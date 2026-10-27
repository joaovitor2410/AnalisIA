"""Camada semântica: o glossário (semantic/glossary.toml) vira contexto para o agente.

O contexto junta três fontes: o glossário (significado e regras), o catálogo do banco (tipos,
sempre atualizado) e os valores reais das colunas marcadas com list_values.
"""

import tomllib
from pathlib import Path

import duckdb
from pydantic import BaseModel, field_validator

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG, quote_identifier
from olheiro.tools import QUERY_TIMEOUT_SECONDS, interrupt_after


class ColumnDoc(BaseModel):
    description: str
    list_values: bool = False


class TableDoc(BaseModel):
    description: str
    columns: dict[str, ColumnDoc] = {}

    @field_validator("columns", mode="before")
    @classmethod
    def _plain_text_is_description(cls, columns: dict[str, object]) -> dict[str, object]:
        """No TOML, `coluna = "texto"` é atalho para `coluna = { description = "texto" }`."""
        return {
            name: {"description": doc} if isinstance(doc, str) else doc
            for name, doc in columns.items()
        }


class Glossary(BaseModel):
    tables: dict[str, TableDoc] = {}
    rules: list[str] = []


def load_glossary(path: Path | None) -> Glossary:
    """Sem arquivo configurado, o catálogo é suficiente para começar a explorar."""
    if path is None:
        return Glossary()
    with path.open("rb") as file:
        return Glossary.model_validate(tomllib.load(file))


def columns_by_table(
    con: duckdb.DuckDBPyConnection, level: str, name: str
) -> dict[str, list[tuple[str, str]]]:
    """{tabela: [(coluna, tipo), ...]} de um schema (level="schema_name") ou de um banco
    anexado (level="database_name"), na ordem das colunas."""
    if level not in {"schema_name", "database_name"}:
        raise ValueError("Filtro de catálogo inválido.")
    rows = con.execute(
        f"""
        SELECT table_name, column_name, data_type FROM duckdb_columns()
        WHERE {level} = ? ORDER BY table_name, column_index
        """,
        [name],
    ).fetchall()
    tables: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in rows:
        tables.setdefault(table, []).append((column, data_type))
    return tables


def check_glossary(
    glossary: Glossary, con: duckdb.DuckDBPyConnection, *, require_complete: bool = True
) -> list[str]:
    """Divergências entre glossário e banco, nos dois sentidos. Lista vazia = em sincronia."""
    catalog = columns_by_table(con, "schema_name", RAW_SCHEMA)
    problems = [f"tabela no glossário, não no banco: {t}" for t in glossary.tables.keys() - catalog]
    for table, columns in catalog.items():
        documented = glossary.tables[table].columns if table in glossary.tables else {}
        names = {name for name, _ in columns}
        problems += (
            [f"coluna sem descrição: {table}.{c}" for c in sorted(names - documented.keys())]
            if require_complete
            else []
        )
        problems += [f"coluna inexistente: {table}.{c}" for c in sorted(documented.keys() - names)]
    return problems


def distinct_values(con: duckdb.DuckDBPyConnection, table: str, column: str) -> str:
    # Mesmo nomes vindos do catálogo precisam de escape: uma coluna pode conter aspas.
    col, source = quote_identifier(column), f"{RAW_SCHEMA}.{quote_identifier(table)}"
    with interrupt_after(con, QUERY_TIMEOUT_SECONDS):
        rows = con.execute(
            f"SELECT DISTINCT CAST({col} AS VARCHAR) AS value FROM {source} "
            f"WHERE {col} IS NOT NULL ORDER BY value LIMIT 21"
        ).fetchall()
    values = ", ".join(value[:128] for (value,) in rows[:20])
    truncated = len(rows) > 20 or any(len(value) > 128 for (value,) in rows) or len(values) > 2048
    note = " [Amostra/truncamento; confirme os valores com profile_column]" if truncated else ""
    return values[:2048] + note


def column_doc(glossary: Glossary, table: str, column: str) -> ColumnDoc:
    """Documentação da coluna; vazia se o glossário não a descrever."""
    table_doc = glossary.tables.get(table)
    if table_doc is None:
        return ColumnDoc(description="")
    return table_doc.columns.get(column, ColumnDoc(description=""))


def labeled(label: str, text: str) -> str:
    return f"{label}: {text}" if text else label


def render_context(glossary: Glossary, con: duckdb.DuckDBPyConnection) -> str:
    """Texto que entra nas instruções: tabelas, colunas (tipo + significado), valores e regras."""
    lines = ["Tabelas de dados (schema raw):"]
    if not glossary.tables:
        lines.append(
            "Catálogo automático: nomes e tipos vêm do banco; significados, unidades, "
            "chaves e regras de negócio não foram informados. Explore antes de concluir."
        )
    for table, columns in columns_by_table(con, "schema_name", RAW_SCHEMA).items():
        doc = glossary.tables.get(table, TableDoc(description=""))
        lines.append("\n" + labeled(f"{RAW_SCHEMA}.{table}", doc.description))
        for column, data_type in columns:
            documented = column_doc(glossary, table, column)
            line = labeled(f"  - {column} {data_type}", documented.description)
            if documented.list_values:
                line += f" Valores: {distinct_values(con, table, column)}."
            lines.append(line)

    saved = columns_by_table(con, "database_name", WORKSPACE_CATALOG)
    lines.append(
        "\nTabelas salvas em workspace:" if saved else "\nNenhuma tabela salva em workspace."
    )
    for table, columns in saved.items():
        typed = ", ".join(f"{name} {data_type}" for name, data_type in columns)
        lines.append(f"  - {WORKSPACE_CATALOG}.{table}: {typed}")

    if glossary.rules:
        lines.append("\nRegras de negócio:")
        lines += [f"- {rule}" for rule in glossary.rules]
    return "\n".join(lines)
