"""Traces OpenTelemetry do agente (padrão de mercado, sem amarrar a um fornecedor).

Cada pergunta vira uma árvore de spans: olheiro.pergunta > invoke_agent > chat (requisição ao
modelo, com tokens) e execute_tool (cada SQL). Os spans do agente vêm da instrumentação do
Pydantic AI; o span raiz vem de olheiro.telemetry.

Destinos (OLHEIRO_TRACING): "file" grava JSONL local (lido pela página Operação), "otlp"
envia a qualquer backend OpenTelemetry (Jaeger, Grafana Tempo, Phoenix, Logfire), "off" desliga.

O OpenTelemetry é global por processo: este é o único módulo com estado global, e
setup_tracing pode ser chamado várias vezes (só a primeira configura).
"""

import atexit
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings

from olheiro.config import Settings
from olheiro.storage import DEFAULT_LOG_BACKUP_COUNT, DEFAULT_LOG_MAX_BYTES, JsonLinesFile

TRACER_NAME = "olheiro"

_provider: TracerProvider | None = None
_include_content = False


class JsonLinesSpanExporter(SpanExporter):
    """Grava cada span como uma linha JSON: trace local, sem nenhuma infraestrutura."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = DEFAULT_LOG_MAX_BYTES,
        backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
    ) -> None:
        self.path = path
        self.file = JsonLinesFile(path, max_bytes=max_bytes, backup_count=backup_count)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = [span.to_json(indent=None).replace("\n", " ") for span in spans]
        try:
            written = self.file.append(lines)
        except OSError as error:
            logging.getLogger(__name__).warning(
                "Não foi possível gravar os traces locais (%s).",
                type(error).__name__,
            )
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS if written == len(lines) else SpanExportResult.FAILURE


def configure_tracing(processor: SpanProcessor, include_content: bool) -> TracerProvider:
    """Liga a instrumentação do Pydantic AI a um provider próprio (os testes passam o deles)."""
    global _provider, _include_content
    provider = TracerProvider(resource=Resource.create({"service.name": "olheiro"}))
    provider.add_span_processor(processor)
    Agent.instrument_all(
        InstrumentationSettings(tracer_provider=provider, include_content=include_content)
    )
    _provider, _include_content = provider, include_content
    return provider


def setup_tracing(settings: Settings) -> None:
    """Configura conforme o .env, uma vez por processo. Os spans saem em lote (sem atrasar a
    resposta) e o atexit garante que os pendentes sejam gravados quando a CLI termina."""
    if _provider is not None or settings.olheiro_tracing == "off":
        return
    exporter: SpanExporter = (
        JsonLinesSpanExporter(
            settings.traces_path,
            max_bytes=settings.olheiro_log_max_bytes,
            backup_count=settings.olheiro_log_backup_count,
        )
        if settings.olheiro_tracing == "file"
        else OTLPSpanExporter(endpoint=settings.olheiro_otlp_endpoint)
    )
    provider = configure_tracing(BatchSpanProcessor(exporter), settings.olheiro_trace_content)
    atexit.register(provider.shutdown)


def reset_tracing() -> None:
    """Desliga a instrumentação (usado pelos testes para isolar um do outro)."""
    global _provider, _include_content
    Agent.instrument_all(False)
    _provider, _include_content = None, False


def tracer() -> trace.Tracer:
    """Tracer do projeto; sem setup, devolve um tracer que não grava nada."""
    provider = _provider if _provider is not None else trace.get_tracer_provider()
    return provider.get_tracer(TRACER_NAME)


def content_enabled() -> bool:
    """Se perguntas e respostas podem ir para os traces (OLHEIRO_TRACE_CONTENT)."""
    return _include_content


@dataclass(frozen=True)
class SpanView:
    """Um span lido do arquivo, pronto para a cascata (profundidade = nível na árvore)."""

    name: str
    span_id: str
    parent_id: str | None
    start: datetime
    end: datetime
    depth: int
    attributes: dict[str, Any]

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def parse_span(line: str, wanted: str) -> SpanView | None:
    """Valida também a estrutura: JSON válido pode conter um span incompleto/incompatível."""
    try:
        span = json.loads(line)
        if span["context"]["trace_id"] != wanted:
            return None
        name, span_id, parent = span["name"], span["context"]["span_id"], span["parent_id"]
        attributes = span.get("attributes")
        if attributes is None:
            attributes = {}
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(span_id, str)
            or not span_id
            or (parent is not None and not isinstance(parent, str))
            or not isinstance(attributes, dict)
        ):
            return None
        start, end = (
            datetime.fromisoformat(span["start_time"]),
            datetime.fromisoformat(span["end_time"]),
        )
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            return None
        return SpanView(name, span_id, parent, start, end, 0, attributes)
    except (ValueError, TypeError, KeyError):
        return None


def read_trace(path: Path, trace_id: str) -> list[SpanView]:
    """Lê spans válidos dos arquivos retidos; linha ruim não interrompe a página Operação."""
    wanted = f"0x{trace_id}"  # no arquivo o id vem com prefixo; no RunRecord, sem
    spans = {}
    for line in JsonLinesFile(path).read():
        if wanted in line and (span := parse_span(line, wanted)) is not None:
            spans[span.span_id] = span

    def depth(span_id: str) -> int:
        seen = {span_id}
        parent = spans[span_id].parent_id
        result = 0
        while parent is not None and parent in spans and parent not in seen:
            seen.add(parent)
            result += 1
            parent = spans[parent].parent_id
        return result

    views = [replace(span, depth=depth(span.span_id)) for span in spans.values()]
    return sorted(views, key=lambda view: view.start)
