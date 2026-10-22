"""Validação do SQL do agente antes de executar (camada 1 da defesa; a camada 2 é o motor).

Regras:
- exatamente uma consulta de leitura (SELECT, UNION, WITH ...);
- toda tabela citada é um nome, não uma função ou arquivo (nada de read_csv('x'), FROM 'x');
- e está em raw ou workspace, ou é um CTE da própria consulta.
As mensagens de erro são escritas para o modelo ler e corrigir a consulta.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG

ALLOWED_SCHEMAS = frozenset({RAW_SCHEMA, WORKSPACE_CATALOG})


class UnsafeQueryError(ValueError):
    """SQL recusado pelo validador."""


def check_query(sql: str) -> exp.Query:
    """Devolve a consulta já analisada se for segura; senão levanta UnsafeQueryError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as error:
        # Usa os campos do erro: o texto padrão traz códigos de cor do terminal.
        first = error.errors[0] if error.errors else {}
        where = f" (linha {first.get('line')}, coluna {first.get('col')})" if first else ""
        detail = first.get("description", "sintaxe não reconhecida")
        raise UnsafeQueryError(f"SQL inválido: {detail}{where}.") from error
    if len(statements) != 1:
        raise UnsafeQueryError("Envie exatamente uma consulta por vez.")
    query = statements[0]
    if not isinstance(query, exp.Query):
        raise UnsafeQueryError(
            f"Só consultas de leitura (SELECT) são permitidas; recebido: {query.key.upper()}."
        )
    cte_names = {cte.alias_or_name for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        check_table(table, cte_names)
    return query


def check_table(table: exp.Table, cte_names: set[str]) -> None:
    if not isinstance(table.this, exp.Identifier):
        raise UnsafeQueryError("Funções de tabela (ex.: read_csv) não são permitidas.")
    if table.catalog:
        raise UnsafeQueryError(f"Use schema.tabela, sem catálogo: '{table.sql()}'.")
    if table.db in ALLOWED_SCHEMAS or (not table.db and table.name in cte_names):
        return
    raise UnsafeQueryError(
        f"Tabela '{table.sql()}' não permitida: use tabelas de raw ou workspace (ex.: raw.teams)."
    )
