"""Qualidade verificável com SQL de leitura; sugestões não substituem regras de negócio."""

from dataclasses import dataclass
from typing import cast

import duckdb

from olheiro.db import quote_identifier
from olheiro.semantic import columns_by_table
from olheiro.tools import QueryResult, query_rows


@dataclass(frozen=True)
class ColumnQuality:
    column: str
    data_type: str
    nulls: int
    distinct: int
    candidate_key: bool


@dataclass(frozen=True)
class QualityReport:
    total_rows: int
    duplicate_rows: int
    columns: list[ColumnQuality]
    sql: list[str]


def table_quality(con: duckdb.DuckDBPyConnection, table: str) -> QualityReport:
    catalog = columns_by_table(con, "schema_name", "raw")
    if table not in catalog:
        raise ValueError("Tabela inexistente no schema raw.")
    source = f"raw.{quote_identifier(table)}"
    expressions = ["count(*) AS total_rows"]
    for index, (column, _) in enumerate(catalog[table]):
        col = quote_identifier(column)
        expressions.extend(
            [
                f"count({col}) AS non_null_{index}",
                f"count(DISTINCT {col}) AS distinct_{index}",
            ]
        )
    stats_sql = f"SELECT {', '.join(expressions)} FROM {source}"
    stats = cast(tuple[int, ...], query_rows(con, stats_sql).rows[0])
    total = stats[0]
    duplicates_sql = f"SELECT count(*) AS unique_rows FROM (SELECT DISTINCT * FROM {source})"
    unique = cast(int, query_rows(con, duplicates_sql).rows[0][0])
    columns = [
        ColumnQuality(
            column,
            kind,
            total - stats[1 + index * 2],
            stats[2 + index * 2],
            total > 0 and stats[1 + index * 2] == total and stats[2 + index * 2] == total,
        )
        for index, (column, kind) in enumerate(catalog[table])
    ]
    return QualityReport(total, total - unique, columns, [stats_sql, duplicates_sql])


@dataclass(frozen=True)
class RelationshipReport:
    evidence: QueryResult
    sql: str
    compatible: bool
    cardinality: str


def check_relationship(
    con: duckdb.DuckDBPyConnection,
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
) -> RelationshipReport:
    """Mede cobertura e unicidade para um JOIN sugerido pelo usuário, sem multiplicar medidas."""
    catalog = columns_by_table(con, "schema_name", "raw")
    left_type = dict(catalog.get(left_table, [])).get(left_column)
    right_type = dict(catalog.get(right_table, [])).get(right_column)
    if left_type is None or right_type is None:
        raise ValueError("Selecione tabelas e colunas existentes em raw.")
    if left_type != right_type:
        raise ValueError("Os tipos das colunas diferem; ajuste e confira antes de sugerir o JOIN.")
    left, right = f"raw.{quote_identifier(left_table)}", f"raw.{quote_identifier(right_table)}"
    lc, rc = quote_identifier(left_column), quote_identifier(right_column)
    sql = f"""WITH l AS (
        SELECT count(*) AS left_rows, count({lc}) AS left_non_null,
               count(DISTINCT {lc}) AS left_distinct FROM {left}
    ), r AS (
        SELECT count(*) AS right_rows, count({rc}) AS right_non_null,
               count(DISTINCT {rc}) AS right_distinct FROM {right}
    ), coverage AS (
        SELECT count(*) AS matched_rows FROM {left} a WHERE a.{lc} IS NOT NULL
        AND EXISTS (SELECT 1 FROM {right} b WHERE a.{lc} = b.{rc})
    ) SELECT l.*, r.*, matched_rows, left_non_null - matched_rows AS orphan_rows
      FROM l CROSS JOIN r CROSS JOIN coverage"""
    evidence = query_rows(con, sql)
    lr, ln, ld, rr, rn, rd, matched, orphans = cast(tuple[int, ...], evidence.rows[0])
    compatible = rr > 0 and rr == rn == rd and ln > 0 and orphans == 0
    cardinality = "um para um" if lr == ln == ld else "muitos para um"
    return RelationshipReport(
        evidence, sql, compatible, cardinality if compatible else "não validada"
    )
