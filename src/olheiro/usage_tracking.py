"""Consumo recebido antes de uma falha, compartilhado por contexto sem acoplar ao logger."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage


def counters(usage: RunUsage) -> tuple[int, int, int, int]:
    return usage.requests, usage.input_tokens, usage.output_tokens, usage.tool_calls


@dataclass
class UsageCapture:
    usage: RunUsage | None = None
    baseline: tuple[int, int, int, int] = (0, 0, 0, 0)
    received: tuple[int, int, int, int] = (0, 0, 0, 0)
    models: set[str] = field(default_factory=set)

    def totals(self) -> tuple[int, int, int, int]:
        current = counters(self.usage) if self.usage is not None else self.baseline
        values = tuple(
            a + max(0, b - c) for a, b, c in zip(self.received, current, self.baseline, strict=True)
        )
        return values[0], values[1], values[2], values[3]

    def bind(self, usage: RunUsage, model: Model | None) -> None:
        self.received = self.totals()
        self.usage, self.baseline = usage, counters(usage)
        if model is not None:
            self.models.add(model.model_name)


_capture: ContextVar[UsageCapture | None] = ContextVar("usage_capture", default=None)


@contextmanager
def capture_usage() -> Iterator[UsageCapture]:
    capture = UsageCapture()
    token = _capture.set(capture)
    try:
        yield capture
    finally:
        _capture.reset(token)


def bind_usage(usage: RunUsage, model: Model | None) -> None:
    capture = _capture.get()
    if capture is not None:
        capture.bind(usage, model)
