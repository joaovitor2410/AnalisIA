"""Recursos do app: criados uma vez por processo e compartilhados entre as sessões.

A conexão blindada é uma só; cada sessão (visitante) usa o próprio cursor, como o DuckDB
pede para uso com várias threads.
"""

from dataclasses import dataclass

import duckdb
import pydantic_ai
import streamlit as st
from pydantic_ai.models import Model

from olheiro.agent import AgentDeps, build_model
from olheiro.cache import AnswerCache
from olheiro.config import Settings, get_settings
from olheiro.dashboard import DashboardStore
from olheiro.db import connect_agent, session_cursor
from olheiro.semantic import Glossary, load_glossary


@dataclass(frozen=True)
class AppResources:
    settings: Settings
    con: duckdb.DuckDBPyConnection
    glossary: Glossary
    cache: AnswerCache
    dashboard: DashboardStore
    model: Model | None  # None sem chave: o app ainda mostra dados, dashboard e cache
    model_error: str | None


@st.cache_resource(show_spinner=False)
def load_resources() -> AppResources:
    pydantic_ai.BANNER_ENABLED = False
    settings = get_settings()
    try:
        model, model_error = build_model(settings), None
    except ValueError as error:
        model, model_error = None, str(error)
    return AppResources(
        settings=settings,
        con=connect_agent(settings.duckdb_path, settings.workspace_path),
        glossary=load_glossary(settings.glossary_path),
        cache=AnswerCache(settings.answer_cache_path),
        dashboard=DashboardStore(settings.dashboard_path),
        model=model,
        model_error=model_error,
    )


def session_deps(resources: AppResources) -> AgentDeps:
    """Dependências do agente para esta sessão (um cursor próprio sobre a conexão comum)."""
    if "deps" not in st.session_state:
        st.session_state.deps = AgentDeps(session_cursor(resources.con), resources.glossary)
    return st.session_state.deps
