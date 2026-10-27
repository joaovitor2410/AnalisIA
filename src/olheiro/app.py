"""Olheiro no navegador.

Rodar:
    uv run streamlit run src/olheiro/app.py
"""

import streamlit as st

from olheiro.config import get_settings
from olheiro.datasets import discover_datasets
from olheiro.db import WorkspaceInUseError
from olheiro.ui.ask_page import ask_page
from olheiro.ui.dashboard_page import dashboard_page
from olheiro.ui.data_page import data_page
from olheiro.ui.ops_page import ops_page
from olheiro.ui.resources import load_resources


def show_sidebar() -> None:
    settings = get_settings()
    if not settings.olheiro_demo_mode:
        datasets = discover_datasets(settings.datasets_dir)
        if settings.olheiro_dataset:
            datasets.pop(settings.olheiro_dataset, None)
        options = [None, *map(str, datasets)]
        labels = {str(path): title for path, title in datasets.items()}
        if "next_dataset" in st.session_state:
            st.session_state.selected_dataset = st.session_state.pop("next_dataset")
        if st.session_state.get("selected_dataset") not in options:
            st.session_state.selected_dataset = None
        st.selectbox(
            "Base de dados",
            options,
            key="selected_dataset",
            format_func=lambda value: labels.get(value, settings.dataset_title),
        )
    resources = load_resources()
    st.markdown("### Olheiro")
    st.caption(
        "Analista de dados com IA: pergunte em português e receba a resposta com o SQL, "
        "a tabela e o gráfico que a sustentam."
    )
    st.caption(f"Base ativa: {resources.settings.dataset_title}")
    demo = resources.settings.olheiro_demo_mode
    if demo:
        st.caption("Modo demonstração · seu dashboard pertence a esta sessão")
    if demo and not resources.settings.olheiro_demo_model_enabled:
        st.info("Escolha uma pergunta pronta para explorar os dados.")
    elif resources.model is None:
        st.warning(f"Modelo indisponível: {resources.model_error}", icon=":material/warning:")
    else:
        st.caption(f"Modelo: {resources.settings.olheiro_model}")
    limit = resources.settings.session_question_limit
    if limit is not None and (not demo or resources.settings.olheiro_demo_model_enabled):
        used = st.session_state.get("model_questions", 0)
        progress = min(used / limit, 1.0) if limit else 1.0
        st.progress(progress, text=f"Perguntas livres: {used} de {limit}")


st.set_page_config(page_title="Olheiro", page_icon=":material/query_stats:", layout="wide")
try:
    with st.sidebar:
        show_sidebar()
except WorkspaceInUseError as error:
    st.title("Workspace em uso")
    st.error(str(error), icon=":material/lock:")
    if st.button("Tentar novamente", key="retry-workspace"):
        st.rerun()
    st.stop()
pages = [
    st.Page(ask_page, title="Perguntar", icon=":material/chat:", default=True),
    st.Page(dashboard_page, title="Dashboard", icon=":material/dashboard:"),
    st.Page(data_page, title="Dados", icon=":material/table_chart:"),
]
if not load_resources().settings.olheiro_demo_mode:
    pages.append(st.Page(ops_page, title="Operação", icon=":material/monitoring:"))
st.navigation(pages).run()
