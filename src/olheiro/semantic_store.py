"""Edição explícita da semântica de bases importadas, com publicação atômica do manifesto."""

import fcntl
import hashlib
import json
import os
import tomllib
from pathlib import Path
from tempfile import NamedTemporaryFile

import duckdb

from olheiro.config import DatasetManifest, Settings
from olheiro.semantic import Glossary, check_glossary


def manifest_revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glossary_toml(glossary: Glossary) -> str:
    """Serializa chaves e textos como strings TOML, inclusive aspas, acentos e quebras."""

    def quoted(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [f"rules = {quoted(glossary.rules)}"]
    for table, doc in glossary.tables.items():
        prefix = f"tables.{quoted(table)}"
        lines += [f"\n[{prefix}]", f"description = {quoted(doc.description)}"]
        for column, description in doc.columns.items():
            lines += [
                f"\n[{prefix}.columns.{quoted(column)}]",
                f"description = {quoted(description.description)}",
                f"unit = {quoted(description.unit)}",
                f"list_values = {str(description.list_values).lower()}",
            ]
    return "\n".join(lines) + "\n"


def atomic_text(path: Path, content: str) -> None:
    """O destino só muda depois da escrita completa; erro remove apenas o temporário."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_dataset_glossary(
    settings: Settings,
    con: duckdb.DuckDBPyConnection,
    glossary: Glossary,
    expected_revision: str,
) -> Settings:
    """Valida e publica uma versão; a demo e a semântica versionada do exemplo não são editadas."""
    if settings.olheiro_demo_mode or settings.olheiro_dataset is None:
        raise ValueError("A edição está disponível apenas para bases pessoais importadas.")
    problems = check_glossary(glossary, con, require_complete=False)
    if problems:
        raise ValueError("Glossário incompatível: " + "; ".join(problems))
    path = settings.olheiro_dataset
    with (path.parent / ".semantics.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if manifest_revision(path) != expected_revision:
            raise ValueError("A semântica mudou em outra sessão. Recarregue antes de salvar.")
        manifest = DatasetManifest.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        content = glossary_toml(glossary)
        filename = f"glossary.{hashlib.sha256(content.encode()).hexdigest()}.toml"
        # O arquivo anterior continua válido para leitores que já abriram o manifesto.
        atomic_text(path.parent / filename, content)
        manifest.glossary, manifest.glossary_file = True, filename
        atomic_text(
            path,
            (
                f"version = 1\ntitle = {json.dumps(manifest.title, ensure_ascii=False)}\n"
                f"glossary = true\nglossary_file = {json.dumps(filename)}\n"
            ),
        )
    return settings.for_dataset(path)
