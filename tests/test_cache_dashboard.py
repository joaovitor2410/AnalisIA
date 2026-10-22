"""Testes do cache de respostas e do dashboard (núcleo, sem interface e sem modelo)."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from olheiro.agent import AgentDeps, AgentReport, AnalysisAnswer, PendingApproval, build_report
from olheiro.cache import AnswerCache, ask_with_cache, normalize_question
from olheiro.charts import ChartSpec
from olheiro.dashboard import DashboardItem, DashboardStore, render_item
from olheiro.db import connect, connect_agent, session_cursor
from olheiro.sql_guard import UnsafeQueryError

models.ALLOW_MODEL_REQUESTS = False

SQL = "SELECT season, points FROM raw.brasileirao WHERE place = 1 ORDER BY season"


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with connect(tmp_path / "test.duckdb") as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute(
            "CREATE TABLE raw.brasileirao AS SELECT * FROM (VALUES (2019, 1, 90), (2020, 1, 71)) "
            "AS t(season, place, points)"
        )
    with connect_agent(tmp_path / "test.duckdb", tmp_path / "workspace.duckdb") as agent_con:
        yield agent_con


def report(con: duckdb.DuckDBPyConnection, sql: str | None = SQL) -> AgentReport:
    output = AnalysisAnswer(answerable=sql is not None, answer="resposta", sql=sql)
    return build_report(output, con, "gemini-teste", RunUsage(requests=3), [])


def test_normalize_question_ignores_case_accents_and_punctuation() -> None:
    assert normalize_question("  Quem foi o CAMPEÃO de 2019?! ") == "quem foi o campeao de 2019"


def test_cache_hit_reexecutes_the_sql_now(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    cache = AnswerCache(tmp_path / "cache.json")
    cache.store("Campeões?", report(con))

    hit = cache.lookup("campeoes", con)

    assert hit is not None and hit.from_cache
    assert hit.usage.requests == 0  # nenhuma requisição ao modelo
    assert hit.evidence is not None and hit.evidence.rows == [(2019, 90), (2020, 71)]
    assert cache.questions() == ["Campeões?"]


def test_cache_entry_with_unsafe_sql_counts_as_a_miss(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    cache = AnswerCache(tmp_path / "cache.json")
    cache.store("q", report(con))
    with cache.file.update() as data:  # alguém editou o arquivo à mão
        data.answers["q"].output.sql = "DROP TABLE raw.brasileirao"
    assert cache.lookup("q", con) is None


def test_paused_runs_are_not_cached(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    model = FunctionModel(
        lambda messages, info: ModelResponse(
            parts=[ToolCallPart("save_result", {"name": "t", "query": SQL})]
        )
    )
    cache = AnswerCache(tmp_path / "cache.json")

    outcome = ask_with_cache("salve", AgentDeps(con), cache, model)

    assert isinstance(outcome, PendingApproval)
    assert cache.questions() == []


def test_pin_and_unpin(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    store = DashboardStore(tmp_path / "dashboard.json")
    item = store.pin("Campeões?", report(con))
    assert [i.id for i in store.read().items] == [item.id]
    store.unpin(item.id)
    assert store.read().items == []


def test_only_answers_with_evidence_can_be_pinned(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="evidência"):
        DashboardStore(tmp_path / "dashboard.json").pin("q", report(con, sql=None))


def test_render_item_reexecutes_sql_and_builds_the_figure(con: duckdb.DuckDBPyConnection) -> None:
    chart = ChartSpec(kind="line", x="season", y="points", title="Pontos")
    rendered = render_item(DashboardItem(title="t", question="q", sql=SQL, chart=chart), con)
    assert rendered.error is None
    assert list(rendered.figure.data[0].y) == [90, 71]


def test_render_item_refuses_unsafe_sql_from_the_file(con: duckdb.DuckDBPyConnection) -> None:
    item = DashboardItem(title="t", question="q", sql="DROP TABLE raw.brasileirao")
    rendered = render_item(item, con)
    assert rendered.error is not None and "leitura" in rendered.error
    assert con.execute("SELECT count(*) FROM raw.brasileirao").fetchone()[0] == 2


def test_session_cursor_keeps_hardening_and_resolves_raw(con: duckdb.DuckDBPyConnection) -> None:
    cursor = session_cursor(con)
    assert cursor.execute("SELECT count(*) FROM raw.brasileirao").fetchone()[0] == 2
    with pytest.raises(duckdb.PermissionException):
        cursor.execute("SELECT * FROM read_csv('/etc/hosts')")


def test_pin_rejects_unsafe_sql(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    unsafe = report(con)
    unsafe.output.sql = "DROP TABLE raw.brasileirao"
    with pytest.raises(UnsafeQueryError):
        DashboardStore(tmp_path / "dashboard.json").pin("q", unsafe)
