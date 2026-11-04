"""Isolamento comum a todos os testes: nada de traces ou registros nos arquivos reais de data/."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from olheiro.tracing import reset_tracing


@pytest.fixture(autouse=True)
def isolated_observability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OLHEIRO_TRACING", "off")
    monkeypatch.setenv("RUNS_PATH", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("TRACES_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setenv("OLHEIRO_DEMO_BUDGET_PATH", str(tmp_path / "demo-budget.json"))
    yield
    reset_tracing()  # o tracing é global no processo: um teste não pode vazar para o outro
