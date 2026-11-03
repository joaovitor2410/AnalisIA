"""Terminal: cache disponível sem chave e falhas do modelo com orientação legível."""

from pathlib import Path

import pytest
from pydantic_ai.usage import RunUsage

from olheiro import cli
from olheiro.agent import AnalysisAnswer, build_report
from olheiro.cache import AnswerCache
from olheiro.config import Settings
from olheiro.datasets import cache_revision
from olheiro.db import connect, connect_agent


@pytest.fixture
def cached_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        _env_file=None,
        google_api_key=None,
        duckdb_path=tmp_path / "source.duckdb",
        workspace_path=tmp_path / "workspace.duckdb",
        answer_cache_path=tmp_path / "cache.json",
        runs_path=tmp_path / "runs.jsonl",
        glossary_path=None,
        olheiro_tracing="off",
    )
    with connect(settings.duckdb_path) as con:
        con.execute("CREATE SCHEMA raw")
        con.execute("CREATE TABLE raw.vendas AS SELECT 42 AS valor")
    with connect_agent(settings.duckdb_path, settings.workspace_path) as con:
        report = build_report(
            AnalysisAnswer(
                answerable=True, answer="Total: 42.", sql="SELECT valor FROM raw.vendas"
            ),
            con,
            "teste",
            RunUsage(),
            [],
        )
        AnswerCache(settings.answer_cache_path, cache_revision(settings)).store("Total?", report)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    return settings


def test_cli_answers_from_cache_without_building_a_model(
    cached_cli: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_model", lambda _: pytest.fail("Cache tentou usar o modelo"))
    cli.main(["Total?"])
    output = capsys.readouterr().out
    assert "Total: 42." in output and "resposta do cache" in output and "0 requisições" in output


@pytest.mark.parametrize("args", [["Outra pergunta?"], ["--no-cache", "Total?"]])
def test_cli_requires_a_key_only_when_the_model_is_needed(
    cached_cli: Settings, args: list[str]
) -> None:
    with pytest.raises(SystemExit, match="GOOGLE_API_KEY não definida"):
        cli.main(args)
