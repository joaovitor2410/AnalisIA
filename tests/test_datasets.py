"""Mudança de domínio: ingestão real, evidência, isolamento e falhas sem perda de dados."""

from pathlib import Path
from types import SimpleNamespace

import anyio
import duckdb
import pytest
import streamlit as st
from mcp import Client
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage
from streamlit.testing.v1 import AppTest

from olheiro import mcp_server
from olheiro.agent import AgentDeps, AgentReport, AnalysisAnswer, build_report
from olheiro.cache import AnswerCache, ask_with_cache
from olheiro.check_setup import check_glossary_sync, check_tables
from olheiro.config import PROJECT_ROOT, Settings, get_settings
from olheiro.dashboard import DashboardStore
from olheiro.datasets import cache_revision, dataset_identity, discover_datasets, import_dataset
from olheiro.db import connect, connect_agent, find_data_files, load_raw_dir, scalar
from olheiro.launcher import ensure_database
from olheiro.semantic import distinct_values, load_glossary, render_context
from olheiro.tools import column_profile
from olheiro.ui import resources


@pytest.fixture
def sales(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "entradas"
    folder.mkdir()
    csv = folder / "Vendas.CSV"
    csv.write_text('cliente_id;valor;"observação ""extra"""\n1;100;ok\n2;175;\n', encoding="utf-8")
    parquet = folder / "Clientes.parquet"
    with duckdb.connect() as con:
        con.execute(
            "COPY (SELECT * FROM (VALUES (1, 'Sul'), (2, 'Norte')) t(cliente_id, regiao)) "
            "TO ? (FORMAT PARQUET)",
            [str(parquet)],
        )
    return [csv, parquet]


def config_for(path: Path) -> Settings:
    return Settings(_env_file=None).for_dataset(path)


def test_mixed_formats_analyze_a_new_domain_without_football_or_glossary(
    tmp_path: Path, sales: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(import_dataset(sales, tmp_path / "bases", "vendas", "Vendas da loja"))
    assert ensure_database(config) is False
    assert check_tables(config).ok and check_glossary_sync(config).ok
    assert config.glossary_path is None
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        instructions = " ".join(part.instructions or "" for part in messages)
        assert "raw.vendas" in instructions and "raw.clientes" in instructions
        assert "Catálogo automático" in instructions
        assert "Campeão de uma temporada" not in instructions
        assert "raw.brasileirao" not in instructions
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "Veja os totais por região.",
                        "sql": "SELECT regiao, sum(valor) AS total FROM raw.vendas v "
                        "JOIN raw.clientes c USING (cliente_id) GROUP BY regiao ORDER BY regiao",
                        "chart": {
                            "kind": "bar",
                            "x": "regiao",
                            "y": "total",
                            "title": "Vendas por região",
                        },
                    },
                )
            ]
        )

    with connect_agent(config.duckdb_path, None) as con:
        outcome = ask_with_cache(
            "Total por região?", AgentDeps(con), AnswerCache(None), FunctionModel(respond)
        )
        assert isinstance(outcome, AgentReport)
        assert outcome.evidence is not None
        assert outcome.evidence.rows == [("Norte", 175), ("Sul", 100)]
        profile = column_profile(con, "vendas", 'observação "extra"')
        assert profile.stats.rows[0][:3] == (2, 1, 1)


def test_snapshot_preserves_source_and_does_not_depend_on_original_files(
    tmp_path: Path, sales: list[Path]
) -> None:
    config = config_for(import_dataset(sales, tmp_path / "bases", "sales", "Sales"))
    sales[0].unlink()
    with connect_agent(config.duckdb_path, None) as con:
        assert scalar(con, "SELECT sum(valor) FROM raw.vendas") == 275
    assert (config.raw_data_dir / "Vendas.CSV").is_file()


def test_partial_glossary_is_optional_but_invalid_references_fail_cleanly(
    tmp_path: Path, sales: list[Path]
) -> None:
    root, glossary = tmp_path / "bases", tmp_path / "glossary.toml"
    glossary.write_text('[tables.vendas]\ndescription="Pedidos da loja"\n', encoding="utf-8")
    config = config_for(import_dataset(sales, root, "good", "Loja", glossary))
    assert check_glossary_sync(config).ok
    with connect_agent(config.duckdb_path, None) as con:
        assert "Pedidos da loja" in render_context(load_glossary(config.glossary_path), con)
    glossary.write_text('[tables.fantasma]\ndescription="Não existe"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Glossário incompatível"):
        import_dataset(sales, root, "bad", "Loja", glossary)
    assert not (root / "bad").exists()
    assert list(discover_datasets(root)) == [config.olheiro_dataset]


def test_failure_or_duplicate_name_never_overwrites_a_working_dataset(
    tmp_path: Path, sales: list[Path]
) -> None:
    root = tmp_path / "bases"
    config = config_for(import_dataset(sales, root, "good", "Loja"))
    original = config.duckdb_path.read_bytes()
    with pytest.raises(FileExistsError):
        import_dataset(sales, root, "good", "Outra loja")
    bad = tmp_path / "broken.parquet"
    bad.write_bytes(b"not a parquet")
    with pytest.raises(duckdb.Error):
        import_dataset([*sales, bad], root, "broken", "Inválida")
    assert not (root / "broken").exists()
    assert config.duckdb_path.read_bytes() == original


def test_empty_or_colliding_sources_and_failed_reload_keep_raw_intact(tmp_path: Path) -> None:
    folder = tmp_path / "input"
    folder.mkdir()
    csv = folder / "dados.csv"
    csv.write_text("n\n42\n", encoding="utf-8")
    with connect(tmp_path / "test.duckdb") as con:
        load_raw_dir(con, folder)
        (folder / "dados.parquet").write_bytes(b"bad")
        with pytest.raises(ValueError, match="conflito"):
            load_raw_dir(con, folder)
        (folder / "dados.parquet").rename(folder / "invalid.parquet")
        with pytest.raises(duckdb.Error):
            load_raw_dir(con, folder)
        assert scalar(con, "SELECT n FROM raw.dados") == 42
        for path in folder.iterdir():
            path.unlink()
        with pytest.raises(ValueError, match="Nenhum CSV ou Parquet"):
            load_raw_dir(con, folder)
        assert scalar(con, "SELECT n FROM raw.dados") == 42


@pytest.mark.parametrize("name", ["../escape", "/absolute", "", "with spaces", "a" * 65])
def test_unsafe_dataset_names_create_nothing(tmp_path: Path, sales: list[Path], name: str) -> None:
    with pytest.raises(ValueError, match="Identificador inválido"):
        import_dataset(sales, tmp_path / "bases", name, "Título")
    assert not (tmp_path / "bases").exists()


def test_cache_revision_invalidates_old_text_and_refusals_after_same_schema_reload(
    tmp_path: Path, sales: list[Path]
) -> None:
    config = config_for(import_dataset(sales, tmp_path / "bases", "vendas", "Vendas"))
    old_revision = cache_revision(config)
    old = AnswerCache(config.answer_cache_path, old_revision)
    with connect_agent(config.duckdb_path, None) as con:
        old.store(
            "Total?",
            build_report(
                AnalysisAnswer(
                    answerable=True, answer="275", sql="SELECT sum(valor) AS total FROM raw.vendas"
                ),
                con,
                "teste",
                RunUsage(),
                [],
            ),
        )
        old.store(
            "Há clientes?",
            build_report(
                AnalysisAnswer(answerable=False, answer="Não foram informados clientes."),
                con,
                "teste",
                RunUsage(),
                [],
            ),
        )
    (config.raw_data_dir / "Vendas.CSV").write_text("cliente_id;valor\n1;999\n", encoding="utf-8")
    with connect(config.duckdb_path) as con:
        load_raw_dir(con, config.raw_data_dir)
    assert cache_revision(config) != old_revision
    fresh = AnswerCache(config.answer_cache_path, cache_revision(config))
    assert fresh.questions() == []
    with connect_agent(config.duckdb_path, None) as con:
        assert fresh.lookup("Total?", con) is None
        assert old.lookup("Total?", con) is None  # evidência também é comparada
    assert old.questions()  # invalidação não apaga o arquivo antigo antes de haver nova resposta


def test_cache_and_dashboard_cannot_cross_datasets_with_identical_table_names(
    tmp_path: Path, sales: list[Path]
) -> None:
    root = tmp_path / "bases"
    first = config_for(import_dataset(sales, root, "a", "A"))
    second = config_for(import_dataset(sales, root, "b", "B"))
    cache_path, panel_path = tmp_path / "shared-cache.json", tmp_path / "shared-panel.json"
    with connect_agent(first.duckdb_path, None) as con:
        report = build_report(
            AnalysisAnswer(answerable=True, answer="275", sql="SELECT sum(valor) FROM raw.vendas"),
            con,
            "teste",
            RunUsage(),
            [],
        )
        AnswerCache(cache_path, cache_revision(first)).store("Total?", report)
        DashboardStore(panel_path, dataset_identity(first)).pin("Total?", report)
    assert AnswerCache(cache_path, cache_revision(second)).questions() == []
    assert DashboardStore(panel_path, dataset_identity(second)).read().items == []
    assert first.workspace_path != second.workspace_path
    assert first.runs_path != second.runs_path


def test_paths_with_apostrophes_open_and_keep_external_access_blocked(
    tmp_path: Path, sales: list[Path]
) -> None:
    config = config_for(import_dataset(sales, tmp_path / "d'ados", "a", "A"))
    with connect_agent(config.duckdb_path, config.workspace_path) as con:
        assert scalar(con, "SELECT count(*) FROM raw.vendas") == 2
        with pytest.raises(duckdb.PermissionException):
            con.execute("SELECT * FROM read_csv('/etc/hosts')")


def test_manifest_selection_applies_to_all_entrypoints_and_demo_refuses_it(
    tmp_path: Path, sales: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = import_dataset(sales, tmp_path / "bases", "a", "Nova base")
    monkeypatch.setenv("OLHEIRO_DATASET", str(manifest))
    assert get_settings().dataset_title == "Nova base"
    monkeypatch.setenv("OLHEIRO_DEMO_MODE", "true")
    with pytest.raises(ValueError, match="base fixa"):
        get_settings()


def test_ui_switches_domain_and_clears_pending_history_without_resetting_quota(
    tmp_path: Path, sales: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bases"
    first = import_dataset(sales, root, "vendas", "Vendas da loja")
    second = import_dataset([sales[0]], root, "outra", "Outra base")
    monkeypatch.setenv("OLHEIRO_DATASET", str(first))
    monkeypatch.setenv("DATASETS_DIR", str(root))
    monkeypatch.setattr(
        resources, "build_model", lambda _: (_ for _ in ()).throw(ValueError("offline"))
    )
    st.cache_resource.clear()
    try:
        app = AppTest.from_file(str(PROJECT_ROOT / "src/olheiro/app.py"), default_timeout=20).run()
        assert not app.exception
        assert app.selectbox(key="selected_dataset").options == ["Vendas da loja", "Outra base"]
        app.session_state["history"] = ["histórico da outra base"]
        app.session_state["pending"] = "aprovação pendente"
        app.session_state["model_questions"] = 2
        app.session_state["question_draft"] = "Rascunho da outra base"
        old_deps = app.session_state["deps"]
        old_conversation = app.session_state["conversation"]
        old_conversation.remember(
            "Questão da outra base",
            build_report(
                AnalysisAnswer(answerable=True, answer="1", sql="SELECT 1"),
                old_deps.con,
                "offline",
                RunUsage(),
                [],
            ),
        )
        app.selectbox(key="selected_dataset").set_value(str(second)).run()
        assert not app.exception
        assert app.session_state["history"] == [] and app.session_state["pending"] is None
        assert app.session_state["model_questions"] == 2
        assert app.session_state["conversation"] is not old_conversation
        assert app.session_state["conversation"].turn_count == 0
        assert not app.session_state.get("question_draft", "")
        assert any("Outra base" in caption.value for caption in app.caption)
        with pytest.raises(duckdb.ConnectionException):
            old_deps.con.execute("SELECT 1")
        assert not app.session_state["deps"].glossary.tables
    finally:
        st.cache_resource.clear()


def test_discovery_skips_incomplete_or_invalid_manifests(tmp_path: Path) -> None:
    for name, content in {"incomplete": 'title="Sem banco"', "broken": "invalid TOML!!!"}.items():
        folder = tmp_path / name
        folder.mkdir()
        (folder / "dataset.toml").write_text(content, encoding="utf-8")
    assert discover_datasets(tmp_path) == {}


def test_legacy_dashboard_is_preserved_only_with_explicit_migration(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.json"
    with duckdb.connect() as con:
        report = build_report(
            AnalysisAnswer(answerable=True, answer="1", sql="SELECT 1"),
            con,
            "teste",
            RunUsage(),
            [],
        )
        DashboardStore(path).pin("Original", report)
    assert not DashboardStore(path, "new").read().items
    migrating = DashboardStore(path, "original", allow_legacy=True)
    assert migrating.read().items[0].question == "Original"
    migrating.pin("Mais um", report)
    assert len(migrating.read().items) == 2
    assert not DashboardStore(path, "other").read().items


def test_mcp_reads_an_imported_non_football_dataset_without_api_key(
    tmp_path: Path, sales: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(import_dataset(sales, tmp_path / "bases", "sales", "Vendas"))
    monkeypatch.setattr(mcp_server, "build_model", lambda _: pytest.fail("Usou modelo"))

    async def scenario() -> None:
        async with Client(mcp_server.create_server(config)) as client:
            result = await client.call_tool(
                "run_sql", {"query": "SELECT sum(valor) AS total FROM raw.vendas"}
            )
            assert not result.is_error
            assert result.structured_content is not None
            assert result.structured_content["rows"] == [[275]]
            context = await client.read_resource("olheiro://context")
            assert "raw.vendas" in context.contents[0].text
            assert "raw.brasileirao" not in context.contents[0].text

    anyio.run(scenario)


def test_synthetic_retail_example_has_consistent_optional_semantics(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "examples/datasets/retail"
    config = config_for(
        import_dataset(
            find_data_files(source), tmp_path / "bases", "loja", "Loja", source / "glossary.toml"
        )
    )
    assert check_glossary_sync(config).ok
    with connect_agent(config.duckdb_path, None) as con:
        assert (
            scalar(con, "SELECT round(sum(amount), 2) FROM raw.orders WHERE status='concluido'")
            == 460.4
        )


def test_same_dataset_can_use_a_different_workspace_for_another_process(
    tmp_path: Path, sales: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = import_dataset(sales, tmp_path / "bases", "sales", "Vendas")
    monkeypatch.setenv("OLHEIRO_DATASET", str(manifest))
    monkeypatch.setenv("OLHEIRO_WORKSPACE_OVERRIDE", str(tmp_path / "mcp.duckdb"))
    assert get_settings().workspace_path == tmp_path / "mcp.duckdb"


def import_form() -> None:
    from olheiro.config import get_settings
    from olheiro.ui.data_page import show_import

    show_import(get_settings())


@pytest.mark.parametrize("scenario", ["valid", "duplicate", "oversized", "missing"])
def test_upload_form_imports_safely_and_reports_invalid_submissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    root = tmp_path / "bases"
    monkeypatch.setenv("DATASETS_DIR", str(root))
    monkeypatch.setenv("OLHEIRO_IMPORT_MAX_MB", "1")
    content = b"id,valor\n1,10\n"
    upload = SimpleNamespace(name="../../vendas.csv", size=len(content), getvalue=lambda: content)
    uploads = [upload]
    if scenario == "duplicate":
        uploads.append(SimpleNamespace(name="outra/vendas.csv", size=1, getvalue=lambda: b"x\n1\n"))
    if scenario == "oversized":
        upload.size = 2 * 1024**2
    if scenario == "missing":
        uploads = []
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploads)
    app = AppTest.from_function(import_form, default_timeout=20).run()
    app.text_input[0].set_value("Vendas")
    app.text_input[1].set_value("vendas")
    if scenario in {"valid", "missing"}:
        app.button(key="preview-import").click().run()
    if scenario == "valid":
        assert not discover_datasets(root)  # conferir não publica a base
        app.button(key="confirm-import").click().run()
    assert not app.exception
    if scenario == "valid":
        assert not app.error
        assert app.session_state["next_dataset"] == str(root / "vendas/dataset.toml")
        assert (root / "vendas/raw/vendas.csv").is_file()
        assert not (tmp_path / "vendas.csv").exists()
    else:
        assert app.error
        assert not discover_datasets(root)
        assert not (root / "vendas").exists()


def test_empty_table_is_valid_and_context_values_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    with duckdb.connect() as con:
        con.execute("COPY (SELECT 1 AS id WHERE false) TO ? (FORMAT PARQUET)", [str(path)])
    config = config_for(import_dataset([path], tmp_path / "bases", "empty", "Sem linhas"))
    assert ensure_database(config) is False and check_tables(config).ok
    with connect_agent(config.duckdb_path, config.workspace_path) as con:
        assert scalar(con, 'SELECT count(*) FROM raw."empty"') == 0
    with duckdb.connect() as con:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.t AS SELECT repeat('a', 200) || range "
            'AS "nome ""extra""" FROM range(100)'
        )
        values = distinct_values(con, "t", 'nome "extra"')
        assert len(values) < 2200
        assert "Amostra/truncamento" in values
