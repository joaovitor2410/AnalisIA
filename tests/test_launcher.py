"""Inicialização reproduzível: carga atômica, preservação dos bancos e diagnóstico de falhas."""

from pathlib import Path

import duckdb
import pytest

from olheiro import launcher
from olheiro.config import PROJECT_ROOT, Settings
from olheiro.db import connect, scalar
from olheiro.launcher import ensure_database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        duckdb_path=tmp_path / "data" / "olheiro.duckdb",
        raw_data_dir=PROJECT_ROOT / "data" / "raw",
        glossary_path=PROJECT_ROOT / "semantic" / "glossary.toml",
    )


def test_first_start_loads_real_data_and_repeated_start_preserves_it(settings: Settings) -> None:
    assert ensure_database(settings) is True
    with connect(settings.duckdb_path) as con:
        assert scalar(con, "SELECT count(*) FROM raw.brasileirao") == 450
        assert scalar(con, "SELECT count(*) FROM raw.teams") == 45
        con.execute("CREATE TABLE preserved AS SELECT 42 AS n")
    assert ensure_database(settings) is False
    with connect(settings.duckdb_path, read_only=True) as con:
        assert scalar(con, "SELECT n FROM preserved") == 42
    assert not list(settings.duckdb_path.parent.glob("olheiro-load-*"))


def test_missing_csvs_do_not_create_an_empty_database(settings: Settings, tmp_path: Path) -> None:
    missing = settings.model_copy(update={"raw_data_dir": tmp_path / "missing"})
    with pytest.raises(ValueError, match="Nenhum CSV"):
        ensure_database(missing)
    assert not missing.duckdb_path.exists()


def test_failed_load_leaves_no_database_or_temporary_files(
    settings: Settings, tmp_path: Path
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    # Os dois nomes normalizam para a mesma tabela: a carga recusa antes de alterar raw.
    (raw / "same.csv").write_text("n\n1\n", encoding="utf-8")
    (raw / "same!.csv").write_text("n\n2\n", encoding="utf-8")
    config = settings.model_copy(update={"raw_data_dir": raw})
    with pytest.raises(ValueError, match="conflito"):
        ensure_database(config)
    assert not config.duckdb_path.exists()
    assert not list(config.duckdb_path.parent.iterdir())


def test_glossary_mismatch_is_not_published(settings: Settings, tmp_path: Path) -> None:
    glossary = tmp_path / "wrong.toml"
    glossary.write_text('[tables.unknown]\ndescription="Tabela ausente"\n', encoding="utf-8")
    config = settings.model_copy(update={"glossary_path": glossary})
    with pytest.raises(ValueError, match="Glossário"):
        ensure_database(config)
    assert not config.duckdb_path.exists()


def test_incomplete_existing_database_is_reported_and_preserved(settings: Settings) -> None:
    with connect(settings.duckdb_path) as con:
        con.execute("CREATE TABLE preserved AS SELECT 42 AS n")
    with pytest.raises(ValueError, match="Tabelas raw"):
        ensure_database(settings)
    with connect(settings.duckdb_path, read_only=True) as con:
        assert scalar(con, "SELECT n FROM preserved") == 42


def test_corrupt_existing_file_is_not_replaced(settings: Settings) -> None:
    settings.duckdb_path.parent.mkdir(parents=True)
    settings.duckdb_path.write_bytes(b"arquivo invalido")
    with pytest.raises(duckdb.Error):
        ensure_database(settings)
    assert settings.duckdb_path.read_bytes() == b"arquivo invalido"


def test_simultaneous_first_start_does_not_replace_a_new_database(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = launcher.load_raw_dir

    def concurrent_load(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> object:
        loaded = original(con, raw_dir)
        # Outro processo termina primeiro e publica uma base com um registro próprio.
        with connect(settings.duckdb_path) as other:
            original(other, raw_dir)
            other.execute("CREATE TABLE preserved AS SELECT 42 AS n")
        return loaded

    monkeypatch.setattr(launcher, "load_raw_dir", concurrent_load)
    assert ensure_database(settings) is False
    with connect(settings.duckdb_path, read_only=True) as con:
        assert scalar(con, "SELECT n FROM preserved") == 42


def test_launcher_rejects_a_locked_workspace_before_starting_another_server(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ensure_database(settings) is True
    monkeypatch.setattr(launcher, "get_settings", lambda: settings)

    def locked(*args: object) -> None:
        raise launcher.WorkspaceInUseError(settings.workspace_path, "Conflicting lock (PID 12345)")

    monkeypatch.setattr(launcher, "connect_agent", locked)
    monkeypatch.setattr(launcher.os, "execv", lambda *args: pytest.fail("Iniciou outro servidor"))
    with pytest.raises(SystemExit, match="PID 12345"):
        launcher.main([])
