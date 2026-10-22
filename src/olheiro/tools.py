"""Ferramentas que o agente pode chamar, e a execução de SQL por trás delas.

As ferramentas (`run_sql`, `profile_column`) devolvem um dict com a chave "result" (sucesso) ou
"error" (falha). Erros não viram exceção: voltam como texto para o modelo ler e corrigir a consulta.
`query_rows` é a execução crua, usada também para reexecutar o SQL de evidência.
"""

from dataclasses import dataclass

import duckdb

from olheiro.db import RAW_SCHEMA

# Mais que isso enche o contexto do modelo sem ajudar a responder; ele deve agregar ou usar LIMIT.
MAX_ROWS = 50


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


def query_rows(con: duckdb.DuckDBPyConnection, query: str, max_rows: int = MAX_ROWS) -> QueryResult:
    """Executa uma consulta e devolve até `max_rows` linhas. Levanta duckdb.Error se falhar."""
    con.execute(query)
    if con.description is None:
        return QueryResult(columns=[], rows=[])
    columns = [column[0] for column in con.description]
    rows = con.fetchmany(max_rows + 1)
    return QueryResult(columns, rows[:max_rows], truncated=len(rows) > max_rows)


def run_sql(con: duckdb.DuckDBPyConnection, query: str, max_rows: int = MAX_ROWS) -> dict[str, str]:
    """Ferramenta: executa uma consulta e devolve o resultado em tabela markdown.

    A segurança, por enquanto, vem só da conexão read-only (validação de SQL na Fase 3).
    """
    try:
        result = query_rows(con, query, max_rows)
    except duckdb.Error as error:
        return {"error": f"{type(error).__name__}: {error}"}

    if not result.columns:
        return {"result": "Comando executado, sem linhas de resultado."}
    if not result.rows:
        return {"result": "A consulta não retornou linhas.\n" + result.to_markdown()}
    return {"result": result.to_markdown()}


def profile_column(con: duckdb.DuckDBPyConnection, table: str, column: str) -> dict[str, str]:
    """Ferramenta: tipo, nulos, distintos, mínimo/máximo e valores mais frequentes de uma coluna.

    Serve para o modelo conhecer os valores reais antes de filtrar (ex.: como um time está escrito).
    """
    table = table.removeprefix(f"{RAW_SCHEMA}.")
    found = con.execute(
        """
        SELECT data_type FROM duckdb_columns()
        WHERE schema_name = ? AND table_name = ? AND column_name = ?
        """,
        [RAW_SCHEMA, table, column],
    ).fetchone()
    if found is None:
        return {"error": f"Coluna '{column}' não existe em {RAW_SCHEMA}.{table}. Confira o schema."}

    # Seguro interpolar: tabela e coluna acabaram de ser confirmadas no catálogo do banco.
    source, col = f'{RAW_SCHEMA}."{table}"', f'"{column}"'
    stats = query_rows(
        con,
        f"""
        SELECT count(*) AS total_rows, count({col}) AS non_null,
               count(DISTINCT {col}) AS distinct_values, min({col}) AS min, max({col}) AS max
        FROM {source}
        """,
    )
    top = query_rows(
        con,
        f"SELECT {col} AS value, count(*) AS rows FROM {source} "
        "GROUP BY ALL ORDER BY rows DESC, value",
    )
    return {
        "result": f"Tipo: {found[0]}\n{stats.to_markdown()}\n\n"
        f"Valores por frequência:\n{top.to_markdown()}"
    }


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
