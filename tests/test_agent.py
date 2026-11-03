"""Testes do agente com um modelo roteirizado (FunctionModel): sem rede, sem cota."""

from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import pytest
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.google import GoogleModel

from olheiro.agent import AgentDeps, AgentReport, PendingApproval, ask, build_model, resume
from olheiro.config import Settings
from olheiro.db import connect, connect_agent

# Qualquer chamada acidental a um modelo de verdade falha o teste.
models.ALLOW_MODEL_REQUESTS = False

CHAMPIONS_SQL = "SELECT season, points FROM raw.brasileirao WHERE place = 1 ORDER BY season"

Step = Callable[[AgentInfo], ModelResponse]


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    db_path = tmp_path / "test.duckdb"
    with connect(db_path) as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute(
            """
            CREATE TABLE raw.brasileirao AS
            SELECT * FROM (VALUES (2019, 1, 'Flamengo', 90), (2019, 2, 'Santos', 74),
                                  (2020, 1, 'Flamengo', 71)) AS t(season, place, team, points)
            """
        )
    # A mesma conexão blindada da CLI: raw somente leitura, workspace gravável.
    with connect_agent(db_path, tmp_path / "workspace.duckdb") as agent_con:
        yield agent_con


class ScriptedModel:
    """Modelo falso: devolve os passos em ordem e guarda as mensagens recebidas em cada um."""

    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.received: list[list[ModelMessage]] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.received.append(list(messages))
        return self.steps.pop(0)(info)

    def model(self) -> FunctionModel:
        return FunctionModel(self)


def call_tool(tool_name: str, /, **args: object) -> Step:
    return lambda info: ModelResponse(parts=[ToolCallPart(tool_name, args)])


def answer(**fields: object) -> Step:
    """A resposta final chega pela ferramenta de saída que o Pydantic AI cria para a saída."""
    return lambda info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, fields)])


def parts_of[T](messages: list[ModelMessage], kind: type[T]) -> list[T]:
    return [part for message in messages for part in message.parts if isinstance(part, kind)]


def test_answer_uses_tools_and_reexecutes_evidence(con: duckdb.DuckDBPyConnection) -> None:
    chart = {"kind": "line", "x": "season", "y": "points", "title": "Pontos do campeão"}
    script = ScriptedModel(
        call_tool("profile_column", table="raw.brasileirao", column="team"),
        answer(answerable=True, answer="Flamengo.", sql=CHAMPIONS_SQL, chart=chart),
    )

    report = ask("Quem foram os campeões?", AgentDeps(con), script.model())

    tool_result = parts_of(script.received[1], ToolReturnPart)[0].content
    assert "Flamengo" in tool_result["result"]
    assert report.evidence is not None
    assert report.evidence.rows == [(2019, 90), (2020, 71)]
    assert report.output.chart is not None and report.output.chart.kind == "line"


@pytest.mark.parametrize(
    ("bad_answer", "expected_retry"),
    [
        ({"sql": None}, "Resposta sem evidência"),
        ({"sql": "SELECT gols FROM raw.brasileirao"}, "SQL de evidência falhou"),
        (
            {
                "sql": CHAMPIONS_SQL,
                "chart": {"kind": "bar", "x": "team", "y": "points", "title": "t"},
            },
            "colunas fora do resultado",
        ),
        (
            {
                "sql": "SELECT team, season FROM raw.brasileirao",
                "chart": {"kind": "bar", "x": "season", "y": "team", "title": "t"},
            },
            "precisa ser numérica",
        ),
    ],
)
def test_invalid_evidence_makes_the_model_retry(
    con: duckdb.DuckDBPyConnection, bad_answer: dict[str, object], expected_retry: str
) -> None:
    script = ScriptedModel(
        answer(answerable=True, answer="x", **bad_answer),
        answer(answerable=True, answer="x", sql=CHAMPIONS_SQL),
    )

    report = ask("pergunta", AgentDeps(con), script.model())

    retries = parts_of(script.received[1], RetryPromptPart)
    assert expected_retry in str(retries[0].content)
    assert report.evidence is not None


def test_unanswerable_question_returns_without_evidence(con: duckdb.DuckDBPyConnection) -> None:
    script = ScriptedModel(answer(answerable=False, answer="Não há dados de artilharia."))

    report = ask("Quem foi o artilheiro de 2019?", AgentDeps(con), script.model())

    assert report.output.answerable is False
    assert report.evidence is None
    assert len(script.received) == 1


def test_build_model_without_fallback() -> None:
    settings = Settings(_env_file=None, olheiro_model="google:gemini-3.8-flash", google_api_key="x")
    model = build_model(settings)
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-3.8-flash"


def test_build_model_with_fallback() -> None:
    settings = Settings(
        _env_file=None,
        olheiro_model="google:gemini-3.8-flash",
        olheiro_fallback_model="google:gemini-3.5-flash",
        google_api_key="x",
    )
    model = build_model(settings)
    assert isinstance(model, FallbackModel)
    assert [m.model_name for m in model.models] == ["gemini-3.8-flash", "gemini-3.5-flash"]
    # Principal falha na hora (o fallback entra sem atraso); só o reserva tem retentativas.
    assert [m.settings["max_retries"] for m in model.models] == [0, 2]


@pytest.mark.parametrize(
    ("model_id", "api_key", "message"),
    [
        ("anthropic:claude-haiku-5-5", "x", "ainda não suportado"),
        ("google:gemini-3.8-flash", None, "GOOGLE_API_KEY"),
    ],
)
def test_build_model_rejects_invalid_config(
    model_id: str, api_key: str | None, message: str
) -> None:
    settings = Settings(_env_file=None, olheiro_model=model_id, google_api_key=api_key)
    with pytest.raises(ValueError, match=message):
        build_model(settings)


def report_of(outcome: AgentReport | PendingApproval) -> AgentReport:
    assert isinstance(outcome, AgentReport)
    return outcome


def saved_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = 'workspace'"
    ).fetchall()
    return [name for (name,) in rows]


def test_save_result_pauses_for_approval_and_writes_when_approved(
    con: duckdb.DuckDBPyConnection,
) -> None:
    script = ScriptedModel(
        call_tool("save_result", name="campeoes", query=CHAMPIONS_SQL),
        answer(answerable=True, answer="Salvei.", sql="SELECT * FROM workspace.campeoes"),
    )
    deps = AgentDeps(con)

    pending = ask("Salve os campeões", deps, script.model())

    assert isinstance(pending, PendingApproval)
    assert [(s.name, s.query) for s in pending.saves] == [("campeoes", CHAMPIONS_SQL)]
    assert saved_tables(con) == []  # nada é gravado antes da decisão do usuário

    report = report_of(resume(pending, approved=True, deps=deps, model=script.model()))

    assert saved_tables(con) == ["campeoes"]
    assert report.evidence is not None and report.evidence.rows == [(2019, 90), (2020, 71)]


def test_denied_save_writes_nothing_and_tells_the_model(con: duckdb.DuckDBPyConnection) -> None:
    script = ScriptedModel(
        call_tool("save_result", name="campeoes", query=CHAMPIONS_SQL),
        answer(answerable=True, answer="Ok, não salvei.", sql=CHAMPIONS_SQL),
    )
    deps = AgentDeps(con)

    pending = ask("Salve os campeões", deps, script.model())
    assert isinstance(pending, PendingApproval)
    report_of(resume(pending, approved=False, deps=deps, model=script.model()))

    assert saved_tables(con) == []
    denial = parts_of(script.received[1], ToolReturnPart)[-1].content
    assert "não autorizou" in str(denial)


def test_invalid_save_request_is_refused_without_asking_the_user(
    con: duckdb.DuckDBPyConnection,
) -> None:
    script = ScriptedModel(
        call_tool("save_result", name="Campeões!", query="DROP TABLE raw.brasileirao"),
        answer(answerable=True, answer="x", sql=CHAMPIONS_SQL),
    )

    outcome = ask("Salve", AgentDeps(con), script.model())

    assert isinstance(outcome, AgentReport)  # não pausou: não havia o que aprovar
    refusal = parts_of(script.received[1], ToolReturnPart)[0].content
    assert "Nome 'Campeões!' inválido" in refusal["error"]


def test_destructive_sql_from_the_model_is_refused_and_raw_stays_intact(
    con: duckdb.DuckDBPyConnection,
) -> None:
    script = ScriptedModel(
        call_tool("run_sql", query="DROP TABLE raw.brasileirao"),
        answer(answerable=True, answer="x", sql=CHAMPIONS_SQL),
    )

    ask("Apague a tabela", AgentDeps(con), script.model())

    refusal = parts_of(script.received[1], ToolReturnPart)[0].content
    assert refusal["error"].startswith("Consulta recusada")
    assert con.execute("SELECT count(*) FROM raw.brasileirao").fetchone()[0] == 3


def test_agent_discovers_and_analyzes_a_table_omitted_from_the_initial_context() -> None:
    from olheiro.semantic import render_context

    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute("ATTACH ':memory:' AS workspace")
        for n in range(25):
            con.execute(f"CREATE TABLE raw.t{n:02d} AS SELECT 1 AS a, 2 AS b, 3 AS c, 4 AS d")
        con.execute("CREATE TABLE raw.z_vendas AS SELECT 125 AS valor")
        deps = AgentDeps(con)
        assert "raw.z_vendas" not in render_context(deps.glossary, con)
        script = ScriptedModel(
            call_tool("discover_tables", search="z_vendas"),
            call_tool("describe_table", table="raw.z_vendas"),
            answer(
                answerable=True, answer="O total é 125.", sql="SELECT sum(valor) FROM raw.z_vendas"
            ),
        )
        result = ask("Qual o total de vendas?", deps, script.model())
        assert isinstance(result, AgentReport) and result.evidence.rows == [(125,)]
        assert "raw.z_vendas" in str(parts_of(script.received[1], ToolReturnPart)[0].content)
        assert "valor INTEGER" in str(parts_of(script.received[2], ToolReturnPart)[-1].content)
