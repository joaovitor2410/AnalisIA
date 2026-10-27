"""Página Perguntar: chat com o agente, aprovação de gravação e fixar no dashboard.

Cada pergunta é independente (sem memória da conversa): toda resposta traz a própria evidência.
"""

from dataclasses import dataclass

import duckdb
import streamlit as st
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup

from olheiro.agent import AgentDeps, AgentReport, PendingApproval, resume
from olheiro.cache import ask_with_cache
from olheiro.db import WORKSPACE_CATALOG
from olheiro.errors import explain_model_failure
from olheiro.telemetry import tracked
from olheiro.tools import query_rows
from olheiro.ui.components import show_report, show_table
from olheiro.ui.resources import AppResources, load_resources, session_deps

MAX_EXAMPLES = 6
PREVIEW_ROWS = 5


@dataclass
class ChatTurn:
    question: str
    report: AgentReport | None = None
    error: str | None = None
    pinned: bool = False


@dataclass
class PendingTurn:
    """Pergunta cuja execução pausou esperando o usuário aprovar uma gravação."""

    question: str
    approval: PendingApproval


def ask_page() -> None:
    resources = load_resources()
    deps = session_deps(resources)
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("model_questions", 0)

    st.title("Perguntar aos dados")
    st.caption(
        f"{resources.settings.dataset_title}. Cada resposta traz o SQL e a tabela que a sustentam."
    )
    show_examples(resources)
    if resources.settings.olheiro_demo_mode:
        st.caption("Demonstração: itens fixados e histórico ficam disponíveis só nesta sessão.")

    for index, turn in enumerate(st.session_state.history):
        show_turn(index, turn, resources)
    pending: PendingTurn | None = st.session_state.pending
    if pending is not None:
        show_approval(pending, resources, deps)

    typed = st.chat_input("Pergunte sobre a base selecionada", disabled=pending is not None)
    question = typed or st.session_state.pop("queued_question", None)
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"), st.spinner("Analisando os dados…"):
            handle_question(question, resources, deps)
        st.rerun()


def show_examples(resources: AppResources) -> None:
    """Perguntas já respondidas: viram atalhos que não gastam cota."""
    examples = resources.cache.questions()[:MAX_EXAMPLES]
    if examples:
        st.pills(
            "Perguntas prontas (respondidas do cache, sem gastar cota)",
            examples,
            key="example",
            on_change=queue_example,
        )


def queue_example() -> None:
    st.session_state.queued_question = st.session_state.example
    st.session_state.example = None  # desmarca, para o mesmo exemplo poder ser clicado de novo


def handle_question(question: str, resources: AppResources, deps: AgentDeps) -> None:
    """Responde e registra a execução (página Operação); falhas viram uma mensagem no chat."""
    try:
        with tracked(resources.runs, question, "app") as run:
            outcome = answer(question, resources, deps)
            if outcome is None:
                return
            run.finish(outcome)
    except (AgentRunError, FallbackExceptionGroup) as error:
        st.session_state.history.append(ChatTurn(question, error=explain_model_failure(error)))
        return
    record(question, outcome)


def answer(
    question: str, resources: AppResources, deps: AgentDeps
) -> AgentReport | PendingApproval | None:
    """Do cache, do modelo, ou None se o modelo não puder ser usado (o motivo vai para o chat)."""
    cached = resources.cache.lookup(question, deps.con)
    if cached is not None:  # do cache: não conta no limite da sessão
        return cached
    problem = model_unavailable(resources)
    if problem is not None:
        st.session_state.history.append(ChatTurn(question, error=problem))
        return None
    if resources.budget is not None and not resources.budget.take():
        st.session_state.history.append(
            ChatTurn(
                question,
                error="As novas perguntas desta demonstração foram esgotadas. "
                "As perguntas prontas continuam disponíveis.",
            )
        )
        return None
    st.session_state.model_questions += 1
    return ask_with_cache(question, deps, resources.cache, resources.model)


def model_unavailable(resources: AppResources) -> str | None:
    if resources.settings.olheiro_demo_mode and not resources.settings.olheiro_demo_model_enabled:
        return (
            "Novas perguntas estão desabilitadas nesta demonstração. Escolha uma pergunta pronta."
        )
    if resources.model is None:
        return f"Modelo indisponível: {resources.model_error}"
    limit = resources.settings.session_question_limit
    if limit is not None and st.session_state.model_questions >= limit:
        return (
            f"Você já usou as {limit} perguntas livres desta sessão. "
            "As perguntas prontas acima continuam disponíveis."
        )
    return None


def record(question: str, outcome: AgentReport | PendingApproval) -> None:
    if isinstance(outcome, PendingApproval):
        st.session_state.pending = PendingTurn(question, outcome)
    else:
        st.session_state.history.append(ChatTurn(question, outcome))


def show_turn(index: int, turn: ChatTurn, resources: AppResources) -> None:
    with st.chat_message("user"):
        st.markdown(turn.question)
    with st.chat_message("assistant"):
        report = turn.report
        if turn.error is not None or report is None:
            st.error(turn.error or "Sem resposta.", icon=":material/error:")
            return
        show_report(report, key=f"turn-{index}")
        if not (report.output.answerable and report.output.sql):
            return
        if turn.pinned:
            st.caption(":material/push_pin: No dashboard")
        elif st.button("Fixar no dashboard", key=f"pin-{index}", icon=":material/push_pin:"):
            resources.dashboard.pin(turn.question, report)
            turn.pinned = True
            st.toast("Fixado no dashboard", icon=":material/dashboard:")
            st.rerun()


def show_approval(pending: PendingTurn, resources: AppResources, deps: AgentDeps) -> None:
    """O agente pausou: mostra o que ele quer gravar (com prévia real) e espera a decisão."""
    with st.chat_message("user"):
        st.markdown(pending.question)
    with st.chat_message("assistant"):
        for save in pending.approval.saves:
            st.info(
                f"O agente quer salvar a tabela **{WORKSPACE_CATALOG}.{save.name}**.",
                icon=":material/save:",
            )
            st.code(save.query, language="sql")
            try:
                show_table(query_rows(deps.con, save.query, max_rows=PREVIEW_ROWS))
            except duckdb.Error as error:
                st.caption(f"Prévia indisponível: {error}")
        approve, deny = st.columns(2)
        if approve.button("Salvar", type="primary", key="approve", icon=":material/check:"):
            decide(True, resources, deps)
        if deny.button("Não salvar", key="deny", icon=":material/close:"):
            decide(False, resources, deps)


def decide(approved: bool, resources: AppResources, deps: AgentDeps) -> None:
    """Retoma a execução pausada com a decisão. O resultado não entra no cache."""
    pending: PendingTurn = st.session_state.pending
    st.session_state.pending = None
    try:
        with (
            tracked(resources.runs, pending.question, "app", phase="resume") as run,
            st.spinner("Continuando…"),
        ):
            outcome = run.finish(resume(pending.approval, approved, deps, resources.model))
    except (AgentRunError, FallbackExceptionGroup) as error:
        st.session_state.history.append(
            ChatTurn(pending.question, error=explain_model_failure(error))
        )
    else:
        record(pending.question, outcome)
    st.rerun()
