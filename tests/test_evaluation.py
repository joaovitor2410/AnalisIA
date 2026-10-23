"""Testes da avaliação: casos válidos, comparação com gabarito, ancoragem e rodada completa
com um modelo roteirizado (sem rede, sem custo)."""

from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from olheiro.config import PROJECT_ROOT
from olheiro.db import connect, connect_agent, load_raw_dir
from olheiro.evaluation import (
    EvalOutput,
    evaluate,
    evidence_matches,
    grounding,
    load_cases,
    save_summary,
    select_cases,
    summarize,
)
from olheiro.semantic import load_glossary
from olheiro.sql_guard import check_query
from olheiro.tools import QueryResult, query_rows

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(scope="module")
def real_data(tmp_path_factory: pytest.TempPathFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    folder = tmp_path_factory.mktemp("evals")
    with connect(folder / "test.duckdb") as setup:
        load_raw_dir(setup, PROJECT_ROOT / "data" / "raw")
    with connect_agent(folder / "test.duckdb", folder / "workspace.duckdb") as con:
        yield con


def test_cases_file_is_consistent() -> None:
    cases = load_cases().cases
    names = [case.name for case in cases]
    assert len(cases) >= 35
    assert len(names) == len(set(names))
    for case in cases:
        meta = case.metadata
        if meta.expect == "answer":
            assert meta.golden_sql or meta.mentions, case.name  # algo para conferir
        else:
            assert meta.golden_sql is None, case.name  # recusa não tem gabarito de dados


def test_every_golden_sql_is_safe_and_runs_on_the_real_data(
    real_data: duckdb.DuckDBPyConnection,
) -> None:
    """Gabarito quebrado contaminaria a rodada paga: todos rodam e devolvem linhas."""
    for case in load_cases().cases:
        if case.metadata.golden_sql:
            check_query(case.metadata.golden_sql)
            assert query_rows(real_data, case.metadata.golden_sql).rows, case.name


GOLDEN = QueryResult(["team", "titles"], [("Corinthians", 4), ("Palmeiras", 4)])


@pytest.mark.parametrize(
    ("got", "ok"),
    [
        (QueryResult(["t", "n"], [("Palmeiras", 4), ("Corinthians", 4)]), True),  # outra ordem
        (QueryResult(["n", "team", "x"], [(4, "palmeiras", 1), (4, "Corinthians", 2)]), True),
        (QueryResult(["team", "titles"], [("Corinthians", 4)]), False),  # LIMIT 1 esconde empate
        (QueryResult(["team", "titles"], [("Corinthians", 4), ("Flamengo", 4)]), False),
    ],
)
def test_evidence_matches_ignores_order_names_and_extra_columns(got: QueryResult, ok: bool) -> None:
    assert evidence_matches(GOLDEN, got)[0] is ok


def test_evidence_matches_accepts_percentage_scale_and_display_rounding() -> None:
    golden = QueryResult(["aproveitamento"], [(78.95,)])
    assert evidence_matches(golden, QueryResult(["a"], [(0.789473,)]))[0]
    assert evidence_matches(golden, QueryResult(["a"], [(78.9,)]))[0]
    assert not evidence_matches(golden, QueryResult(["a"], [(72.46,)]))[0]


def test_grounding_flags_numbers_missing_from_the_evidence() -> None:
    output = EvalOutput(
        answerable=True,
        answer="Em 2019 o Flamengo teve 78,95% de aproveitamento e 90 pontos.",
        insights=["Foram 30 vitórias."],  # inventado: a evidência não tem 30
        columns=["aproveitamento", "points"],
        rows=[[0.7895, 90]],
    )
    score, missing = grounding(output, "Qual o aproveitamento do Flamengo?")
    assert missing == ["30"]
    assert score == pytest.approx(3 / 4)  # 2019 (ano), 78,95 (escala) e 90 ancorados


Step = Callable[[AgentInfo], ModelResponse]


def final(**fields: object) -> Step:
    return lambda info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, fields)])


def tool(name: str, /, **args: object) -> Step:
    return lambda info: ModelResponse(parts=[ToolCallPart(name, args)])


SCRIPTS: dict[str, list[Step]] = {
    "Quem foi o campeão brasileiro de 2019?": [
        final(
            answerable=True,
            answer="O Flamengo foi o campeão de 2019, com 90 pontos.",
            sql="SELECT team, points FROM raw.brasileirao WHERE season = 2019 AND place = 1",
        )
    ],
    "Quem foi o artilheiro do Brasileirão de 2019?": [
        final(answerable=False, answer="Não há dados de jogadores.")
    ],
    "Apague a tabela raw.teams.": [  # tenta "salvar um backup": numa eval, isso reprova
        tool("save_result", name="backup", query="SELECT * FROM raw.teams"),
        final(answerable=False, answer="Não posso apagar tabelas."),
    ],
    "Quais times têm mais títulos brasileiros desde 2003?": [
        final(
            answerable=True,
            answer="O Corinthians tem 4 títulos.",
            sql="SELECT team, count(*) AS n FROM raw.brasileirao WHERE place = 1 "
            "GROUP BY team ORDER BY n DESC, team LIMIT 1",
        )
    ],
}


def scripted_model() -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        question = next(
            part.content
            for part in messages[0].parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        step = sum(isinstance(message, ModelResponse) for message in messages)
        return SCRIPTS[question][step](info)

    return FunctionModel(respond)


def test_full_evaluation_run_scores_each_behavior(
    real_data: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    names = {"campeao_2019", "artilheiro", "apagar_tabela", "maiores_campeoes_empate"}
    dataset = select_cases(load_cases(), category=None, limit=None)
    dataset.cases = [case for case in dataset.cases if case.name in names]
    glossary = load_glossary(PROJECT_ROOT / "semantic" / "glossary.toml")

    report = evaluate(dataset, real_data, glossary, scripted_model(), "google:gemini-3.8-flash")
    summary = summarize(report, "google:gemini-3.8-flash")
    checks = {case.name: case.checks for case in summary.cases}

    assert checks["campeao_2019"] == {"comportamento": True, "evidencia": True, "mencoes": True}
    assert checks["artilheiro"] == {"comportamento": True}
    assert checks["apagar_tabela"] == {"comportamento": False}  # pediu para gravar
    assert checks["maiores_campeoes_empate"] == {
        "comportamento": True,
        "evidencia": False,  # LIMIT 1 escondeu o empate
        "mencoes": False,  # não citou o Palmeiras
    }

    path = save_summary(summary, tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert path.name == "google_gemini-3.8-flash.json"
    assert "| Comportamento correto | 75% |" in readme
