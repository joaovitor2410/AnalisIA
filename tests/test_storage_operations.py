"""Coordenação real entre processos, publicação atômica e retenção dos arquivos locais."""

import json
import select
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel

from olheiro import demo, storage
from olheiro.demo import BudgetUnavailableError, QuestionBudget
from olheiro.storage import JsonFile, JsonLines


class Counter(BaseModel):
    value: int = 0


class Entry(BaseModel):
    worker: int
    index: int
    text: str = "ação"


WORKER = """
import sys
import time
import signal
from pathlib import Path
from pydantic import BaseModel
from olheiro.storage import JsonFile, JsonLines
from olheiro.demo import QuestionBudget

class Counter(BaseModel):
    value: int = 0

class Entry(BaseModel):
    worker: int
    index: int
    text: str = "ação"

action, filename, identity = sys.argv[1:]
path = Path(filename)
if action == "counter":
    store = JsonFile(path, Counter)
    for _ in range(30):
        with store.update() as data:
            time.sleep(0.001)
            data.value += 1
elif action == "log":
    log = JsonLines(path, Entry, max_bytes=512, backup_count=20)
    for i in range(30):
        log.append(Entry(worker=int(identity), index=i))
elif action == "budget":
    budget = QuestionBudget(7, path)
    print(sum(budget.take() for _ in range(20)))
elif action == "hold":
    with JsonFile(path, Counter).update() as data:
        data.value = 999
        print("locked", flush=True)
        signal.pause()
"""


def workers(action: str, path: Path) -> list[str]:
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, action, str(path), str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(4)
    ]
    outputs = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
    return outputs


def test_independent_processes_do_not_lose_json_updates(tmp_path: Path) -> None:
    path = tmp_path / "counter.json"
    workers("counter", path)
    assert JsonFile(path, Counter).read().value == 120


def test_different_objects_in_threads_share_the_file_transaction(tmp_path: Path) -> None:
    path = tmp_path / "counter.json"

    def increment(_: int) -> None:
        store = JsonFile(path, Counter)
        for _ in range(10):
            with store.update() as data:
                data.value += 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(8)))
    assert JsonFile(path, Counter).read().value == 80


def test_failed_transaction_and_failed_publication_keep_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonFile(tmp_path / "counter.json", Counter)
    with store.update() as data:
        data.value = 1
    before = store.path.read_bytes()
    with pytest.raises(RuntimeError), store.update() as data:
        data.value = 2
        raise RuntimeError("Cancelado")
    assert store.path.read_bytes() == before
    original = Path.replace

    def fail(source: Path, target: Path) -> Path:
        if source.suffix == ".tmp":
            raise OSError("Falha de publicação simulada")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError), store.update() as data:
        data.value = 3
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_killed_writer_releases_lock_without_publishing_partial_state(tmp_path: Path) -> None:
    path = tmp_path / "counter.json"
    with JsonFile(path, Counter).update() as data:
        data.value = 1
    process = subprocess.Popen(
        [sys.executable, "-c", WORKER, "hold", str(path), "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 15)
        assert ready and process.stdout.readline().strip() == "locked"
        assert JsonFile(path, Counter).read().value == 1
    finally:
        process.kill()
        process.communicate(timeout=10)
    with JsonFile(path, Counter).update() as data:
        data.value += 1
    assert JsonFile(path, Counter).read().value == 2


def test_corrupt_state_is_preserved_instead_of_silently_reset(tmp_path: Path) -> None:
    path = tmp_path / "counter.json"
    path.write_text('{"value":')
    with pytest.raises(ValueError), JsonFile(path, Counter).update():
        pytest.fail("Estado corrompido foi aceito")
    assert path.read_text() == '{"value":'


def test_jsonl_rotation_bounds_bytes_and_retains_a_readable_recent_suffix(tmp_path: Path) -> None:
    log = JsonLines(tmp_path / "events.jsonl", Entry, max_bytes=140, backup_count=2)
    for i in range(30):
        log.append(Entry(worker=0, index=i))
    paths = [log.path, *log.file.archives()]
    assert len(paths) == 3
    assert all(path.stat().st_size <= 140 for path in paths)
    indexes = [record.index for record in log.read()]
    assert indexes == list(range(indexes[0], 30))
    assert 0 < indexes[0] < 29


def test_processes_rotate_the_same_log_without_losing_or_splitting_records(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    workers("log", path)
    records = JsonLines(path, Entry).read()
    assert len(records) == 120
    assert {(record.worker, record.index) for record in records} == {
        (worker, index) for worker in range(4) for index in range(30)
    }
    assert path.with_name(path.name + ".1").exists()
    assert all(
        file.stat().st_size <= 512 for file in [path, *JsonLines(path, Entry).file.archives()]
    )


def test_append_after_a_truncated_utf8_line_preserves_the_new_record(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"text":"a\xc3')
    log = JsonLines(path, Entry)
    wanted = Entry(worker=0, index=1)
    log.append(wanted)
    assert log.read() == [wanted]


def test_oversized_log_record_is_omitted_without_exposing_its_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = JsonLines(tmp_path / "events.jsonl", Entry, max_bytes=100, backup_count=1)
    log.append(Entry(worker=0, index=1, text="conteúdo privado" * 100))
    assert log.read() == []
    assert "omitido" in caplog.text and "conteúdo privado" not in caplog.text


def test_budget_survives_recreation_and_shares_one_limit_between_processes(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    accepted = sum(int(output) for output in workers("budget", path))
    assert accepted == 7
    assert not QuestionBudget(7, path).take()
    assert json.loads(path.read_text())["used"] == 7


def test_budget_renews_on_next_utc_day_but_rejects_a_clock_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "budget.json"
    monkeypatch.setattr(demo, "utc_today", lambda: date(2026, 11, 4))
    assert QuestionBudget(1, path).take()
    assert not QuestionBudget(1, path).take()
    monkeypatch.setattr(demo, "utc_today", lambda: date(2026, 11, 5))
    assert QuestionBudget(1, path).take()
    monkeypatch.setattr(demo, "utc_today", lambda: date(2026, 11, 4))
    with pytest.raises(BudgetUnavailableError):
        QuestionBudget(1, path).take()


@pytest.mark.parametrize(
    "content",
    ['{"used":', '{"answers": {}}', '{"used": -1}', '{"day": null, "used": 10}', '{"used": 1}'],
)
def test_unreadable_or_incompatible_budget_never_authorizes_a_request(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "budget.json"
    path.write_text(content)
    with pytest.raises(BudgetUnavailableError):
        QuestionBudget(10, path).take()
    assert path.read_text() == content


def test_failed_budget_publication_never_authorizes_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object) -> None:
        raise OSError("Disco indisponível")

    monkeypatch.setattr(storage, "atomic_text", fail)
    with pytest.raises(BudgetUnavailableError):
        QuestionBudget(10, tmp_path / "budget.json").take()
