"""Testes do validador de SQL (camada 1): o que passa e o que é recusado, com o motivo."""

import pytest

from olheiro.sql_guard import UnsafeQueryError, check_query


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT team FROM raw.brasileirao WHERE place = 1;",
        "WITH c AS (SELECT * FROM raw.brasileirao) SELECT count(*) FROM c",
        "SELECT season FROM raw.brasileirao UNION ALL SELECT founded FROM raw.teams",
        "SELECT team, RANK() OVER (ORDER BY goals DESC) AS r FROM raw.brasileirao QUALIFY r = 1",
        "SELECT * FROM workspace.campeoes",
        "SELECT b.team, t.region FROM raw.brasileirao b LEFT JOIN raw.teams t USING (team)",
    ],
)
def test_accepts_read_only_queries_on_allowed_tables(sql: str) -> None:
    check_query(sql)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DROP TABLE raw.teams", "Só consultas de leitura"),
        ("INSERT INTO raw.teams (team) VALUES ('x')", "Só consultas de leitura"),
        ("COPY (SELECT 1) TO 'vazou.csv'", "Só consultas de leitura"),
        ("ATTACH 'outro.duckdb' AS outro", "Só consultas de leitura"),
        ("SET enable_external_access = true", "Só consultas de leitura"),
        ("SELECT 1; DROP TABLE raw.teams", "exatamente uma consulta"),
        ("SELECT * FROM read_csv('/etc/hosts')", "Funções de tabela"),
        ("SELECT * FROM (SELECT * FROM read_parquet('x.parquet'))", "Funções de tabela"),
        ("SELECT * FROM '/etc/hosts'", "não permitida"),
        ("SELECT * FROM lake.raw.teams", "sem catálogo"),
        ("SELECT * FROM information_schema.tables", "não permitida"),
        ("SELECT * FROM brasileirao", "não permitida"),
        ("SELEC 1", "SQL inválido"),
    ],
)
def test_rejects_unsafe_queries_with_a_reason(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        check_query(sql)
