"""Bases locais: importação transacional, descoberta e identidade do estado persistido.

Cada importação cria uma cópia independente dos arquivos e do banco. O manifesto só é
publicado depois da validação; uma falha não troca a base ativa nem deixa uma base listada.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

import duckdb

from olheiro.config import DatasetManifest, Settings, get_settings
from olheiro.db import find_data_files, load_files, validate_data_files
from olheiro.semantic import check_glossary, load_glossary

DATASET_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def discover_datasets(root: Path) -> dict[Path, str]:
    """Lista somente importações concluídas; manifestos inválidos não derrubam a interface."""
    datasets: dict[Path, str] = {}
    for path in sorted(root.glob("*/dataset.toml")):
        try:
            with path.open("rb") as file:
                manifest = DatasetManifest.model_validate(tomllib.load(file))
            if (path.parent / "source.duckdb").is_file():
                datasets[path.resolve()] = manifest.title
        except (OSError, ValueError):
            continue
    return datasets


def import_dataset(
    files: list[Path], root: Path, name: str, title: str, glossary: Path | None = None
) -> Path:
    """Cria uma base nova sem sobrescrever base, workspace ou arquivos de outra importação."""
    if not DATASET_NAME.fullmatch(name):
        raise ValueError(
            "Identificador inválido: comece com letra e use a-z, 0-9, _ ou - (até 64)."
        )
    manifest = DatasetManifest(title=title.strip(), glossary=glossary is not None)
    validate_data_files(files)
    target = root / name
    target.mkdir(parents=True, exist_ok=False)  # reserva exclusiva, inclusive entre processos
    try:
        raw = target / "raw"
        raw.mkdir()
        for source in files:
            shutil.copyfile(source, raw / source.name)
        if glossary is not None:
            shutil.copyfile(glossary, target / "glossary.toml")
        # Importação é uma operação do usuário; o agente não recebe acesso aos leitores.
        with duckdb.connect(str(target / "source.duckdb")) as con:
            con.execute("SET memory_limit='1GB'")
            con.execute("SET threads=2")
            loaded = load_files(con, find_data_files(raw))
            problems = check_glossary(
                load_glossary(target / "glossary.toml" if manifest.glossary else None),
                con,
                require_complete=False,
            )
            if problems:
                raise ValueError("Glossário incompatível: " + "; ".join(problems))
            if not loaded:
                raise ValueError("A importação não produziu tabelas.")
        content = (
            f"version = 1\ntitle = {json.dumps(manifest.title, ensure_ascii=False)}\n"
            f"glossary = {str(manifest.glossary).lower()}\n"
        )
        temporary = target / ".dataset.toml.tmp"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target / "dataset.toml")
    except BaseException:
        shutil.rmtree(target)
        raise
    return (target / "dataset.toml").resolve()


def dataset_identity(settings: Settings) -> str:
    """Identidade estável da base: painéis sobrevivem à atualização dos seus dados."""
    return hashlib.sha256(str(settings.duckdb_path.resolve()).encode()).hexdigest()


def cache_revision(settings: Settings) -> str:
    """Muda quando os dados ou a semântica mudam, mesmo com nomes/tipos iguais."""
    digest = hashlib.sha256(dataset_identity(settings).encode())
    for path in (settings.duckdb_path, settings.glossary_path):
        if path is not None:
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\x00")
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> None:
    """Comando olheiro-dataset: importar ou listar bases, sem usar o modelo."""
    parser = argparse.ArgumentParser(prog="olheiro-dataset", description="Bases CSV e Parquet.")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="cria uma base independente")
    importer.add_argument("source", type=Path, help="arquivo ou pasta de CSV/Parquet")
    importer.add_argument("--name", required=True, help="identificador único, ex.: vendas")
    importer.add_argument("--title", help="nome para exibir na interface")
    importer.add_argument("--glossary", type=Path, help="TOML opcional com descrições/regras")
    commands.add_parser("list", help="lista bases disponíveis")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.olheiro_demo_mode:
        sys.exit("Importação e troca de base estão disponíveis no modo pessoal.")
    if args.command == "list":
        for path, title in discover_datasets(settings.datasets_dir).items():
            print(f"{title}\t{path}")
        return
    try:
        path = import_dataset(
            find_data_files(args.source),
            settings.datasets_dir,
            args.name,
            args.title or args.name,
            args.glossary,
        )
    except (ValueError, OSError, duckdb.Error) as error:
        sys.exit(f"Não foi possível importar: {error}")
    print(f"Base pronta: {path}")
    print("Selecione a base na barra lateral do app ou configure OLHEIRO_DATASET com esse caminho.")


if __name__ == "__main__":
    main()
