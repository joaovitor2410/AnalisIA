"""Recursos do app: criados uma vez por processo e compartilhados entre as sessões.

A conexão blindada é uma só; cada sessão (visitante) usa o próprio cursor, como o DuckDB
pede para uso com várias threads.
Na demo, cache e dashboard ficam em memória por sessão; o workspace pessoal não é aberto.
"""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import duckdb
import pydantic_ai
import streamlit as st
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from olheiro.agent import AgentDeps, build_model
from olheiro.cache import AnswerCache
from olheiro.config import PROJECT_ROOT, Settings, get_settings
from olheiro.dashboard import DashboardStore
from olheiro.datasets import cache_revision, dataset_identity
from olheiro.db import connect_agent, session_cursor
from olheiro.demo import QuestionBudget, load_examples
from olheiro.semantic import Glossary, load_glossary
from olheiro.telemetry import RunLog
from olheiro.tracing import setup_tracing


@dataclass(frozen=True)
class AppResources:
    settings: Settings
    con: duckdb.DuckDBPyConnection
    glossary: Glossary
    cache: AnswerCache
    dashboard: DashboardStore
    runs: RunLog
    model: Model | None  # None sem chave: o app ainda mostra dados, dashboard e cache
    model_error: str | None
    budget: QuestionBudget | None = None


@st.cache_resource(show_spinner=False)
def shared_resources(dataset_path: str | None = None) -> AppResources:
    pydantic_ai.BANNER_ENABLED = False
    settings = get_settings()
    if dataset_path is not None:
        # O provider OpenTelemetry é global por processo. Registros ficam por base;
        # traces da interface usam o destino comum da instância, inclusive após a troca.
        trace_path = settings.traces_path
        settings = settings.for_dataset(Path(dataset_path)).model_copy(
            update={"traces_path": trace_path}
        )
    if settings.olheiro_demo_mode:
        # Exceções em spans de bibliotecas podem conter argumentos mesmo sem payloads.
        # Na demo ficam apenas métricas locais com conteúdo omitido, sem traces detalhados.
        settings = settings.model_copy(
            update={"olheiro_trace_content": False, "olheiro_tracing": "off"}
        )
    setup_tracing(settings)
    if settings.olheiro_demo_mode and not settings.olheiro_demo_model_enabled:
        model, model_error = None, "Novas perguntas estão desabilitadas nesta demonstração."
    else:
        try:
            model, model_error = build_model(settings), None
        except ValueError as error:
            model, model_error = None, str(error)
    glossary = load_glossary(settings.glossary_path)
    con = connect_agent(
        settings.duckdb_path, None if settings.olheiro_demo_mode else settings.workspace_path
    )
    try:
        demo = settings.olheiro_demo_mode
        cache = (
            load_examples(settings.demo_examples_path, con)
            if demo
            else AnswerCache(settings.answer_cache_path, cache_revision(settings))
        )
        return AppResources(
            settings=settings,
            con=con,
            glossary=glossary,
            cache=cache,
            dashboard=DashboardStore(
                None if demo else settings.dashboard_path,
                None if demo else dataset_identity(settings),
                allow_legacy=settings.duckdb_path == PROJECT_ROOT / "data/olheiro.duckdb",
            ),
            runs=RunLog(settings.runs_path, include_content=not demo),
            model=model,
            model_error=model_error,
            budget=QuestionBudget(settings.olheiro_demo_total_question_limit) if demo else None,
        )
    except Exception:
        con.close()
        raise


def load_resources() -> AppResources:
    """Dados públicos compartilhados; cache e painel privados para cada sessão da demo."""
    shared = shared_resources(st.session_state.get("selected_dataset"))
    previous = st.session_state.get("resource_connection")
    if previous is not shared.con:
        old_deps = st.session_state.pop("deps", None)
        if old_deps is not None:
            old_deps.con.close()
        for key in (
            "history",
            "pending",
            "queued_question",
            "question_draft",
            "example",
            "demo_resources",
            "dashboard-search",
            "dashboard-kind",
        ):
            st.session_state.pop(key, None)
        st.session_state.resource_connection = shared.con
    if not shared.settings.olheiro_demo_mode:
        return shared
    if "demo_resources" not in st.session_state:
        cache = AnswerCache(None)
        with cache.file.update() as target:
            target.answers = shared.cache.read().answers
        st.session_state.demo_resources = replace(
            shared, cache=cache, dashboard=DashboardStore(None)
        )
    return cast(AppResources, st.session_state.demo_resources)


def session_deps(resources: AppResources) -> AgentDeps:
    """Dependências do agente para esta sessão (um cursor próprio sobre a conexão comum)."""
    if "deps" not in st.session_state:
        demo = resources.settings.olheiro_demo_mode
        st.session_state.deps = AgentDeps(
            session_cursor(resources.con),
            resources.glossary,
            allow_saves=not demo,
            usage_limits=UsageLimits(request_limit=6, tool_calls_limit=12) if demo else None,
        )
    return st.session_state.deps
