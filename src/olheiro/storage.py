"""Um modelo Pydantic guardado num arquivo JSON (cache de respostas, dashboard).

Escrita atômica (grava num temporário e troca) e lock, para duas sessões do app não se
atropelarem. Para um deploy com vários usuários, é este módulo que muda (ex.: banco de dados).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel


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
