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

from olheiro.agent import ask, build_model
from olheiro.config import Settings
from olheiro.db import connect

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
    with connect(db_path, read_only=True) as read_only_con:
        yield read_only_con


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


def call_tool(name: str, **args: object) -> Step:
    return lambda info: ModelResponse(parts=[ToolCallPart(name, args)])


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

    report = ask("Quem foram os campeões?", con, script.model())

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
            "precisa ser uma coluna numérica",
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

    report = ask("pergunta", con, script.model())

    retries = parts_of(script.received[1], RetryPromptPart)
    assert expected_retry in str(retries[0].content)
    assert report.evidence is not None


def test_unanswerable_question_returns_without_evidence(con: duckdb.DuckDBPyConnection) -> None:
    script = ScriptedModel(answer(answerable=False, answer="Não há dados de artilharia."))

    report = ask("Quem foi o artilheiro de 2019?", con, script.model())

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
