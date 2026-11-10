"""Controles de sessão da entrada hospedada; credenciais nunca entram em cache global."""

import streamlit as st
from pydantic import SecretStr

from olheiro.agent import build_model
from olheiro.visitor import VisitorWorkspace

WORKSPACE_MODE = "Meu workspace"
GUIDED_MODE = "Análises prontas"


def clear_analysis(reset_dataset: bool = True) -> None:
    deps = st.session_state.pop("deps", None)
    if deps is not None:
        deps.con.close()
    for key in (
        "history",
        "conversation",
        "pending",
        "queued_question",
        "question_draft",
        "example",
        "resource_connection",
        "demo_resources",
        "semantic_revision",
        "import_preview",
        "dashboard-search",
        "dashboard-kind",
    ):
        st.session_state.pop(key, None)
    if reset_dataset:
        st.session_state.pop("active_dataset", None)
        st.session_state.pop("selected_dataset", None)
        st.session_state.pop("next_dataset", None)


def connect_model(workspace: VisitorWorkspace) -> None:
    key = st.session_state.pop("session-api-key", "").strip()
    if not key:
        st.session_state["connection-error"] = "Informe uma chave Gemini."
        return
    model_name = st.session_state["session-model-name"]
    try:
        config = workspace.settings.model_copy(
            update={
                "google_api_key": SecretStr(key),
                "olheiro_model": model_name,
                "olheiro_fallback_model": None,
            }
        )
        model = build_model(config)
    except ValueError:
        st.session_state["connection-error"] = (
            "Não foi possível configurar a IA. Confira chave e modelo."
        )
    else:
        workspace.model, workspace.model_name = model, model_name
        st.session_state.pop("connection-error", None)
        clear_analysis(reset_dataset=False)


def disconnect_model(workspace: VisitorWorkspace) -> None:
    workspace.model = None
    st.session_state.pop("session-api-key", None)
    st.session_state.pop("connection-error", None)
    clear_analysis(reset_dataset=False)


def end_workspace(workspace: VisitorWorkspace) -> None:
    disconnect_model(workspace)
    clear_analysis()
    workspace.close()
    st.session_state.pop("visitor-workspace", None)
    st.session_state["portfolio-mode"] = GUIDED_MODE


def show_mode_selector() -> None:
    st.radio(
        "Modo de uso", [WORKSPACE_MODE, GUIDED_MODE], key="portfolio-mode", on_change=clear_analysis
    )


def show_connection(workspace: VisitorWorkspace) -> None:
    with st.expander("Conectar IA", expanded=workspace.model is None):
        st.caption(
            "Use sua chave Gemini nesta sessão. Perguntas e dados necessários à análise "
            "serão enviados ao Google. O consumo usa a cota/faturamento da sua chave."
        )
        st.link_button("Obter chave Gemini", "https://aistudio.google.com/apikey")
        if error := st.session_state.get("connection-error"):
            st.error(error)
        with st.form("session-model", clear_on_submit=True):
            st.text_input("Chave Gemini", type="password", key="session-api-key")
            models = ["google:gemini-3.8-flash", "google:gemini-3.5-flash-lite"]
            st.selectbox(
                "Modelo Gemini",
                models,
                index=models.index(workspace.model_name),
                key="session-model-name",
            )
            st.form_submit_button(
                "Usar chave nesta sessão", on_click=connect_model, args=(workspace,)
            )
        if workspace.model is not None:
            st.caption("Chave configurada. A API será verificada na primeira pergunta.")
            st.button(
                "Desconectar IA",
                key="disconnect-model",
                on_click=disconnect_model,
                args=(workspace,),
            )


def show_session_end(workspace: VisitorWorkspace) -> None:
    st.caption(
        "Seus uploads e análises pertencem a esta sessão e não persistem após seu encerramento."
    )
    st.button(
        "Encerrar sessão e apagar meus uploads",
        key="end-workspace",
        on_click=end_workspace,
        args=(workspace,),
    )
