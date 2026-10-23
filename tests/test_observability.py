"""Testes da observabilidade: árvore de spans, registro de execuções, privacidade e a página
Operação. Usam um exportador em memória e um modelo roteirizado (sem rede, sem cota)."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from streamlit.testing.v1 import AppTest

from olheiro.agent import AgentDeps, ask
from olheiro.db import connect, connect_agent
from olheiro.pricing import cost_usd
from olheiro.storage import JsonLines
from olheiro.telemetry import RunLog, RunRecord, tracked
from olheiro.tracing import JsonLinesSpanExporter, configure_tracing, read_trace, tracer

models.ALLOW_MODEL_REQUESTS = False

QUESTION = "Quem foi o campeão de 2019?"
SQL = "SELECT team FROM raw.brasileirao WHERE season = 2019 AND place = 1"


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with connect(tmp_path / "test.duckdb") as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute(
            "CREATE TABLE raw.brasileirao AS SELECT 2019 AS season, 1 AS place, 'Flamengo' AS team"
        )
    with connect_agent(tmp_path / "test.duckdb", tmp_path / "workspace.duckdb") as agent_con:
        yield agent_con


def tool_then_answer() -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if sum(isinstance(m, ModelResponse) for m in messages) == 0:
            return ModelResponse(parts=[ToolCallPart("run_sql", {"query": SQL})])
        final = {"answerable": True, "answer": "Flamengo.", "sql": SQL}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, final)])

    return FunctionModel(respond)


def traced_question(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, include_content: bool
) -> tuple[list[ReadableSpan], list[RunRecord]]:
    exporter = InMemorySpanExporter()
    configure_tracing(SimpleSpanProcessor(exporter), include_content=include_content)
    runs = RunLog(tmp_path / "runs.jsonl")
    with tracked(runs, QUESTION, "cli") as run:
        run.finish(ask(QUESTION, AgentDeps(con), tool_then_answer()))
    return list(exporter.get_finished_spans()), runs.read()


def test_question_becomes_a_tree_of_spans_linked_to_the_run_record(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    spans, records = traced_question(con, tmp_path, include_content=True)
    by_name = {span.name: span for span in spans}
    root = by_name["olheiro.pergunta"]
    agent_run = next(span for span in spans if span.name.startswith("invoke_agent"))

    assert root.parent is None
    assert agent_run.parent is not None and agent_run.parent.span_id == root.context.span_id
    assert "execute_tool run_sql" in by_name  # a ferramenta virou span
    assert sum(span.name.startswith("chat") for span in spans) == 2  # duas idas ao modelo
    assert root.attributes is not None and root.attributes["olheiro.question"] == QUESTION

    (record,) = records
    assert record.outcome == "answer" and record.requests == 2 and record.tool_calls == 1
    assert record.trace_id == format(root.context.trace_id, "032x")


def test_traces_can_exclude_questions_and_answers(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    spans, _ = traced_question(con, tmp_path, include_content=False)
    recorded = " ".join(str(value) for span in spans for value in (span.attributes or {}).values())
    assert QUESTION not in recorded
    assert "Flamengo" not in recorded  # nem a resposta, nem o resultado da ferramenta


def test_errors_are_recorded_and_reraised(tmp_path: Path) -> None:
    runs = RunLog(tmp_path / "runs.jsonl")
    with pytest.raises(RuntimeError), tracked(runs, "q", "app"):
        raise RuntimeError("falhou")
    (record,) = runs.read()
    assert record.outcome == "error" and record.error == "RuntimeError: falhou"


def test_nothing_is_recorded_when_there_is_no_outcome(tmp_path: Path) -> None:
    runs = RunLog(tmp_path / "runs.jsonl")
    with tracked(runs, "q", "app"):
        pass  # ex.: limite da sessão atingido, o modelo nem foi chamado
    assert runs.read() == []


def test_file_exporter_round_trip_rebuilds_the_tree(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    configure_tracing(SimpleSpanProcessor(JsonLinesSpanExporter(path)), include_content=False)
    with tracer().start_as_current_span("raiz") as root, tracer().start_as_current_span("filho"):
        pass
    spans = read_trace(path, format(root.get_span_context().trace_id, "032x"))
    assert [(span.name, span.depth) for span in spans] == [("raiz", 0), ("filho", 1)]


def test_json_lines_skips_a_truncated_line(tmp_path: Path) -> None:
    log = JsonLines(tmp_path / "runs.jsonl", RunRecord)
    record = RunRecord(
        at=datetime(2026, 10, 23),
        source="cli",
        phase="ask",
        question="q",
        outcome="answer",
        seconds=1,
    )
    log.append(record)
    with log.path.open("a", encoding="utf-8") as file:
        file.write('{"at": "2026-10-')  # processo morto no meio da escrita
    assert log.read() == [record]


def test_cost_accepts_provider_prefix_and_unknown_models() -> None:
    assert cost_usd("google:gemini-3.8-flash", 1_000_000, 0) == pytest.approx(0.75)
    assert cost_usd("gemini-3.5-flash-lite", 0, 1_000_000) == pytest.approx(2.50)
    assert cost_usd("modelo-desconhecido", 10, 10) is None


def run_ops_page() -> None:
    from olheiro.ui.ops_page import ops_page

    ops_page()


def test_ops_page_shows_kpis_and_the_trace_waterfall(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import streamlit as st

    traces = tmp_path / "traces.jsonl"
    configure_tracing(SimpleSpanProcessor(JsonLinesSpanExporter(traces)), include_content=True)
    runs = RunLog(tmp_path / "runs.jsonl")
    with tracked(runs, QUESTION, "app") as run:
        run.finish(ask(QUESTION, AgentDeps(con), tool_then_answer()))
    monkeypatch.setenv("TRACES_PATH", str(traces))
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "workspace-app.duckdb"))
    st.cache_resource.clear()

    app = AppTest.from_function(run_ops_page, default_timeout=20).run()

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Perguntas"] == "1"
    assert metrics["Requisições/pergunta"] == "2.0"
    assert app.selectbox(key="ops-trace").value is not None  # a cascata tem o que mostrar
    st.cache_resource.clear()
