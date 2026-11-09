"""Camada semântica: o glossário (semantic/glossary.toml) vira contexto para o agente.

O contexto junta três fontes: o glossário (significado e regras), o catálogo do banco (tipos,
sempre atualizado) e os valores reais das colunas marcadas com list_values.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import duckdb
from pydantic import BaseModel, Field, field_validator

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG, quote_identifier
from olheiro.tools import QUERY_TIMEOUT_SECONDS, interrupt_after


class ColumnDoc(BaseModel):
    description: str = Field(max_length=4000)
    unit: str = Field(default="", max_length=120)
    list_values: bool = False


class TableDoc(BaseModel):
    description: str = Field(max_length=4000)
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
    rules: list[Annotated[str, Field(max_length=4000)]] = Field(
        default_factory=list, max_length=100
    )


MAX_CONTEXT_CHARS = 12_000
MAX_CONTEXT_COLUMNS = 80


def read_semantics(glossary: Glossary, table: str = "", column: str = "", offset: int = 0) -> str:
    """Recupera descrições integrais ou duas regras por página, sem enviar o catálogo inteiro."""
    if offset < 0:
        raise ValueError("O início da página deve ser maior ou igual a zero.")
    if table:
        name = table.removeprefix("raw.")
        if name not in glossary.tables:
            return "Não há documentação adicional para esta tabela."
        doc = glossary.tables[name]
        if column:
            col = column_doc(glossary, name, column)
            return f"{col.description}\nUnidade: {col.unit or 'não informada'}"
        return doc.description
    rules = glossary.rules[offset : offset + 2]
    text = f"{len(glossary.rules)} regras; início {offset}.\n" + "\n".join(rules)
    if offset + 2 < len(glossary.rules):
        text += f"\nHá mais regras; use offset={offset + 2}."
    return text


def discover_tables(
    glossary: Glossary, con: duckdb.DuckDBPyConnection, search: str = "", offset: int = 0
) -> str:
    """Catálogo paginado pesquisável, inclusive por coluna/descrição; não lê valores."""
    if offset < 0:
        raise ValueError("O início da página deve ser maior ou igual a zero.")
    needle = search.casefold()
    entries = []
    sources = [
        (RAW_SCHEMA, columns_by_table(con, "schema_name", RAW_SCHEMA)),
        (WORKSPACE_CATALOG, columns_by_table(con, "database_name", WORKSPACE_CATALOG)),
    ]
    for schema, tables in sources:
        for table, columns in tables.items():
            doc = glossary.tables.get(table) if schema == RAW_SCHEMA else None
            description = doc.description if doc else ""
            searchable = " ".join([table, description, *(column for column, _ in columns)])
            if needle in searchable.casefold():
                entries.append(f"{schema}.{table} ({len(columns)} colunas): {description[:256]}")
    page = entries[offset : offset + 20]
    text = f"{len(entries)} tabelas encontradas; início {offset}.\n" + "\n".join(page)
    if offset + 20 < len(entries):
        text += f"\nHá mais tabelas; use offset={offset + 20}."
    return text[:MAX_CONTEXT_CHARS]


def describe_table(
    glossary: Glossary, con: duckdb.DuckDBPyConnection, table: str, offset: int = 0
) -> str:
    """Schema de uma tabela por página; mantém acesso às colunas omitidas do contexto inicial."""
    if offset < 0:
        raise ValueError("O início da página deve ser maior ou igual a zero.")
    schema = WORKSPACE_CATALOG if table.startswith("workspace.") else RAW_SCHEMA
    name = table.removeprefix(f"{schema}.")
    catalog = columns_by_table(
        con, "schema_name" if schema == RAW_SCHEMA else "database_name", schema
    )
    if name not in catalog:
        raise ValueError("Tabela inexistente; consulte discover_tables.")
    columns = catalog[name]
    lines = [f"{schema}.{name}: {len(columns)} colunas; início {offset}."]
    for column, kind in columns[offset : offset + 20]:
        doc = (
            column_doc(glossary, name, column)
            if schema == RAW_SCHEMA
            else ColumnDoc(description="")
        )
        lines.append(labeled(f"{column} {kind}", doc.description[:256]))
        if doc.unit:
            lines.append(f"  Unidade: {doc.unit}")
    lines.append("Descrições completas e regras estão em read_semantics.")
    if offset + 20 < len(columns):
        lines.append(f"Há mais colunas; use offset={offset + 20}.")
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]


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


@dataclass(frozen=True)
class SemanticContext:
    text: str
    truncated: bool


def build_context(glossary: Glossary, con: duckdb.DuckDBPyConnection) -> SemanticContext:
    """Texto que entra nas instruções: tabelas, colunas (tipo + significado), valores e regras."""
    lines = ["Tabelas de dados (schema raw):"]
    if not glossary.tables:
        lines.append(
            "Catálogo automático: nomes e tipos vêm do banco; significados, unidades, "
            "chaves e regras de negócio não foram informados. Explore antes de concluir."
        )
    used = 0
    omitted = False
    for table, columns in columns_by_table(con, "schema_name", RAW_SCHEMA).items():
        if used >= MAX_CONTEXT_COLUMNS or sum(map(len, lines)) > 10_000:
            omitted = True
            break
        doc = glossary.tables.get(table, TableDoc(description=""))
        omitted = omitted or len(doc.description) > 256
        lines.append("\n" + labeled(f"{RAW_SCHEMA}.{table}", doc.description[:256]))
        for column, data_type in columns:
            if used >= MAX_CONTEXT_COLUMNS or sum(map(len, lines)) > 10_000:
                omitted = True
                break
            used += 1
            documented = column_doc(glossary, table, column)
            omitted = omitted or len(documented.description) > 256
            line = labeled(f"  - {column} {data_type}", documented.description[:256])
            if documented.unit:
                line += f" Unidade: {documented.unit}."
            if documented.list_values:
                line += f" Valores: {distinct_values(con, table, column)}."
            lines.append(line)

    saved = columns_by_table(con, "database_name", WORKSPACE_CATALOG)
    lines.append(
        "\nTabelas salvas em workspace:" if saved else "\nNenhuma tabela salva em workspace."
    )
    for table, columns in saved.items():
        if used >= MAX_CONTEXT_COLUMNS:
            omitted = True
            break
        available = MAX_CONTEXT_COLUMNS - used
        omitted = omitted or len(columns) > available
        columns = columns[:available]
        used += len(columns)
        typed = ", ".join(f"{name} {data_type}" for name, data_type in columns)
        lines.append(f"  - {WORKSPACE_CATALOG}.{table}: {typed}")

    if glossary.rules:
        lines.append("\nRegras de negócio:")
        lines += [f"- {rule[:512]}" for rule in glossary.rules[:20]]
        omitted = (
            omitted or len(glossary.rules) > 20 or any(len(rule) > 512 for rule in glossary.rules)
        )
    text = "\n".join(lines)
    note = (
        "\nContexto resumido/truncado. Use discover_tables(search, offset) para localizar tabelas "
        "e describe_table(table, offset) para acessar as colunas restantes. "
        "Use read_semantics para regras/descrições completas. "
        "Não suponha que tabelas omitidas não existem."
    )
    truncated = omitted or len(text) > MAX_CONTEXT_CHARS
    return SemanticContext(
        text[: MAX_CONTEXT_CHARS - len(note)] + note if truncated else text, truncated
    )


def render_context(glossary: Glossary, con: duckdb.DuckDBPyConnection) -> str:
    return build_context(glossary, con).text
