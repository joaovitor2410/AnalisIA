"""Workspace efêmero de um visitante: dados, conexões e modelo pertencem à sessão."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from weakref import finalize

from pydantic_ai.models import Model

from olheiro.config import Settings, resource_path
from olheiro.datasets import import_dataset
from olheiro.db import find_data_files
from olheiro.import_options import load_import_options

if TYPE_CHECKING:
    from olheiro.ui.resources import AppResources


def cleanup(folder: TemporaryDirectory[str], resources: dict[str, "AppResources"]) -> None:
    for resource in resources.values():
        resource.con.close()
    resources.clear()
    folder.cleanup()


@dataclass
class VisitorWorkspace:
    settings: Settings
    folder: TemporaryDirectory[str]
    resources: dict[str, "AppResources"] = field(default_factory=dict)
    model: Model | None = None
    model_name: str = "google:gemini-3.8-flash"

    def __post_init__(self) -> None:
        self._cleanup = finalize(self, cleanup, self.folder, self.resources)

    def close(self) -> None:
        self.model = None
        self._cleanup()


def create_workspace(public: Settings) -> VisitorWorkspace:
    folder = TemporaryDirectory(prefix="analisia-visitor-")
    root = Path(folder.name)
    base = public.model_copy(
        update={
            "olheiro_demo_mode": False,
            "olheiro_demo_model_enabled": False,
            "olheiro_session_question_limit": None,
            "datasets_dir": root / "datasets",
            "olheiro_dataset": None,
            "olheiro_workspace_override": None,
            "runs_path": root / "runs.jsonl",
            "traces_path": root / "traces.jsonl",
            "olheiro_tracing": "off",
            "olheiro_trace_content": False,
        }
    )
    profiles = [
        ("loja", "Loja demonstrativa · 120 pedidos", "examples/datasets/portfolio"),
        ("vendas", "Vendas · exemplo pequeno", "examples/datasets/retail"),
        ("estoque", "Estoque · produtos e fornecedores", "evals/fixtures/inventory"),
    ]
    try:
        manifests = []
        for name, title, relative in profiles:
            source = resource_path(relative)
            manifests.append(
                import_dataset(
                    find_data_files(source),
                    base.datasets_dir,
                    name,
                    title,
                    glossary=source / "glossary.toml",
                    options=load_import_options(source / "import-options.json"),
                )
            )
        return VisitorWorkspace(base.for_dataset(manifests[0]), folder)
    except BaseException:
        folder.cleanup()
        raise


_current: ContextVar[VisitorWorkspace | None] = ContextVar("visitor_workspace", default=None)


def current_workspace() -> VisitorWorkspace | None:
    return _current.get()


@contextmanager
def workspace_scope(workspace: VisitorWorkspace) -> Iterator[None]:
    token = _current.set(workspace)
    try:
        yield
    finally:
        _current.reset(token)
