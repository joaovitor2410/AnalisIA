"""A demo gratuita executa SQL curado e nunca usa chaves ou bases pessoais."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from olheiro.config import PROJECT_ROOT, get_settings, has_settings_scope
from olheiro.portfolio import portfolio_settings
from olheiro.ui.resources import shared_resources


@pytest.fixture(autouse=True)
def clean_portfolio_resources() -> Iterator[None]:
    shared_resources.clear()
    portfolio_settings.clear()
    yield
    shared_resources.clear()
    portfolio_settings.clear()


def test_free_portfolio_ignores_personal_configuration_and_all_examples_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from olheiro import portfolio
    from olheiro.ui import resources

    personal = tmp_path / "personal.duckdb"
    personal.write_bytes(b"arquivo pessoal preservado")
    monkeypatch.setenv("DUCKDB_PATH", str(personal))
    monkeypatch.setenv("GOOGLE_API_KEY", "nao-usar-esta-chave")
    monkeypatch.setenv("OLHEIRO_DEMO_MODEL_ENABLED", "true")
    monkeypatch.setenv("OLHEIRO_DATASET", str(tmp_path / "privado/dataset.toml"))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A demo gratuita tentou construir o modelo.")

    monkeypatch.setattr(resources, "build_model", forbidden)
    settings = portfolio.portfolio_settings()
    assert settings.google_api_key is None and settings.olheiro_dataset is None
    assert settings.olheiro_demo_mode and not settings.olheiro_demo_model_enabled
    assert settings.duckdb_path != personal
    app = AppTest.from_file(str(PROJECT_ROOT / "portfolio_app.py"), default_timeout=20).run()
    assert not app.exception
    questions = app.pills(key="example").options
    assert len(questions) == 10
    for question in questions:
        app.pills(key="example").set_value(question).run()
        assert not app.exception
        report = app.session_state["history"][-1].report
        assert report is not None and report.from_cache and report.usage.requests == 0
    assert personal.read_bytes() == b"arquivo pessoal preservado"
    assert not has_settings_scope()
    monkeypatch.delenv("OLHEIRO_DATASET")
    assert get_settings().duckdb_path == personal  # o perfil pessoal não foi substituído


def test_two_portfolio_visitors_have_private_dashboards() -> None:
    path = str(PROJECT_ROOT / "portfolio_app.py")
    first = AppTest.from_file(path, default_timeout=20).run()
    question = first.pills(key="example").options[0]
    first.pills(key="example").set_value(question).run()
    first.button(key="pin-0").click().run()
    assert len(first.session_state["demo_resources"].dashboard.read().items) == 1
    second = AppTest.from_file(path, default_timeout=20).run()
    assert not second.exception
    assert second.session_state["demo_resources"].dashboard.read().items == []
    assert second.session_state["history"] == []
