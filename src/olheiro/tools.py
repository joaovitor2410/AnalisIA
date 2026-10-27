"""Ferramentas que o agente pode chamar, e a execução de SQL por trás delas.

As ferramentas (`run_sql`, `profile_column`, `save_result`) devolvem um dict com a chave "result"
(sucesso) ou "error" (falha). Erros não viram exceção: voltam como texto para o modelo corrigir.
`query_rows` é a execução crua (com prazo), usada também para reexecutar o SQL de evidência.
"""

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import duckdb

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG, quote_identifier, scalar
from olheiro.sql_guard import UnsafeQueryError, check_query

# Mais que isso enche o contexto do modelo sem ajudar a responder; ele deve agregar ou usar LIMIT.
MAX_ROWS = 50
# O DuckDB não tem timeout de consulta: a aplicação interrompe (recomendação da doc de segurança).
QUERY_TIMEOUT_SECONDS = 10
# Nome de tabela salva: snake_case simples, então pode ir direto no SQL sem risco de injeção.
TABLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")


@dataclass(frozen=True)
class QueryResult:
    """Resultado de uma consulta: colunas, até `max_rows` linhas e se foi cortado."""

    columns: list[str]
    rows: list[tuple[object, ...]]
    truncated: bool = False

    def column_values(self, column: str) -> list[object]:
        """Valores de uma coluna, na ordem das linhas."""
        index = self.columns.index(column)
        return [row[index] for row in self.rows]

    def to_markdown(self) -> str:
        table = format_markdown_table(self.columns, self.rows)
        if self.truncated:
            table += f"\n(resultado cortado em {len(self.rows)} linhas; use agregação ou LIMIT)"
        return table


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


@contextmanager
def interrupt_after(con: duckdb.DuckDBPyConnection, seconds: float) -> Iterator[None]:
    """Interrompe o que estiver rodando na conexão se passar de `seconds`."""
    timer = threading.Timer(seconds, con.interrupt)
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def query_rows(
    con: duckdb.DuckDBPyConnection,
    query: str,
    max_rows: int = MAX_ROWS,
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> QueryResult:
    """Executa uma consulta e devolve até `max_rows` linhas.

    Levanta duckdb.Error se falhar, ou duckdb.InterruptException se passar de `timeout`.
    """
    with interrupt_after(con, timeout):
        con.execute(query)
        if con.description is None:
            return QueryResult(columns=[], rows=[])
        columns = [column[0] for column in con.description]
        rows = con.fetchmany(max_rows + 1)
    return QueryResult(columns, rows[:max_rows], truncated=len(rows) > max_rows)


def describe_db_error(error: duckdb.Error) -> str:
    if isinstance(error, duckdb.InterruptException):
        return f"A consulta passou de {QUERY_TIMEOUT_SECONDS} s e foi interrompida: simplifique."
    return f"{type(error).__name__}: {error}"


def run_sql(con: duckdb.DuckDBPyConnection, query: str, max_rows: int = MAX_ROWS) -> dict[str, str]:
    """Ferramenta: valida e executa uma consulta, devolvendo o resultado em tabela markdown."""
    try:
        check_query(query)
        result = query_rows(con, query, max_rows)
    except UnsafeQueryError as error:
        return {"error": f"Consulta recusada: {error}"}
    except duckdb.Error as error:
        return {"error": describe_db_error(error)}

    if not result.columns:
        return {"result": "Comando executado, sem linhas de resultado."}
    if not result.rows:
        return {"result": "A consulta não retornou linhas.\n" + result.to_markdown()}
    return {"result": result.to_markdown()}


@dataclass(frozen=True)
class ColumnProfile:
    """Perfil de uma coluna: estatísticas gerais e valores por frequência."""

    data_type: str
    stats: QueryResult
    top_values: QueryResult


def column_profile(con: duckdb.DuckDBPyConnection, table: str, column: str) -> ColumnProfile:
    """Perfil de uma coluna de raw. Levanta ValueError se a tabela ou a coluna não existir."""
    table = table.removeprefix(f"{RAW_SCHEMA}.")
    found = con.execute(
        """
        SELECT data_type FROM duckdb_columns()
        WHERE schema_name = ? AND table_name = ? AND column_name = ?
        """,
        [RAW_SCHEMA, table, column],
    ).fetchone()
    if found is None:
        raise ValueError(f"Coluna '{column}' não existe em {RAW_SCHEMA}.{table}. Confira o schema.")

    source, col = f"{RAW_SCHEMA}.{quote_identifier(table)}", quote_identifier(column)
    stats = query_rows(
        con,
        f"""
        SELECT count(*) AS total_rows, count({col}) AS non_null,
               count(DISTINCT {col}) AS distinct_values, min({col}) AS min, max({col}) AS max
        FROM {source}
        """,
    )
    top_values = query_rows(
        con,
        f"SELECT {col} AS value, count(*) AS rows FROM {source} "
        "GROUP BY ALL ORDER BY rows DESC, value",
    )
    return ColumnProfile(found[0], stats, top_values)


def profile_column(con: duckdb.DuckDBPyConnection, table: str, column: str) -> dict[str, str]:
    """Ferramenta: o perfil da coluna em texto, para o modelo conhecer os valores reais."""
    try:
        profile = column_profile(con, table, column)
    except ValueError as error:
        return {"error": str(error)}
    return {
        "result": f"Tipo: {profile.data_type}\n{profile.stats.to_markdown()}\n\n"
        f"Valores por frequência:\n{profile.top_values.to_markdown()}"
    }


def check_save_request(con: duckdb.DuckDBPyConnection, name: str, query: str) -> str:
    """Valida um pedido de save_result antes de pedir aprovação ao usuário.

    Devolve a consulta normalizada (gerada pelo sqlglot, sem comentários nem ';' extras).
    """
    if not TABLE_NAME.fullmatch(name):
        raise UnsafeQueryError(f"Nome '{name}' inválido: use snake_case (ex.: campeoes_2019).")
    exists = scalar(
        con,
        "SELECT count(*) FROM duckdb_tables() WHERE database_name = ? AND table_name = ?",
        [WORKSPACE_CATALOG, name],
    )
    if exists:
        raise UnsafeQueryError(f"{WORKSPACE_CATALOG}.{name} já existe: escolha outro nome.")
    return check_query(query).sql(dialect="duckdb")


def save_result(con: duckdb.DuckDBPyConnection, name: str, query: str) -> dict[str, str]:
    """Ferramenta (só roda depois da aprovação): grava o resultado em workspace.<name>."""
    try:
        safe_query = check_save_request(con, name, query)
        with interrupt_after(con, QUERY_TIMEOUT_SECONDS):
            con.execute(f"CREATE TABLE {WORKSPACE_CATALOG}.{name} AS {safe_query}")
        count = scalar(con, f"SELECT count(*) FROM {WORKSPACE_CATALOG}.{name}")
    except UnsafeQueryError as error:
        return {"error": f"Pedido recusado: {error}"}
    except duckdb.Error as error:
        return {"error": describe_db_error(error)}
    return {"result": f"Tabela {WORKSPACE_CATALOG}.{name} criada com {count} linhas."}


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
