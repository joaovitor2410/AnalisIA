"""Registro de execuções: uma linha por chamada ao agente (data/runs.jsonl).

É a visão de produto da observabilidade (base da página Operação): desfecho, cache, latência,
requisições, tokens e custo equivalente de cada pergunta. O trace_id liga cada linha ao trace
OpenTelemetry correspondente, para ver o passo a passo.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import BaseModel
from pydantic_ai.messages import RetryPromptPart

from olheiro.agent import AgentReport, PendingApproval
from olheiro.errors import explain_model_failure
from olheiro.pricing import cost_usd
from olheiro.storage import JsonLines
from olheiro.tracing import content_enabled, tracer

type Source = Literal["app", "cli", "eval", "mcp"]
type Phase = Literal["ask", "resume"]
type Outcome = Literal["answer", "refusal", "approval", "error"]


class RunRecord(BaseModel):
    at: datetime
    source: Source
    phase: Phase
    question: str
    outcome: Outcome
    from_cache: bool = False
    model: str | None = None
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    retries: int = 0
    cost_usd: float | None = None
    seconds: float
    error: str | None = None
    trace_id: str | None = None


class RunLog:
    def __init__(self, path: Path, *, include_content: bool = True) -> None:
        self.file = JsonLines(path, RunRecord)
        self.include_content = include_content

    def append(self, record: RunRecord) -> None:
        if not self.include_content:
            record = record.model_copy(update={"question": "(conteúdo omitido)", "error": None})
        self.file.append(record)

    def read(self) -> list[RunRecord]:
        return self.file.read()


@dataclass
class Tracking:
    """Onde o chamador entrega o resultado; sem resultado (ex.: limite da sessão), não grava."""

    outcome: AgentReport | PendingApproval | None = None

    def finish[T: AgentReport | PendingApproval](self, outcome: T) -> T:
        self.outcome = outcome
        return outcome


@dataclass(frozen=True)
class RunContext:
    """O que se sabe da chamada antes de ela terminar."""

    at: datetime
    source: Source
    phase: Phase
    question: str


@contextmanager
def tracked(log: RunLog, question: str, source: Source, phase: Phase = "ask") -> Iterator[Tracking]:
    """Mede uma chamada ao agente, abre o span raiz do trace e grava o RunRecord.

    Erros também são gravados (com o motivo) e depois relançados para o chamador tratar.
    """
    tracking = Tracking()
    run = RunContext(datetime.now(), source, phase, question)
    started = perf_counter()
    attributes: dict[str, str] = {"olheiro.source": source, "olheiro.phase": phase}
    if content_enabled() and log.include_content:
        attributes["olheiro.question"] = question
    with tracer().start_as_current_span("olheiro.pergunta", attributes=attributes) as span:
        try:
            yield tracking
        except Exception as error:
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            log.append(error_record(run, error, perf_counter() - started, trace_id_of(span)))
            raise
        if tracking.outcome is None:
            return
        record = outcome_record(run, tracking.outcome, perf_counter() - started, trace_id_of(span))
        span.set_attributes(
            {
                "olheiro.outcome": record.outcome,
                "olheiro.from_cache": record.from_cache,
                "olheiro.requests": record.requests,
            }
        )
        log.append(record)


def error_record(
    run: RunContext, error: Exception, seconds: float, trace_id: str | None
) -> RunRecord:
    return RunRecord(
        at=run.at,
        source=run.source,
        phase=run.phase,
        question=run.question,
        outcome="error",
        seconds=seconds,
        error=explain_model_failure(error),
        trace_id=trace_id,
    )


def outcome_record(
    run: RunContext,
    outcome: AgentReport | PendingApproval,
    seconds: float,
    trace_id: str | None,
) -> RunRecord:
    usage = outcome.usage
    record = RunRecord(
        at=run.at,
        source=run.source,
        phase=run.phase,
        question=run.question,
        outcome="approval",
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        tool_calls=usage.tool_calls,
        seconds=seconds,
        trace_id=trace_id,
    )
    if isinstance(outcome, PendingApproval):
        return record
    record.outcome = "answer" if outcome.output.answerable else "refusal"
    record.from_cache = outcome.from_cache
    record.model = outcome.model_name
    record.retries = sum(
        isinstance(part, RetryPromptPart) for message in outcome.messages for part in message.parts
    )
    if not outcome.from_cache:
        record.cost_usd = cost_usd(outcome.model_name, usage.input_tokens, usage.output_tokens)
    return record


def trace_id_of(span: Span) -> str | None:
    """trace_id em hexadecimal, ou None quando o tracing está desligado (span sem contexto)."""
    context = span.get_span_context()
    return trace.format_trace_id(context.trace_id) if context.is_valid else None
