"""AnalisIA no navegador.

Rodar:
    uv run streamlit run src/olheiro/app.py
"""

from collections import Counter

import streamlit as st

from olheiro.config import get_settings, has_settings_scope
from olheiro.datasets import discover_datasets
from olheiro.db import WorkspaceInUseError
from olheiro.ui.ask_page import ask_page
from olheiro.ui.connection_panel import show_connection, show_mode_selector, show_session_end
from olheiro.ui.dashboard_page import dashboard_page
from olheiro.ui.data_page import data_page
from olheiro.ui.ops_page import ops_page
from olheiro.ui.presentation import apply_identity, connection_status
from olheiro.ui.resources import load_resources
from olheiro.visitor import current_workspace


def select_dataset() -> None:
    # Estado durável separado do widget, que o Streamlit recria ao mudar de página.
    st.session_state.active_dataset = st.session_state.selected_dataset
    st.session_state.pop("import_preview", None)


def show_sidebar() -> None:
    settings = get_settings()
    if has_settings_scope():
        show_mode_selector()
    st.caption("SEU ESPAÇO DE ANÁLISE")
    if not settings.olheiro_demo_mode:
        datasets = discover_datasets(settings.datasets_dir)
        if settings.olheiro_dataset:
            datasets.pop(settings.olheiro_dataset, None)
        options = [None, *map(str, datasets)]
        counts = Counter([settings.dataset_title, *datasets.values()])
        labels: dict[str | None, str] = {
            str(path): f"{title} ({path.parent.name})" if counts[title] > 1 else title
            for path, title in datasets.items()
        }
        labels[None] = (
            f"{settings.dataset_title} (base inicial)"
            if counts[settings.dataset_title] > 1
            else settings.dataset_title
        )

        def dataset_label(value: str | None) -> str:
            # Streamlit serializa o valor usando o rótulo. Preserve também rótulos já formatados.
            if value in labels:
                return labels[value]
            return (
                value if value is not None and value in labels.values() else settings.dataset_title
            )

        if "next_dataset" in st.session_state:
            st.session_state.active_dataset = st.session_state.pop("next_dataset")
        if "active_dataset" not in st.session_state:
            st.session_state.active_dataset = st.session_state.get("selected_dataset")
        selected = st.session_state.active_dataset
        if selected not in options:
            st.session_state.active_dataset = next(
                (value for value, label in labels.items() if label == selected), None
            )
        st.session_state.selected_dataset = st.session_state.active_dataset
        st.selectbox(
            "Base de dados",
            options,
            key="selected_dataset",
            format_func=dataset_label,
            on_change=select_dataset,
            help="Escolha uma base. Importe novos arquivos na página Dados.",
        )
        if st.button("Importar CSV/Parquet", key="open-import"):
            st.session_state["open-data-page"] = True
    resources = load_resources()
    st.caption(f"Base ativa: {resources.settings.dataset_title}")
    workspace = current_workspace()
    if workspace is not None:
        show_connection(workspace)
        show_session_end(workspace)
    demo = resources.settings.olheiro_demo_mode
    if demo:
        st.caption("Modo demonstração · seu dashboard pertence a esta sessão")
    if demo and not resources.settings.olheiro_demo_model_enabled:
        connection_status("Exemplos prontos para explorar", configured=True)
        st.info("Escolha uma pergunta pronta para explorar os dados.")
    elif resources.model is None:
        connection_status("IA não configurada", configured=False)
        if workspace is not None:
            st.caption("Use Conectar IA para habilitar perguntas livres.")
        else:
            with st.expander("Configurar o modelo"):
                st.warning(
                    f"Modelo indisponível: {resources.model_error}", icon=":material/warning:"
                )
                st.caption("A exploração de dados e o dashboard continuam disponíveis.")
    else:
        connection_status("IA configurada", configured=True)
        with st.expander("Detalhes do ambiente"):
            st.caption(f"Modelo: {resources.settings.olheiro_model}")
            st.caption("As perguntas são processadas pelo provedor de IA configurado.")
    limit = resources.settings.session_question_limit
    if limit is not None and (not demo or resources.settings.olheiro_demo_model_enabled):
        used = st.session_state.get("model_questions", 0)
        progress = min(used / limit, 1.0) if limit else 1.0
        st.progress(progress, text=f"Perguntas livres: {used} de {limit}")
    st.divider()
    st.caption("Pergunte. Confira a evidência. Transforme em descoberta.")
    st.caption("AnalisIA · Inteligência com clareza")


st.set_page_config(page_title="AnalisIA", page_icon="✦", layout="wide")
apply_identity()
if has_settings_scope():
    if current_workspace() is not None:
        st.info(
            "Seu workspace: escolha uma base ou importe CSV/Parquet em Dados. "
            "Para perguntas livres, conecte sua chave em Conectar IA. "
            "Seus dados ficam isolados nesta sessão."
        )
    else:
        st.info(
            "Demonstração gratuita com dados fictícios e análises prontas. "
            "Para importar dados e fazer novas perguntas, selecione Meu workspace na barra lateral."
        )
    st.link_button("Código e execução local", "https://github.com/joaovitor2410/AnalisIA")
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
navigation = st.navigation(pages)
if st.session_state.pop("open-data-page", False):
    st.switch_page(pages[2])
if st.session_state.pop("open-ask-page", False):
    st.switch_page(pages[0])
navigation.run()
