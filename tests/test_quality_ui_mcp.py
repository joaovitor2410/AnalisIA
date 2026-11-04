"""F9B de ponta a ponta: prévia, editor, recarga das regras e descoberta MCP sem Gemini."""

from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
import streamlit as st
from mcp import Client
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from streamlit.testing.v1 import AppTest

from olheiro import mcp_server
from olheiro.config import Settings
from olheiro.conversation import Conversation
from olheiro.datasets import import_dataset
from olheiro.db import connect_agent
from olheiro.semantic import Glossary
from olheiro.semantic_store import manifest_revision, save_dataset_glossary
from olheiro.ui import resources


@pytest.fixture
def stock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    path = tmp_path / "estoque.csv"
    path.write_text("produto,quantidade\n001,10\n002,20\n", encoding="utf-8")
    manifest = import_dataset([path], tmp_path / "bases", "estoque", "Estoque")
    monkeypatch.setenv("OLHEIRO_DATASET", str(manifest))
    monkeypatch.setenv("DATASETS_DIR", str(tmp_path / "bases"))
    monkeypatch.setattr(
        resources, "build_model", lambda _: (_ for _ in ()).throw(ValueError("offline"))
    )
    st.cache_resource.clear()
    yield Settings(_env_file=None, olheiro_tracing="off").for_dataset(manifest)
    st.cache_resource.clear()


def data_page() -> None:
    from olheiro.ui.data_page import data_page

    data_page()


def import_page() -> None:
    from olheiro.config import get_settings
    from olheiro.ui.import_panel import show_import

    show_import(get_settings())


def test_editor_refreshes_context_without_reopening_database_or_resetting_quota(
    stock: Settings,
) -> None:
    app = AppTest.from_function(data_page, default_timeout=20).run()
    assert not app.exception
    old_con = app.session_state["deps"].con
    app.session_state["model_questions"] = 3
    app.session_state["history"] = ["resposta antiga"]
    app.session_state["pending"] = "aprovação antiga"
    app.session_state["conversation"] = Conversation()
    app.selectbox(key="semantic-column").set_value("quantidade").run()
    app.text_area[0].set_value("Saldo disponível por produto")
    app.text_area[1].set_value("Estoque físico")
    app.text_area[2].set_value("Cada linha representa o saldo de um produto.")
    next(item for item in app.text_input if item.label == "Unidade (opcional)").set_value(
        "unidades"
    )
    next(button for button in app.button if button.label == "Salvar semântica").click().run()
    assert not app.exception and not app.error
    assert app.session_state["deps"].con is old_con
    assert app.session_state["deps"].glossary.rules == [
        "Cada linha representa o saldo de um produto."
    ]
    assert (
        app.session_state["deps"].glossary.tables["estoque"].columns["quantidade"].unit
        == "unidades"
    )
    assert app.session_state["model_questions"] == 3
    assert not app.session_state.get("pending") and not app.session_state.get("history")
    assert app.session_state.get("conversation") is None
    app.button(key=f"quality-{stock.duckdb_path}-estoque").click().run()
    assert not app.exception
    assert any(metric.label == "Linhas duplicadas excedentes" for metric in app.metric)


def test_import_requires_new_preview_after_reading_options_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bases"
    monkeypatch.setenv("DATASETS_DIR", str(root))
    content = b"id,valor\n001,10\n002,20\n"
    upload = SimpleNamespace(name="vendas.csv", size=len(content), getvalue=lambda: content)
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: [upload])
    app = AppTest.from_function(import_page, default_timeout=20).run()
    assert app.button(key="confirm-import").disabled
    app.text_input[0].set_value("Vendas")
    app.text_input[1].set_value("vendas")
    app.button(key="preview-import").click().run()
    assert not app.exception and not app.button(key="confirm-import").disabled
    app.checkbox(key="text-vendas.csv").check().run()
    assert app.button(key="confirm-import").disabled and app.warning
    app.button(key="preview-import").click().run()
    assert not app.button(key="confirm-import").disabled
    app.button(key="confirm-import").click().run()
    assert not app.exception and not app.error
    with connect_agent(root / "vendas/source.duckdb", None) as con:
        assert con.execute("SELECT id FROM raw.vendas ORDER BY id").fetchall() == [
            ("001",),
            ("002",),
        ]


def test_import_type_editor_preserves_selected_identifiers_and_numeric_measures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bases"
    monkeypatch.setenv("DATASETS_DIR", str(root))
    content = b"id,valor\n001,10\n002,20\n"
    upload = SimpleNamespace(name="vendas.csv", size=len(content), getvalue=lambda: content)
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: [upload])
    app = AppTest.from_function(import_page, default_timeout=20).run()
    app.text_input[0].set_value("Vendas")
    app.text_input[1].set_value("vendas")
    app.button(key="preview-import").click().run()
    signature = app.session_state["import_preview"]["parse_signature"]
    app.session_state[f"types-vendas.csv-{signature}"] = {
        "edited_rows": {0: {"usar": "VARCHAR"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.run()
    assert app.button(key="confirm-import").disabled
    app.button(key="preview-import").click().run()
    assert not app.button(key="confirm-import").disabled
    app.button(key="confirm-import").click().run()
    assert not app.exception and not app.error
    with connect_agent(root / "vendas/source.duckdb", None) as con:
        assert con.execute("SELECT id, valor FROM raw.vendas ORDER BY id").fetchall() == [
            ("001", 10),
            ("002", 20),
        ]


def test_demo_does_not_offer_import_or_semantic_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLHEIRO_DEMO_MODE", "true")
    app = AppTest.from_function(import_page).run()
    assert not app.exception and not app.file_uploader and not app.button


def test_mcp_refreshes_semantics_and_invalidates_previous_answer_without_restart(
    stock: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def respond(messages: object, info: object) -> ModelResponse:
        calls.append("request")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answerable": True,
                        "answer": "O saldo é 30.",
                        "sql": "SELECT sum(quantidade) AS total FROM raw.estoque",
                    },
                )
            ]
        )

    monkeypatch.setattr(mcp_server, "build_model", lambda _: FunctionModel(respond))

    async def scenario() -> None:
        async with Client(mcp_server.create_server(stock)) as client:
            first = await client.call_tool("ask_question", {"question": "Qual o saldo?"})
            assert not first.is_error
            cached = await client.call_tool("ask_question", {"question": "Qual o saldo?"})
            assert cached.structured_content["from_cache"] is True
            assert len(calls) == 1
            assert stock.olheiro_dataset is not None
            with connect_agent(stock.duckdb_path, None) as con:
                save_dataset_glossary(
                    stock,
                    con,
                    Glossary(rules=["Saldo em unidades, não em reais."]),
                    manifest_revision(stock.olheiro_dataset),
                )
            context = await client.read_resource("olheiro://context")
            assert "Saldo em unidades" in context.contents[0].text
            updated = await client.call_tool("ask_question", {"question": "Qual o saldo?"})
            assert not updated.is_error and updated.structured_content["from_cache"] is False
            assert len(calls) == 2
            search = await client.call_tool("discover_tables", {"search": "quantidade"})
            schema = await client.call_tool("describe_table", {"table": "raw.estoque"})
            rules = await client.call_tool("read_semantics", {})
            assert not search.is_error and not schema.is_error and not rules.is_error
            assert "estoque" in str(search.content) and "quantidade" in str(schema.content)
            assert "Saldo em unidades" in str(rules.content)

    anyio.run(scenario)
