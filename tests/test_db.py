"""Testes da carga de CSVs no DuckDB (usam arquivos temporários, não os dados reais)."""

from pathlib import Path

import pytest

from olheiro.db import connect, load_raw_dir, table_name_from_file


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("brasileirao.csv", "brasileirao"),
        ("Brasileirão 2024.csv", "brasileirao_2024"),
        ("2024.csv", "t_2024"),
        ("times-série-A.csv", "times_serie_a"),
    ],
)
def test_table_name_from_file(filename: str, expected: str) -> None:
    assert table_name_from_file(Path(filename)) == expected


def write_csv(folder: Path, name: str, content: str) -> None:
    (folder / name).write_text(content, encoding="utf-8")


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "raw"
    folder.mkdir()
    write_csv(folder, "jogos.csv", "ano,mandante,gols\n2023,Palmeiras,2\n2023,Santos,1\n")
    return folder


def test_load_creates_raw_tables_and_workspace(tmp_path: Path, raw_dir: Path) -> None:
    with connect(tmp_path / "test.duckdb") as con:
        loaded = load_raw_dir(con, raw_dir)
        total_goals = con.execute("SELECT sum(gols) FROM raw.jogos").fetchone()[0]
        schema_rows = con.execute("SELECT schema_name FROM duckdb_schemas()").fetchall()
        schemas = {name for (name,) in schema_rows}

    assert [(t.name, t.row_count, t.column_count) for t in loaded] == [("jogos", 2, 3)]
    assert total_goals == 3  # DuckDB inferiu "gols" como número
    assert "workspace" in schemas


def test_reload_mirrors_raw_folder(tmp_path: Path, raw_dir: Path) -> None:
    """Recarregar não duplica linhas e remove tabelas de CSVs apagados."""
    write_csv(raw_dir, "extra.csv", "a\n1\n")
    with connect(tmp_path / "test.duckdb") as con:
        load_raw_dir(con, raw_dir)
        (raw_dir / "extra.csv").unlink()
        load_raw_dir(con, raw_dir)
        tables = con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'raw'"
        ).fetchall()
        rows = con.execute("SELECT count(*) FROM raw.jogos").fetchone()[0]

    assert tables == [("jogos",)]
    assert rows == 2
