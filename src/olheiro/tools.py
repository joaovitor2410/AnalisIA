"""Ferramentas que o agente pode chamar.

Cada ferramenta devolve um dict com a chave "result" (sucesso) ou "error" (falha).
Erros não viram exceção: voltam como texto para o modelo ler e corrigir a consulta.
"""

import duckdb

from olheiro.db import RAW_SCHEMA

# Mais que isso enche o contexto do modelo sem ajudar a responder; ele deve agregar ou usar LIMIT.
MAX_ROWS = 50


def format_cell(value: object) -> str:
    """Converte um valor do banco em texto seguro para uma célula de tabela markdown."""
    if value is None:
        return "NULL"
    return str(value).replace("|", "\\|").replace("\n", " ")


def format_markdown_table(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    """Monta uma tabela markdown: formato compacto e fácil de ler para o modelo e para nós."""
    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "---|" * len(columns)
    body = ["| " + " | ".join(format_cell(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def run_sql(con: duckdb.DuckDBPyConnection, query: str, max_rows: int = MAX_ROWS) -> dict[str, str]:
    """Executa uma consulta e devolve até `max_rows` linhas em tabela markdown.

    A segurança, por enquanto, vem só da conexão read-only (validação de SQL na Fase 3).
    """
    try:
        con.execute(query)
        if con.description is None:
            return {"result": "Comando executado, sem linhas de resultado."}
        columns = [column[0] for column in con.description]
        rows = con.fetchmany(max_rows + 1)
    except duckdb.Error as error:
        return {"error": f"{type(error).__name__}: {error}"}

    if not rows:
        return {"result": "A consulta não retornou linhas.\n" + format_markdown_table(columns, [])}
    table = format_markdown_table(columns, rows[:max_rows])
    if len(rows) > max_rows:
        table += f"\n(resultado cortado em {max_rows} linhas; use agregação ou LIMIT)"
    return {"result": table}


def describe_schema(con: duckdb.DuckDBPyConnection) -> str:
    """Lista as tabelas do schema raw com suas colunas e tipos, uma tabela por linha.

    Ex.: 'raw.teams: team VARCHAR, founded BIGINT'
    """
    rows = con.execute(
        """
        SELECT table_name, string_agg(column_name || ' ' || data_type, ', ' ORDER BY column_index)
        FROM duckdb_columns()
        WHERE schema_name = ?
        GROUP BY table_name
        ORDER BY table_name
        """,
        [RAW_SCHEMA],
    ).fetchall()
    return "\n".join(f"{RAW_SCHEMA}.{table}: {columns}" for table, columns in rows)
