"""F9B: ingestão reproduzível, diagnósticos e semântica em bases de outros domínios."""

from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError
from pydantic_ai.usage import RunUsage

from olheiro import semantic_store
from olheiro.agent import AnalysisAnswer, build_report
from olheiro.cache import AnswerCache
from olheiro.config import Settings
from olheiro.datasets import cache_revision, import_dataset, main
from olheiro.db import connect, connect_agent, load_raw_dir, scalar
from olheiro.import_options import FileOptions, ImportOptions, load_import_options
from olheiro.ingestion import preview_files
from olheiro.launcher import ensure_database
from olheiro.quality import check_relationship, table_quality
from olheiro.semantic import (
    MAX_CONTEXT_CHARS,
    ColumnDoc,
    Glossary,
    TableDoc,
    describe_table,
    discover_tables,
    load_glossary,
    read_semantics,
    render_context,
)
from olheiro.semantic_store import manifest_revision, save_dataset_glossary
from olheiro.sql_guard import check_query


@pytest.fixture
def imported(tmp_path: Path) -> Settings:
    source = tmp_path / "estoque.csv"
    source.write_text("produto,quantidade\n001,10\n002,20\n", encoding="utf-8")
    manifest = import_dataset([source], tmp_path / "bases", "estoque", "Estoque")
    return Settings(_env_file=None, olheiro_tracing="off").for_dataset(manifest)


@pytest.mark.parametrize("encoding", ["cp1252", "latin-1", "utf-16", "utf-8-sig"])
def test_preview_import_and_reload_agree_with_encoding_decimals_and_identifiers(
    tmp_path: Path, encoding: str
) -> None:
    source = tmp_path / "vendas.csv"
    source.write_bytes(
        "id;valor;cidade\n001;12,50;São Luís\n002;10,25;Fortaleza\n".encode(encoding)
    )
    original = source.read_bytes()
    options = ImportOptions(
        files={
            source.name: FileOptions(
                delimiter=";",
                header=True,
                encoding=encoding,
                decimal_separator=",",
                types={"id": "VARCHAR"},
            )
        }
    )
    preview = preview_files([source], options)[0]
    assert preview.sample.rows == [("001", 12.5, "São Luís"), ("002", 10.25, "Fortaleza")]
    assert not (tmp_path / "bases").exists()
    config = Settings(_env_file=None).for_dataset(
        import_dataset(
            [source],
            tmp_path / "bases",
            "vendas",
            "Vendas",
            options=options,
        )
    )
    assert load_import_options(config.import_options_path) == options
    with connect(config.duckdb_path) as con:
        load_raw_dir(con, config.raw_data_dir, load_import_options(config.import_options_path))
        assert con.execute("SELECT * FROM raw.vendas").fetchall() == preview.sample.rows
    assert source.read_bytes() == original
    config.duckdb_path.unlink()
    assert ensure_database(config)  # reconstrução também usa as opções persistidas
    with connect(config.duckdb_path, read_only=True) as con:
        assert scalar(con, "SELECT id FROM raw.vendas ORDER BY id LIMIT 1") == "001"


def test_preview_checks_all_rows_and_failed_types_publish_nothing(tmp_path: Path) -> None:
    source = tmp_path / "pedidos.csv"
    source.write_text("id,valor\n" + "1,10\n" * 50 + "2,inválido\n", encoding="utf-8")
    options = ImportOptions(
        files={source.name: FileOptions(header=True, types={"valor": "BIGINT"})}
    )
    with pytest.raises(duckdb.Error):
        preview_files([source], options)
    with pytest.raises(duckdb.Error):
        import_dataset([source], tmp_path / "bases", "pedidos", "Pedidos", options=options)
    assert not (tmp_path / "bases/pedidos").exists()


def test_headerless_text_and_parquet_overrides(tmp_path: Path) -> None:
    csv, parquet = tmp_path / "sem_header.csv", tmp_path / "produtos.parquet"
    csv.write_text("001;10\n002;20\n", encoding="utf-8")
    with duckdb.connect() as con:
        con.execute("COPY (SELECT 12 AS codigo) TO ? (FORMAT PARQUET)", [str(parquet)])
    previews = preview_files(
        [csv, parquet],
        ImportOptions(
            files={
                csv.name: FileOptions(header=False, delimiter=";", all_varchar=True),
                parquet.name: FileOptions(types={"codigo": "VARCHAR"}),
            }
        ),
    )
    assert previews[0].sample.rows == [("001", "10"), ("002", "20")]
    assert previews[1].sample.rows == [("12",)]


def test_import_options_reject_unknown_files_columns_and_sql_types(tmp_path: Path) -> None:
    csv = tmp_path / "v.csv"
    csv.write_text("n\n1\n", encoding="utf-8")
    for options in [
        ImportOptions(files={"missing.csv": FileOptions()}),
        ImportOptions(files={csv.name: FileOptions(types={"missing": "VARCHAR"})}),
    ]:
        with pytest.raises((ValueError, duckdb.Error)):
            preview_files([csv], options)
    with pytest.raises(ValidationError):
        FileOptions(types={"n": "VARCHAR); DROP SCHEMA raw CASCADE; --"})
    with pytest.raises(ValidationError):
        FileOptions(delimiter="\n")


def test_cli_preview_does_not_create_a_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "v.csv"
    source.write_text("valor\n42\n", encoding="utf-8")
    monkeypatch.setenv("DATASETS_DIR", str(tmp_path / "bases"))
    main(["preview", str(source)])
    assert "42" in capsys.readouterr().out
    assert not (tmp_path / "bases").exists()


def test_quality_counts_nulls_duplicate_rows_and_real_key_candidates() -> None:
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.estoque AS SELECT * FROM (VALUES "
            "('001', 10), ('001', 10), ('002', NULL)) t(produto, quantidade)"
        )
        report = table_quality(con, "estoque")
        assert report.total_rows == 3 and report.duplicate_rows == 1
        assert [(c.nulls, c.distinct, c.candidate_key) for c in report.columns] == [
            (0, 2, False),
            (1, 1, False),
        ]
        con.execute("CREATE TABLE raw.clientes AS SELECT 1 AS id, 'A' AS nome")
        assert all(c.candidate_key for c in table_quality(con, "clientes").columns)
        con.execute("DELETE FROM raw.clientes")
        assert not any(c.candidate_key for c in table_quality(con, "clientes").columns)
        for sql in report.sql:
            check_query(sql)


@pytest.mark.parametrize(
    "right_values,expected",
    [
        ("(1), (2)", True),
        ("(1), (1), (2)", False),
        ("(1)", False),
        ("(1), (2), (NULL)", False),
    ],
)
def test_relationship_requires_actual_coverage_and_unique_non_null_destination(
    right_values: str, expected: bool
) -> None:
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.pedidos AS SELECT * FROM (VALUES (1), (1), (2), (NULL)) t(cliente_id)"
        )
        con.execute(
            f"CREATE TABLE raw.clientes AS SELECT * FROM (VALUES {right_values}) t(cliente_id)"
        )
        report = check_relationship(con, "pedidos", "cliente_id", "clientes", "cliente_id")
        check_query(report.sql)
        assert report.compatible is expected
        assert report.evidence.rows[0][6] in (
            2,
            3,
        )  # nunca multiplica linhas pela duplicação no destino
        if expected:
            assert report.cardinality == "muitos para um"


def test_semantic_save_is_versioned_invalidates_cache_and_rejects_stale_edits(
    imported: Settings,
) -> None:
    assert imported.olheiro_dataset is not None
    previous = manifest_revision(imported.olheiro_dataset)
    old_revision = cache_revision(imported)
    glossary = Glossary(
        tables={
            "estoque": TableDoc(
                description="Saldo por produto",
                columns={
                    "quantidade": ColumnDoc(
                        description='Saldo físico, não "vendas".', unit="unidades"
                    ),
                },
            )
        },
        rules=["Cada linha representa um produto."],
    )
    with connect_agent(imported.duckdb_path, imported.workspace_path) as con:
        report = build_report(
            AnalysisAnswer(
                answerable=True, answer="30", sql="SELECT sum(quantidade) FROM raw.estoque"
            ),
            con,
            "teste",
            RunUsage(),
            [],
        )
        AnswerCache(imported.answer_cache_path, old_revision).store("Total?", report)
        updated = save_dataset_glossary(imported, con, glossary, previous)
        assert load_glossary(updated.glossary_path) == glossary
        assert "Unidade: unidades" in render_context(glossary, con)
        assert cache_revision(updated) != old_revision
        assert (
            AnswerCache(updated.answer_cache_path, cache_revision(updated)).lookup("Total?", con)
            is None
        )
        with pytest.raises(ValueError, match="outra sessão"):
            save_dataset_glossary(imported, con, glossary, previous)
    assert updated.glossary_path is not None and updated.glossary_path.name.startswith("glossary.")


def test_semantic_failure_preserves_previous_manifest_and_rejects_bad_references(
    imported: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = imported.olheiro_dataset
    assert path is not None
    before = path.read_bytes()
    revision = manifest_revision(path)
    with connect_agent(imported.duckdb_path, None) as con:
        with pytest.raises(ValueError, match="incompatível"):
            save_dataset_glossary(
                imported, con, Glossary(tables={"fantasma": TableDoc(description="x")}), revision
            )
        original = semantic_store.atomic_text

        def fail_manifest(destination: Path, content: str) -> None:
            if destination == path:
                raise OSError("falha simulada")
            original(destination, content)

        monkeypatch.setattr(semantic_store, "atomic_text", fail_manifest)
        with pytest.raises(OSError):
            save_dataset_glossary(imported, con, Glossary(rules=["Regra nova"]), revision)
    assert path.read_bytes() == before
    assert imported.for_dataset(path).glossary_path is None


def test_large_catalog_remains_discoverable_with_bounded_context() -> None:
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute("ATTACH ':memory:' AS workspace")
        for number in range(25):
            con.execute(f"CREATE TABLE raw.t{number:02d} AS SELECT 1 AS id, 2 AS valor")
        con.execute(
            "CREATE TABLE raw.wide AS SELECT " + ", ".join(f"{n} AS c{n}" for n in range(90))
        )
        glossary = Glossary(rules=["Regra " + str(n) for n in range(30)])
        context = render_context(glossary, con)
        assert len(context) <= MAX_CONTEXT_CHARS and "truncado" in context
        assert "raw.wide" in discover_tables(glossary, con, "wide")
        assert "c89" in describe_table(glossary, con, "wide", offset=80)
        assert "Regra 29" in read_semantics(glossary, offset=28)
        assert "raw.wide" in discover_tables(glossary, con, offset=20)


def test_long_descriptions_and_rules_are_retrievable_without_silent_truncation() -> None:
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute("CREATE TABLE raw.t AS SELECT 1 AS id")
        con.execute("ATTACH ':memory:' AS workspace")
        description = "a" * 1000 + " significado final"
        glossary = Glossary(
            tables={
                "t": TableDoc(
                    description=description,
                    columns={
                        "id": ColumnDoc(description=description, unit="unidades"),
                    },
                )
            },
            rules=["r" * 1000 + " regra final"],
        )
        assert "truncado" in render_context(glossary, con)
        assert read_semantics(glossary, "raw.t") == description
        assert "significado final" in read_semantics(glossary, "raw.t", "id")
        assert "regra final" in read_semantics(glossary)
