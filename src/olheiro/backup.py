"""Backup frio local, privado e verificável; restauração sempre para um destino novo."""

import argparse
import hashlib
import json
import shutil
from contextlib import ExitStack
from pathlib import Path

import duckdb

from olheiro.storage import file_lock

MANIFEST = ".analisia-backup.json"


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def state_files(root: Path) -> list[Path]:
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("O estado não deve conter links simbólicos.")
    files = [
        path
        for path in paths
        if path.is_file() and not path.name.endswith((".lock", ".tmp")) and path.name != ".DS_Store"
    ]
    if any(path.suffix == ".wal" for path in files):
        raise ValueError("Há WAL pendente; encerre app, CLI e MCP antes do backup.")
    return sorted(files)


def create_backup(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir() or destination.is_relative_to(source):
        raise ValueError("Escolha um estado existente e um backup fora dessa pasta.")
    files = state_files(source)
    if not files or (source / MANIFEST).exists():
        raise ValueError("Estado vazio ou origem já é um backup.")
    with ExitStack() as stack:
        # Conexões de leitura recusam escritores de outros processos e seguram os bancos
        # durante a cópia. JSONs ainda exigem todos os aplicativos encerrados.
        try:
            for path in files:
                if path.suffix == ".duckdb":
                    stack.enter_context(duckdb.connect(str(path), read_only=True))
                if path.suffix in {".json", ".jsonl"}:
                    stack.enter_context(file_lock(path))
        except duckdb.Error as error:
            raise ValueError("Banco em uso; encerre app, CLI e MCP antes do backup.") from error
        destination.mkdir(parents=True, mode=0o700, exist_ok=False)
        try:
            checksums = {}
            for path in files:
                relative = path.relative_to(source)
                target = destination / relative
                target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                before = digest(path)
                shutil.copyfile(path, target)
                target.chmod(0o600)
                if before != digest(target) or before != digest(path):
                    raise ValueError("O estado mudou durante a cópia; encerre os aplicativos.")
                checksums[str(relative)] = before
            if files != state_files(source):
                raise ValueError("A lista de arquivos mudou durante o backup.")
            manifest = destination / MANIFEST
            manifest.write_text(json.dumps({"version": 1, "files": checksums}, indent=2))
            manifest.chmod(0o600)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def verify_backup(source: Path) -> dict[str, str]:
    source = source.resolve()
    data = json.loads((source / MANIFEST).read_text())
    if data.get("version") != 1 or not isinstance(data.get("files"), dict) or not data["files"]:
        raise ValueError("Manifesto de backup inválido.")
    for name, expected in data["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name == MANIFEST:
            raise ValueError("Caminho inválido no manifesto.")
        path = source / relative
        if not path.resolve().is_relative_to(source) or path.is_symlink():
            raise ValueError("Link ou caminho externo ao backup.")
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Arquivo ausente ou corrompido: {name}")
    return data["files"]


def restore_backup(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    files = verify_backup(source)
    if destination.is_relative_to(source):
        raise ValueError("Restaure fora da pasta do backup.")
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        for name, expected in files.items():
            target = destination / name
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copyfile(source / name, target)
            target.chmod(0o600)
            if digest(target) != expected:
                raise ValueError("O backup mudou durante a restauração.")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["create", "restore"]:
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path)
    commands.add_parser("verify").add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            print(create_backup(args.source, args.destination))
        elif args.command == "restore":
            print(restore_backup(args.source, args.destination))
        else:
            print(f"Backup válido: {len(verify_backup(args.source))} arquivos.")
    except (OSError, ValueError) as error:
        raise SystemExit(f"Operação recusada: {error}") from error
