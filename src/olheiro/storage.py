"""Modelos Pydantic em arquivo: JSON inteiro (cache, dashboard) ou JSONL só de acréscimo (logs).

Locks de arquivo coordenam instâncias e processos no mesmo filesystem local (macOS/Linux).
MemoryStore mantém estado por sessão na demo; arquivos não substituem um backend distribuído.
"""

import fcntl
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ValidationError

DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 3


@contextmanager
def file_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
    """O sidecar permanece estável mesmo quando o arquivo de dados é trocado por rename."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f".{path.name}.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_text(path: Path, content: str) -> None:
    """Publica um arquivo completo; falhas anteriores ao replace preservam a versão ativa."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class MemoryStore[M: BaseModel]:
    """Estado de uma sessão: cópias profundas impedem alterações fora da transação."""

    def __init__(self, model: type[M]) -> None:
        self._data = model()
        self._lock = threading.Lock()

    def read(self) -> M:
        return self._data.model_copy(deep=True)

    @contextmanager
    def update(self) -> Iterator[M]:
        with self._lock:
            data = self.read()
            yield data
            self._data = data.model_copy(deep=True)


class JsonFile[M: BaseModel]:
    def __init__(self, path: Path, model: type[M]) -> None:
        self.path = path.resolve()
        self.model = model
        self._lock = threading.Lock()

    def read(self) -> M:
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self.model()
        return self.model.model_validate_json(content)

    @contextmanager
    def update(self) -> Iterator[M]:
        """Lê, deixa o chamador alterar e grava, tudo sob o lock."""
        with self._lock, file_lock(self.path):
            data = self.read()
            yield data
            atomic_text(self.path, data.model_dump_json(indent=2))


class JsonLinesFile:
    """JSONL com rotação por bytes e leitura dos arquivos retidos, sob um único lock."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = DEFAULT_LOG_MAX_BYTES,
        backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
    ) -> None:
        if max_bytes < 1 or backup_count < 1:
            raise ValueError("O tamanho e a quantidade de arquivos retidos precisam ser positivos.")
        self.path = path.resolve()
        self.max_bytes = max_bytes
        self.backup_count = backup_count

    def archives(self) -> list[Path]:
        """Mais antigo primeiro; ignora sidecars e arquivos sem sufixo numérico."""
        if not self.path.parent.exists():
            return []
        prefix = self.path.name + "."
        return sorted(
            (
                path
                for path in self.path.parent.iterdir()
                if path.name.startswith(prefix) and path.name[len(prefix) :].isdigit()
            ),
            key=lambda path: int(path.name[len(prefix) :]),
            reverse=True,
        )

    def rotate(self) -> None:
        """Chamado com lock exclusivo, antes de um registro ultrapassar o tamanho máximo."""
        prefix = self.path.name + "."
        for archive in self.archives():
            index = int(archive.name[len(prefix) :])
            if index >= self.backup_count:
                archive.unlink()
            else:
                archive.replace(self.path.with_name(f"{prefix}{index + 1}"))
        self.path.replace(self.path.with_name(f"{prefix}1"))

    def append(self, lines: list[str]) -> int:
        """Não divide registros; os maiores que o teto são omitidos com aviso sem conteúdo."""
        written = 0
        with file_lock(self.path):
            for line in lines:
                payload = (line.rstrip("\n") + "\n").encode("utf-8")
                if len(payload) > self.max_bytes:
                    logging.getLogger(__name__).warning(
                        "Registro de observabilidade omitido: %d bytes excedem o teto de %d.",
                        len(payload),
                        self.max_bytes,
                    )
                    continue
                size = self.path.stat().st_size if self.path.exists() else 0
                separator = b""
                if size:
                    with self.path.open("rb") as existing:
                        existing.seek(-1, os.SEEK_END)
                        separator = b"\n" if existing.read(1) != b"\n" else b""
                if size and size + len(separator) + len(payload) > self.max_bytes:
                    self.rotate()
                    separator = b""
                with self.path.open("ab") as file:
                    file.write(separator + payload)
                    file.flush()
                    os.fsync(file.fileno())
                written += 1
        return written

    def read(self) -> list[str]:
        if not self.path.exists() and not self.archives():
            return []
        lines = []
        with file_lock(self.path, exclusive=False):
            for path in [*self.archives(), self.path]:
                if not path.exists():
                    continue
                with path.open("rb") as file:
                    for line in file:
                        try:
                            lines.append(line.decode("utf-8"))
                        except UnicodeDecodeError:
                            continue
        return lines


class JsonLines[M: BaseModel]:
    """Um registro por linha, só acréscimo: gravar é barato e uma linha ruim não perde as outras."""

    def __init__(
        self,
        path: Path,
        model: type[M],
        *,
        max_bytes: int = DEFAULT_LOG_MAX_BYTES,
        backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
    ) -> None:
        self.path = path.resolve()
        self.model = model
        self.file = JsonLinesFile(path, max_bytes=max_bytes, backup_count=backup_count)

    def append(self, record: M) -> None:
        self.file.append([record.model_dump_json()])

    def read(self) -> list[M]:
        records = []
        for line in self.file.read():
            try:
                records.append(self.model.model_validate_json(line))
            except ValidationError:
                continue  # linha cortada (ex.: processo morto no meio da escrita): ignora
        return records
