"""Testes da observabilidade: árvore de spans, registro de execuções, privacidade e a página
Operação. Usam um exportador em memória e um modelo roteirizado (sem rede, sem cota)."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import models
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
from streamlit.testing.v1 import AppTest

from olheiro.agent import AgentDeps, PendingApproval, ask, resume
from olheiro.db import connect, connect_agent
from olheiro.pricing import cost_usd
from olheiro.storage import JsonLines
from olheiro.telemetry import RunLog, RunRecord, Source, tracked
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
    assert record.usage_status == "unknown"


@pytest.mark.parametrize("source", ["app", "cli", "mcp"])
def test_error_preserves_received_usage_without_call_site_changes(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, source: Source
) -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(message, ModelResponse) for message in messages):
            raise UnexpectedModelBehavior("falha após a primeira resposta")
        return ModelResponse(
            parts=[ToolCallPart("run_sql", {"query": SQL})],
            usage=RequestUsage(input_tokens=1000, output_tokens=20),
        )

    log = RunLog(tmp_path / "partial.jsonl")
    with pytest.raises(UnexpectedModelBehavior), tracked(log, QUESTION, source):
        ask(QUESTION, AgentDeps(con), FunctionModel(respond, model_name="gemini-3.8-flash"))
    record = log.read()[0]
    assert record.usage_status == "partial" and record.requests >= 1
    assert record.input_tokens == 1000 and record.output_tokens == 20
    assert record.cost_usd == pytest.approx(cost_usd("gemini-3.8-flash", 1000, 20))


def test_approval_resume_does_not_double_count_prior_usage(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not any(isinstance(message, ModelResponse) for message in messages):
            return ModelResponse(
                parts=[ToolCallPart("save_result", {"name": "teste", "query": SQL})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "Flamengo.",
                        "sql": SQL,
                    },
                )
            ]
        )

    deps, log = AgentDeps(con), RunLog(tmp_path / "resume.jsonl")
    model = FunctionModel(respond)
    with tracked(log, QUESTION, "cli") as run:
        pending = run.finish(ask(QUESTION, deps, model))
    assert isinstance(pending, PendingApproval)
    with tracked(log, QUESTION, "cli", phase="resume") as run:
        run.finish(resume(pending, False, deps, model))
    assert [record.requests for record in log.read()] == [1, 1]


def test_nothing_is_recorded_when_there_is_no_outcome(tmp_path: Path) -> None:
    runs = RunLog(tmp_path / "runs.jsonl")
    with tracked(runs, "q", "app"):
        pass  # ex.: limite da sessão atingido, o modelo nem foi chamado
    assert runs.read() == []


def test_logging_failure_does_not_mask_the_original_error_or_leak_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runs = RunLog(tmp_path / "runs.jsonl", include_content=False)

    def fail(record: RunRecord) -> None:
        raise OSError("erro interno contendo informação privada")

    monkeypatch.setattr(runs.file, "append", fail)
    with (
        pytest.raises(RuntimeError, match="erro original"),
        tracked(runs, "pergunta privada", "app"),
    ):
        raise RuntimeError("erro original")
    assert "não foi possível" in caplog.text.lower()
    assert "privada" not in caplog.text and "erro original" not in caplog.text


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


def test_trace_reader_finds_spans_across_retained_files(tmp_path: Path) -> None:
    memory = InMemorySpanExporter()
    configure_tracing(SimpleSpanProcessor(memory), include_content=False)
    with tracer().start_as_current_span("raiz") as root, tracer().start_as_current_span("filho"):
        pass
    spans = memory.get_finished_spans()
    maximum = max(len((span.to_json(indent=None) + "\n").encode()) for span in spans)
    path = tmp_path / "traces.jsonl"
    exporter = JsonLinesSpanExporter(path, max_bytes=maximum + 1, backup_count=3)
    assert exporter.export(spans) == SpanExportResult.SUCCESS
    assert path.with_name(path.name + ".1").exists()
    restored = read_trace(path, format(root.get_span_context().trace_id, "032x"))
    assert [(span.name, span.depth) for span in restored] == [("raiz", 0), ("filho", 1)]


def test_oversized_span_fails_export_without_logging_private_attributes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    memory = InMemorySpanExporter()
    configure_tracing(SimpleSpanProcessor(memory), include_content=True)
    with tracer().start_as_current_span("raiz", attributes={"pergunta": "dado privado"}):
        pass
    exporter = JsonLinesSpanExporter(tmp_path / "traces.jsonl", max_bytes=10, backup_count=1)
    assert exporter.export(memory.get_finished_spans()) == SpanExportResult.FAILURE
    assert "dado privado" not in caplog.text


def test_trace_reader_skips_incomplete_or_invalid_spans_and_bounds_cycles(tmp_path: Path) -> None:
    trace_id = "a" * 32
    good = {
        "name": "válido",
        "context": {"trace_id": f"0x{trace_id}", "span_id": "root"},
        "parent_id": None,
        "start_time": "2026-11-06T10:00:00+00:00",
        "end_time": "2026-11-06T10:00:01+00:00",
        "attributes": {},
    }
    broken = [
        {"context": {"trace_id": f"0x{trace_id}"}},
        {"context": None, "id": f"0x{trace_id}"},
        {**good, "start_time": "data inválida"},
        {**good, "start_time": "2026-11-06T10:00:00"},
        {**good, "end_time": "2026-11-06T09:00:00+00:00"},
        {**good, "attributes": "formato inválido"},
        {**good, "parent_id": 123},
    ]
    path = tmp_path / "traces.jsonl"
    path.write_text("\n".join(json.dumps(span) for span in [*broken, good]) + "\n")
    views = read_trace(path, trace_id)
    assert len(views) == 1 and views[0].name == "válido" and views[0].depth == 0
    cycle = [
        {**good, "context": {"trace_id": f"0x{trace_id}", "span_id": name}, "parent_id": parent}
        for name, parent in [("a", "b"), ("b", "a")]
    ]
    path.write_text("\n".join(json.dumps(span) for span in cycle) + "\n")
    assert [view.depth for view in read_trace(path, trace_id)] == [1, 1]


def test_cost_accepts_provider_prefix_and_unknown_models() -> None:
    assert cost_usd("google:gemini-3.8-flash", 1_000_000, 0) == pytest.approx(0.75)
    assert cost_usd("gemini-3.5-flash-lite", 0, 1_000_000) == pytest.approx(2.50)
    assert cost_usd("modelo-desconhecido", 10, 10) is None


def run_ops_page() -> None:
    from olheiro.ui.ops_page import ops_page

    ops_page()


@pytest.mark.parametrize("source", ["app", "mcp"])
def test_ops_page_shows_kpis_and_the_trace_waterfall(
    con: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: Source,
) -> None:
    import streamlit as st

    traces = tmp_path / "traces.jsonl"
    configure_tracing(SimpleSpanProcessor(JsonLinesSpanExporter(traces)), include_content=True)
    runs = RunLog(tmp_path / "runs.jsonl")
    with tracked(runs, QUESTION, source) as run:
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
