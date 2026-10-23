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
import threading
from collections.abc import Sequence
from dataclasses import dataclass
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

TRACER_NAME = "olheiro"

_provider: TracerProvider | None = None
_include_content = False


class JsonLinesSpanExporter(SpanExporter):
    """Grava cada span como uma linha JSON: trace local, sem nenhuma infraestrutura."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = [span.to_json(indent=None).replace("\n", " ") for span in spans]
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write("\n".join(lines) + "\n")
        return SpanExportResult.SUCCESS


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
        JsonLinesSpanExporter(settings.traces_path)
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


def read_trace(path: Path, trace_id: str) -> list[SpanView]:
    """Os spans de um trace gravado pelo JsonLinesSpanExporter, em ordem de início."""
    if not path.exists():
        return []
    wanted = f"0x{trace_id}"  # no arquivo o id vem com prefixo; no RunRecord, sem
    raw = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if wanted not in line:
            continue
        try:
            span = json.loads(line)
        except json.JSONDecodeError:
            continue  # linha cortada: ignora
        if span["context"]["trace_id"] == wanted:
            raw.append(span)
    parents: dict[str, str | None] = {span["context"]["span_id"]: span["parent_id"] for span in raw}

    def depth(span_id: str) -> int:
        parent = parents.get(span_id)
        return 1 + depth(parent) if parent is not None and parent in parents else 0

    views = [
        SpanView(
            name=span["name"],
            span_id=span["context"]["span_id"],
            parent_id=span["parent_id"],
            start=datetime.fromisoformat(span["start_time"]),
            end=datetime.fromisoformat(span["end_time"]),
            depth=depth(span["context"]["span_id"]),
            attributes=span.get("attributes") or {},
        )
        for span in raw
    ]
    return sorted(views, key=lambda view: view.start)
