"""Regressões do site completo: chave por sessão, bases, upload e pergunta livre."""

import json
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
import streamlit as st
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from streamlit.testing.v1 import AppTest

from olheiro.config import PROJECT_ROOT, Settings
from olheiro.portfolio import portfolio_settings
from olheiro.ui import connection_panel
from olheiro.ui.resources import shared_resources, visitor_resources

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def apps() -> Iterator[list[AppTest]]:
    shared_resources.clear()
    portfolio_settings.clear()
    instances: list[AppTest] = []
    yield instances
    for app in instances:
        if "deps" in app.session_state:
            app.session_state["deps"].con.close()
        if "visitor-workspace" in app.session_state:
            app.session_state["visitor-workspace"].close()
    shared_resources.clear()
    portfolio_settings.clear()


def start(apps: list[AppTest]) -> AppTest:
    app = AppTest.from_file(str(PROJECT_ROOT / "portfolio_app.py"), default_timeout=30).run()
    assert not app.exception
    apps.append(app)
    return app


def connect(app: AppTest, key: str = "chave-apenas-do-teste") -> None:
    app.text_input(key="session-api-key").set_value(key)
    next(button for button in app.button if button.label == "Usar chave nesta sessão").click().run()
    assert not app.exception
    assert app.text_input(key="session-api-key").value == ""


def test_default_site_allows_dataset_changes_and_explains_missing_key(apps: list[AppTest]) -> None:
    app = start(apps)
    assert not app.chat_input[0].disabled
    assert len(app.selectbox(key="selected_dataset").options) == 3
    app.selectbox(key="selected_dataset").select_index(1).run()
    assert not app.exception
    assert "Estoque" in app.selectbox(key="selected_dataset").options[1]
    app.chat_input[0].set_value("Qual o saldo do SKU 001?").run()
    assert not app.exception
    assert any("Conecte sua chave" in error.value for error in app.error)


def test_connected_model_uses_active_dataset_and_context_and_disconnects(
    apps: list[AppTest], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        question = [p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)][
            -1
        ]
        sku = "01" if "do 01" in str(question) else "001"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "Saldo na tabela.",
                        "sql": f"SELECT sum(quantity) AS saldo FROM raw.stock WHERE sku='{sku}'",
                    },
                )
            ]
        )

    def build(settings: Settings) -> FunctionModel:
        assert settings.google_api_key.get_secret_value() == "chave-apenas-do-teste"
        return FunctionModel(respond)

    monkeypatch.setattr(connection_panel, "build_model", build)
    app = start(apps)
    app.selectbox(key="selected_dataset").select_index(1).run()
    selection = app.selectbox(key="selected_dataset").value
    connect(app)
    assert app.selectbox(key="selected_dataset").value == selection
    app.chat_input[0].set_value("Qual o saldo do SKU 001?").run()
    assert not app.exception
    assert app.session_state["history"][-1].report.evidence.rows == [(12,)]
    app.chat_input[0].set_value("E do 01?").run()
    assert not app.exception
    assert app.session_state["history"][-1].report.evidence.rows == [(0,)]
    assert "SKU 001" in str(calls[-1])
    root = Path(app.session_state["visitor-workspace"].folder.name)
    assert not any(
        b"chave-apenas-do-teste" in p.read_bytes() for p in root.rglob("*") if p.is_file()
    )
    app.button(key="disconnect-model").click().run()
    assert not app.exception
    assert app.session_state["visitor-workspace"].model is None
    assert app.selectbox(key="selected_dataset").value == selection


@pytest.mark.parametrize("extension", ["csv", "parquet"])
def test_full_site_import_preview_select_and_custom_question(
    apps: list[AppTest], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extension: str
) -> None:
    content = b"valor\n10\n20\n30\n"
    if extension == "parquet":
        path = tmp_path / "medicoes.parquet"
        with duckdb.connect() as con:
            con.execute(
                "COPY (SELECT * FROM (VALUES (10),(20),(30)) t(valor)) TO ? (FORMAT PARQUET)",
                [str(path)],
            )
        content = path.read_bytes()

    class Upload:
        name = f"medicoes.{extension}"
        size = len(content)

        def getvalue(self) -> bytes:
            return content

    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: [Upload()])

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "A soma é 60.",
                        "sql": "SELECT sum(valor) AS total FROM raw.medicoes",
                    },
                )
            ]
        )

    monkeypatch.setattr(connection_panel, "build_model", lambda _: FunctionModel(respond))
    app = start(apps)
    app.button(key="open-import").click().run()
    assert not app.exception and app.title[0].value == "Dados"
    next(field for field in app.text_input if field.label == "Nome da base").set_value("Medições")
    next(field for field in app.text_input if field.label == "Identificador único").set_value(
        "medicoes"
    )
    app.button(key="preview-import").click().run()
    assert not app.exception
    app.button(key="confirm-import").click().run()
    assert not app.exception
    assert str(app.selectbox(key="selected_dataset").value).endswith("medicoes/dataset.toml")
    connect(app)
    app.button(key="ask-active-dataset").click().run()
    app.chat_input[0].set_value("Qual a soma das minhas medições?").run()
    assert not app.exception
    report = app.session_state["history"][-1].report
    assert report.evidence.rows == [(60,)] and not report.from_cache


def test_duplicate_dataset_titles_still_select_the_correct_database(apps: list[AppTest]) -> None:
    app = start(apps)
    workspace = app.session_state["visitor-workspace"]
    manifest = (workspace.settings.datasets_dir / "vendas/dataset.toml").resolve()
    manifest.write_text(
        f"version = 1\ntitle = {json.dumps(workspace.settings.dataset_title)}\nglossary = true\n"
    )
    app.run()
    options = app.selectbox(key="selected_dataset").options
    assert len(set(options)) == 3 and any("(vendas)" in label for label in options)
    app.selectbox(key="selected_dataset").select_index(2).run()
    assert app.selectbox(key="selected_dataset").value == str(manifest)
    app.button(key="open-import").click().run()
    app.button(key="ask-active-dataset").click().run()
    assert app.selectbox(key="selected_dataset").value == str(manifest)
    assert app.session_state["deps"].con.execute("SELECT count(*) FROM raw.orders").fetchall() == [
        (4,)
    ]


def test_visitors_are_isolated_and_can_erase_their_workspace(apps: list[AppTest]) -> None:
    first, second = start(apps), start(apps)
    a, b = first.session_state["visitor-workspace"], second.session_state["visitor-workspace"]
    assert a.folder.name != b.folder.name and a.model is None and b.model is None
    with pytest.raises(ValueError, match="não pertence"):
        visitor_resources(b, str(a.settings.olheiro_dataset))
    first.radio(key="portfolio-mode").set_value("Análises prontas").run()
    assert first.chat_input[0].disabled
    first.radio(key="portfolio-mode").set_value("Meu workspace").run()
    assert not first.chat_input[0].disabled
    root = Path(a.folder.name)
    first.button(key="end-workspace").click().run()
    assert not first.exception and not root.exists()
    assert Path(b.folder.name).exists() and second.session_state["visitor-workspace"].model is None
