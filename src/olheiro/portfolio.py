"""Entrada pública gratuita: dados fictícios e SQL curado, sem acesso ao modelo."""

import atexit
import runpy
import shutil
from pathlib import Path
from tempfile import mkdtemp

import streamlit as st
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from olheiro.config import Settings, resource_path, settings_scope
from olheiro.launcher import ensure_database


class PortfolioSettings(Settings):
    """A entrada pública ignora .env, ambiente e arquivos de segredos pessoais."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


@st.cache_resource(show_spinner=False)
def portfolio_settings() -> Settings:
    """Estado descartável por processo; nenhuma configuração pessoal habilita geração."""
    root = Path(mkdtemp(prefix="analisia-portfolio-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    settings = PortfolioSettings(
        google_api_key=None,
        anthropic_api_key=None,
        olheiro_fallback_model=None,
        olheiro_demo_mode=True,
        olheiro_demo_model_enabled=False,
        olheiro_session_question_limit=0,
        olheiro_demo_total_question_limit=0,
        olheiro_dataset=None,
        olheiro_workspace_override=None,
        duckdb_path=root / "source.duckdb",
        workspace_path=root / "workspace.duckdb",
        raw_data_dir=resource_path("examples/datasets/portfolio"),
        glossary_path=resource_path("examples/datasets/portfolio/glossary.toml"),
        import_options_path=resource_path("examples/datasets/portfolio/import-options.json"),
        demo_examples_path=resource_path("demo/portfolio.toml"),
        dataset_title="Loja demonstrativa · dados sintéticos",
        datasets_dir=root / "datasets",
        answer_cache_path=root / "cache.json",
        dashboard_path=root / "dashboard.json",
        runs_path=root / "runs.jsonl",
        traces_path=root / "traces.jsonl",
        exports_dir=root / "exports",
        olheiro_demo_budget_path=root / "budget.json",
        olheiro_tracing="off",
        olheiro_trace_content=False,
    )
    ensure_database(settings)
    return settings


def run() -> None:
    with settings_scope(portfolio_settings()):
        runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
