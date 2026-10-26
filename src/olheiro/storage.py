"""Modelos Pydantic em arquivo: JSON inteiro (cache, dashboard) ou JSONL só de acréscimo (logs).

Escrita atômica ou por acréscimo, sempre com lock, para duas sessões do app não se atropelarem.
MemoryStore mantém estado por sessão na demo; persistência entre instâncias exige outro backend.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ValidationError


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
        self.path = path
        self.model = model
        self._lock = threading.Lock()

    def read(self) -> M:
        if not self.path.exists():
            return self.model()
        return self.model.model_validate_json(self.path.read_text(encoding="utf-8"))

    @contextmanager
    def update(self) -> Iterator[M]:
        """Lê, deixa o chamador alterar e grava, tudo sob o lock."""
        with self._lock:
            data = self.read()
            yield data
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(self.path)


class JsonLines[M: BaseModel]:
    """Um registro por linha, só acréscimo: gravar é barato e uma linha ruim não perde as outras."""

    def __init__(self, path: Path, model: type[M]) -> None:
        self.path = path
        self.model = model
        self._lock = threading.Lock()

    def append(self, record: M) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(record.model_dump_json() + "\n")

    def read(self) -> list[M]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(self.model.model_validate_json(line))
            except ValidationError:
                continue  # linha cortada (ex.: processo morto no meio da escrita): ignora
        return records
