import json
from pathlib import Path

import duckdb
import pytest

from olheiro.backup import MANIFEST, create_backup, restore_backup, verify_backup


def test_backup_and_restore_preserve_state_and_do_not_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "state"
    source.mkdir()
    (source / "cache.json").write_text('{"answer": "dado pessoal"}')
    with duckdb.connect(str(source / "workspace.duckdb")) as con:
        con.execute("CREATE TABLE saved AS SELECT 42 AS total")
    backup = create_backup(source, tmp_path / "backup")
    assert len(verify_backup(backup)) == 2
    restored = restore_backup(backup, tmp_path / "restored")
    assert (restored / "cache.json").read_bytes() == (source / "cache.json").read_bytes()
    with duckdb.connect(str(restored / "workspace.duckdb")) as con:
        assert con.execute("SELECT total FROM saved").fetchall() == [(42,)]
    with pytest.raises(FileExistsError):
        restore_backup(backup, source)
    assert (backup.stat().st_mode & 0o777) == 0o700


def test_corrupted_backup_is_rejected_before_creating_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.json").write_text("original")
    backup = create_backup(source, tmp_path / "backup")
    (backup / "data.json").write_text("corrompido")
    with pytest.raises(ValueError, match="corrompido"):
        restore_backup(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_active_database_and_wal_are_not_copied(tmp_path: Path) -> None:
    source = tmp_path / "state"
    source.mkdir()
    with duckdb.connect(str(source / "workspace.duckdb")) as con:
        con.execute("CREATE TABLE state AS SELECT 1")
        with pytest.raises(ValueError):
            create_backup(source, tmp_path / "backup")
    (source / "interrupted.wal").write_bytes(b"pending")
    with pytest.raises(ValueError, match="WAL"):
        create_backup(source, tmp_path / "backup2")


def test_backup_does_not_follow_symlinks_or_restore_external_paths(tmp_path: Path) -> None:
    source = tmp_path / "state"
    source.mkdir()
    (tmp_path / "private").write_text("segredo")
    (source / "link").symlink_to(tmp_path / "private")
    with pytest.raises(ValueError, match="simbólicos"):
        create_backup(source, tmp_path / "backup")
    (source / "link").unlink()
    (source / MANIFEST).write_text(json.dumps({"version": 1, "files": {"../private": "hash"}}))
    with pytest.raises(ValueError, match="Caminho"):
        restore_backup(source, tmp_path / "restored")
