"""Testes da camada semântica: glossário em sincronia com os dados e contexto renderizado."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from olheiro.config import PROJECT_ROOT
from olheiro.db import connect, connect_agent, load_raw_dir
from olheiro.semantic import Glossary, check_glossary, load_glossary, render_context

GLOSSARY_PATH = PROJECT_ROOT / "semantic" / "glossary.toml"


@pytest.fixture
def real_data(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Os CSVs reais de data/raw carregados num banco temporário (não mexe no banco do projeto)."""
    with connect(tmp_path / "test.duckdb") as setup:
        load_raw_dir(setup, PROJECT_ROOT / "data" / "raw")
    with connect_agent(tmp_path / "test.duckdb", tmp_path / "workspace.duckdb") as con:
        yield con


def test_project_glossary_matches_the_real_data(real_data: duckdb.DuckDBPyConnection) -> None:
    """Se uma coluna mudar nos CSVs, este teste quebra até o glossário ser atualizado."""
    assert check_glossary(load_glossary(GLOSSARY_PATH), real_data) == []


def test_check_glossary_finds_divergences_both_ways(real_data: duckdb.DuckDBPyConnection) -> None:
    glossary = Glossary.model_validate(
        {"tables": {"teams": {"description": "x", "columns": {"team": "x", "fantasma": "x"}}}}
    )
    problems = check_glossary(glossary, real_data)
    assert "coluna inexistente: teams.fantasma" in problems
    assert "coluna sem descrição: teams.region" in problems
    assert "coluna sem descrição: brasileirao.season" in problems


def test_render_context_combines_glossary_catalog_values_and_rules(
    real_data: duckdb.DuckDBPyConnection,
) -> None:
    real_data.execute("CREATE TABLE workspace.campeoes AS SELECT 1 AS season")

    context = render_context(load_glossary(GLOSSARY_PATH), real_data)

    assert "  - goals BIGINT: Gols marcados." in context  # tipo do banco + texto do glossário
    assert "Valores: Central, North, Northeast, South, Southeast." in context  # valores reais
    assert "  - workspace.campeoes: season INTEGER" in context  # tabelas salvas aparecem
    assert "- Campeão de uma temporada: place = 1." in context


def test_plain_text_column_is_shorthand_for_description() -> None:
    glossary = Glossary.model_validate(
        {
            "tables": {
                "t": {"description": "d", "columns": {"a": "texto", "b": {"description": "x"}}}
            }
        }
    )
    assert glossary.tables["t"].columns["a"].description == "texto"
    assert glossary.tables["t"].columns["a"].list_values is False
