"""Testes das ferramentas: conexão comum e a conexão blindada do agente (bancos temporários)."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from olheiro.db import connect, connect_agent
from olheiro.tools import (
    describe_schema,
    format_markdown_table,
    profile_column,
    query_rows,
    run_sql,
    save_result,
)

HEAVY_QUERY = (
    "SELECT count(*) FROM range(100000) a, range(100000) b WHERE (a.range * b.range) % 7 = 3"
)


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    db_path = tmp_path / "test.duckdb"
    with connect(db_path) as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute("CREATE TABLE raw.jogos AS SELECT range AS id, 'A' AS time FROM range(60)")
    with connect(db_path, read_only=True) as read_only_con:
        yield read_only_con


def test_format_markdown_table_escapes_pipes_and_nulls() -> None:
    table = format_markdown_table(["a", "b"], [("x|y", None)])
    assert table == "| a | b |\n|---|---|\n| x\\|y | NULL |"


def test_run_sql_returns_markdown_table(con: duckdb.DuckDBPyConnection) -> None:
    output = run_sql(con, "SELECT count(*) AS total FROM raw.jogos")
    assert output == {"result": "| total |\n|---|\n| 60 |"}


def test_run_sql_truncates_long_results(con: duckdb.DuckDBPyConnection) -> None:
    output = run_sql(con, "SELECT id FROM raw.jogos", max_rows=5)
    lines = output["result"].splitlines()
    assert len(lines) == 2 + 5 + 1  # cabeçalho + separador + 5 linhas + aviso
    assert "cortado em 5 linhas" in lines[-1]


def test_run_sql_returns_error_instead_of_raising(con: duckdb.DuckDBPyConnection) -> None:
    output = run_sql(con, "SELECT coluna_que_nao_existe FROM raw.jogos")
    assert "error" in output
    assert "coluna_que_nao_existe" in output["error"]


def test_run_sql_refuses_writes_before_touching_the_database(
    con: duckdb.DuckDBPyConnection,
) -> None:
    output = run_sql(con, "DELETE FROM raw.jogos")
    assert output["error"].startswith("Consulta recusada")
    assert run_sql(con, "SELECT count(*) AS total FROM raw.jogos")["result"].endswith("| 60 |")


def test_describe_schema_lists_columns_and_types(con: duckdb.DuckDBPyConnection) -> None:
    assert describe_schema(con) == "raw.jogos: id BIGINT, time VARCHAR"


def test_query_rows_returns_real_values_and_truncation(con: duckdb.DuckDBPyConnection) -> None:
    result = query_rows(con, "SELECT id, time FROM raw.jogos ORDER BY id", max_rows=3)
    assert result.columns == ["id", "time"]
    assert result.column_values("id") == [0, 1, 2]
    assert result.truncated is True


def test_profile_column_shows_stats_and_values(con: duckdb.DuckDBPyConnection) -> None:
    output = profile_column(con, "raw.jogos", "time")
    assert output["result"].startswith("Tipo: VARCHAR")
    assert "| A | 60 |" in output["result"]


def test_profile_column_rejects_unknown_column(con: duckdb.DuckDBPyConnection) -> None:
    output = profile_column(con, "jogos", "gols")
    assert "não existe" in output["error"]


def test_slow_query_is_interrupted(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(duckdb.InterruptException):
        query_rows(con, HEAVY_QUERY, timeout=0.2)
    assert query_rows(con, "SELECT 1 AS ok").rows == [(1,)]  # a conexão continua usável


@pytest.fixture
def agent_con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with connect(tmp_path / "test.duckdb") as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute("CREATE TABLE raw.jogos AS SELECT range AS id FROM range(3)")
    with connect_agent(tmp_path / "test.duckdb", tmp_path / "workspace.duckdb") as con:
        yield con


def test_save_result_creates_workspace_table(agent_con: duckdb.DuckDBPyConnection) -> None:
    output = save_result(agent_con, "pares", "SELECT id FROM raw.jogos WHERE id % 2 = 0 -- x")
    assert output == {"result": "Tabela workspace.pares criada com 2 linhas."}


@pytest.mark.parametrize(
    ("name", "query", "reason"),
    [
        ("Pares!", "SELECT 1", "inválido"),
        ("pares", "DROP TABLE raw.jogos", "Só consultas de leitura"),
        ("existente", "SELECT 1", "já existe"),
    ],
)
def test_save_result_refuses_bad_requests(
    agent_con: duckdb.DuckDBPyConnection, name: str, query: str, reason: str
) -> None:
    agent_con.execute("CREATE TABLE workspace.existente AS SELECT 1 AS x")
    output = save_result(agent_con, name, query)
    assert output["error"].startswith("Pedido recusado")
    assert reason in output["error"]
