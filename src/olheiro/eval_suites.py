"""Suítes reproduzíveis: fixtures versionadas, sem abrir a base ou o workspace pessoal."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from olheiro.config import PROJECT_ROOT, RESOURCE_ROOT, resource_path
from olheiro.db import connect, connect_agent, find_data_files, load_raw_dir
from olheiro.import_options import load_import_options
from olheiro.semantic import Glossary, check_glossary, load_glossary


@dataclass(frozen=True)
class EvalSuite:
    name: str
    cases: Path
    data: Path
    glossary: Path
    options: Path | None = None

    def revision(self) -> str:
        """Identifica dados, regras, opções e perguntas usados nesta rodada."""
        digest = hashlib.sha256()
        paths = [self.cases, self.glossary, *find_data_files(self.data)]
        if self.options is not None:
            paths.append(self.options)
        for path in paths:
            base = RESOURCE_ROOT if path.is_relative_to(RESOURCE_ROOT) else PROJECT_ROOT
            digest.update(str(path.relative_to(base)).encode())
            digest.update(b"\x00")
            digest.update(path.read_bytes())
        return digest.hexdigest()


SUITES = {
    "brasileirao": EvalSuite(
        "brasileirao",
        resource_path("evals/cases.yaml"),
        resource_path("data/raw"),
        resource_path("semantic/glossary.toml"),
    ),
    "vendas": EvalSuite(
        "vendas",
        resource_path("evals/vendas.yaml"),
        resource_path("examples/datasets/retail"),
        resource_path("examples/datasets/retail/glossary.toml"),
        resource_path("examples/datasets/retail/import-options.json"),
    ),
    "estoque": EvalSuite(
        "estoque",
        resource_path("evals/estoque.yaml"),
        resource_path("evals/fixtures/inventory"),
        resource_path("evals/fixtures/inventory/glossary.toml"),
        resource_path("evals/fixtures/inventory/import-options.json"),
    ),
}


@contextmanager
def suite_database(suite: EvalSuite) -> Iterator[tuple[duckdb.DuckDBPyConnection, Glossary]]:
    """Carga igual à importação pessoal; avaliação usa raw em leitura e workspace descartável."""
    with TemporaryDirectory(prefix=f"analisia-eval-{suite.name}-") as folder:
        database = Path(folder) / "source.duckdb"
        with connect(database) as loader:
            load_raw_dir(loader, suite.data, load_import_options(suite.options))
        with connect_agent(database, Path(folder) / "workspace.duckdb") as con:
            glossary = load_glossary(suite.glossary)
            problems = check_glossary(glossary, con, require_complete=False)
            if problems:
                raise ValueError("Glossário incompatível: " + "; ".join(problems))
            yield con, glossary
