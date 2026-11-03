"""Prévia sem persistência, usando a mesma carga estrita da importação definitiva."""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from olheiro.db import load_files, quote_identifier
from olheiro.import_options import ImportOptions
from olheiro.tools import QueryResult, interrupt_after, query_rows


@dataclass(frozen=True)
class FilePreview:
    name: str
    table: str
    row_count: int
    columns: list[tuple[str, str]]
    sample: QueryResult


def preview_files(files: list[Path], options: ImportOptions | None = None) -> list[FilePreview]:
    """Valida o arquivo inteiro; só a exibição é cortada em vinte linhas."""
    previews = []
    with duckdb.connect() as con:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET threads=2")
        with interrupt_after(con, 10):
            loaded = load_files(con, files, options)
        for table in loaded:
            source = f"raw.{quote_identifier(table.name)}"
            columns = [(row[0], row[1]) for row in con.execute(f"DESCRIBE {source}").fetchall()]
            previews.append(
                FilePreview(
                    table.source.name,
                    table.name,
                    table.row_count,
                    columns,
                    query_rows(con, f"SELECT * FROM {source}", max_rows=20),
                )
            )
    return previews
