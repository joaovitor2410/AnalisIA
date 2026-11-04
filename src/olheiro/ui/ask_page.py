"""Página Perguntar: chat com o agente, aprovação de gravação e fixar no dashboard.

Continuações usam contexto limitado da sessão; toda resposta traz a própria evidência.
"""

from dataclasses import dataclass
from html import escape

import duckdb
import streamlit as st
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup

from olheiro.agent import AgentDeps, AgentReport, ApprovalContextError, PendingApproval, resume
from olheiro.cache import ask_with_cache, normalize_question
from olheiro.db import WORKSPACE_CATALOG
from olheiro.errors import explain_model_failure
from olheiro.semantic import columns_by_table
from olheiro.telemetry import tracked
from olheiro.tools import query_rows
from olheiro.ui.components import show_report, show_table
from olheiro.ui.presentation import context_strip, page_intro
from olheiro.ui.resources import AppResources, load_resources, session_conversation, session_deps

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
    conversation = session_conversation(resources, deps)

    page_intro(
        "Seu próximo insight começa aqui",
        "Perguntar aos dados",
        "Converse com a AnalisIA. Descubra respostas em português e confira os dados da análise.",
    )
    tables = columns_by_table(deps.con, "schema_name", "raw")
    context_strip(resources.settings.dataset_title, len(tables), sum(map(len, tables.values())))
    pending: PendingTurn | None = st.session_state.pending
    if not st.session_state.history:
        show_welcome(resources, list(tables), pending is not None)
    else:
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.button(
                "Nova exploração",
                key="new-exploration",
                icon=":material/add_comment:",
                on_click=clear_history,
                disabled=pending is not None,
                help="Limpa o histórico e o contexto desta sessão. Itens fixados permanecem.",
            )
    show_examples(resources)
    if resources.settings.olheiro_demo_mode:
        st.caption("Demonstração: itens fixados e histórico ficam disponíveis só nesta sessão.")

    for index, turn in enumerate(st.session_state.history):
        show_turn(index, turn, resources)
    show_draft(pending is not None)
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
    st.caption(
        f"Continue a análise com outra pergunta. Contexto: {conversation.turn_count} de até "
        f"{conversation.max_turns} análises recentes. Nova exploração limpa esse contexto."
    )
    if conversation.truncated:
        st.caption(
            "O contexto foi limitado por tamanho ou quantidade de análises. "
            "Repita filtros, períodos ou referências antigas quando necessário."
        )


def show_welcome(resources: AppResources, tables: list[str], pending: bool) -> None:
    st.html(
        '<section class="ai-hero"><div class="ai-label">'
        "DADOS EM PERGUNTAS. PERGUNTAS EM DESCOBERTAS.</div>"
        "<p>Uma visão geral, uma comparação ou aquele número que faltava. "
        "Comece com uma pergunta: a AnalisIA reúne a análise "
        "e as evidências para você conferir.</p>"
        '<div class="ai-steps"><span><b>01</b> Faça uma pergunta</span>'
        "<span><b>02</b> Explore as evidências</span><span><b>03</b> Monte seu dashboard</span>"
        "</div></section>"
    )
    if (
        resources.settings.olheiro_demo_mode
        or resources.model is None
        or not tables
        or pending
        or st.session_state.get("question_draft")
    ):
        return
    table = 'raw."' + tables[0].replace('"', '""') + '"'
    starters = [
        (
            "overview",
            "↗",
            "Uma visão geral",
            "Entenda o tamanho e as possibilidades da base.",
            f"Faça um resumo da tabela {table}: quantidade de registros, colunas disponíveis "
            "e possibilidades de análise. Sustente as contagens com SQL.",
        ),
        (
            "quality",
            "◇",
            "Conhecer a qualidade",
            "Investigue valores ausentes antes de analisar.",
            f"Analise os valores ausentes da tabela {table}. Mostre a contagem de nulos por coluna "
            "e a quantidade total de registros, com evidência SQL.",
        ),
        (
            "patterns",
            "≋",
            "Encontrar padrões",
            "Explore categorias e frequências nos dados.",
            f"Explore as categorias mais frequentes na tabela {table}. Confira tipos e valores "
            "antes de escolher uma coluna e mostre as frequências com SQL.",
        ),
    ]
    st.caption("ESCOLHA UM PONTO DE PARTIDA · você pode editar antes de enviar")
    for column, (key, icon, title, description, question) in zip(
        st.columns(3), starters, strict=True
    ):
        with column, st.container(border=True, key=f"starter-{key}"):
            st.html(
                f'<span class="ai-card-icon" aria-hidden="true">{icon}</span>'
                f'<p class="ai-card-title">{escape(title)}</p>'
                f'<p class="ai-card-copy">{escape(description)}</p>'
            )
            st.button(
                "Preparar pergunta",
                key=f"suggest-{key}",
                width="stretch",
                on_click=prepare_question,
                args=(question,),
            )


def prepare_question(question: str) -> None:
    """Sugestão vira rascunho editável; nenhuma requisição é feita antes do envio."""
    st.session_state.question_draft = question


def submit_draft() -> None:
    question = st.session_state.get("question_draft", "").strip()
    if question:
        st.session_state.queued_question = question
    st.session_state.question_draft = ""


def clear_history() -> None:
    st.session_state.history = []
    st.session_state.question_draft = ""
    st.session_state.pop("queued_question", None)
    conversation = st.session_state.get("conversation")
    if conversation is not None:
        conversation.clear()


def discard_draft() -> None:
    st.session_state.question_draft = ""


def show_draft(pending: bool) -> None:
    if not st.session_state.get("question_draft"):
        return
    with st.container(border=True, key="question-draft"):
        st.caption("SUA PERGUNTA · revise e envie quando estiver pronta")
        st.text_area("Edite sua pergunta", key="question_draft", disabled=pending, height=110)
        st.button(
            "Analisar pergunta",
            key="send-draft",
            type="primary",
            icon=":material/arrow_upward:",
            on_click=submit_draft,
            disabled=pending or not st.session_state.question_draft.strip(),
        )
        st.button(
            "Escolher outra sugestão",
            key="discard-draft",
            type="tertiary",
            on_click=discard_draft,
            disabled=pending,
        )
        st.caption("O envio usa o modelo configurado e conta no limite da sessão, se houver.")


def show_examples(resources: AppResources) -> None:
    """Perguntas já respondidas: viram atalhos que não gastam cota."""
    examples = resources.cache.questions()[:MAX_EXAMPLES]
    if examples:
        st.pills(
            "Perguntas prontas (respondidas do cache, sem gastar cota)",
            examples,
            key="example",
            on_change=queue_example,
            disabled=st.session_state.get("pending") is not None,
        )
        st.caption("Perguntas prontas, selecionadas ou digitadas, iniciam um novo contexto.")


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
    conversation = session_conversation(resources, deps)
    if normalize_question(question) in {
        normalize_question(example) for example in resources.cache.questions()
    }:
        # Um atalho curado é uma análise independente, inclusive quando digitado.
        conversation.clear()
    cached = resources.cache.lookup(question, deps.con, conversation.cache_key())
    if cached is not None:  # do cache: não conta no limite da sessão
        conversation.remember(question, cached)
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
    return ask_with_cache(
        question, deps, resources.cache, resources.model, conversation=conversation
    )


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
    except (AgentRunError, FallbackExceptionGroup, ApprovalContextError) as error:
        st.session_state.history.append(
            ChatTurn(pending.question, error=explain_model_failure(error))
        )
    else:
        if isinstance(outcome, AgentReport):
            session_conversation(resources, deps).remember(pending.question, outcome)
        record(pending.question, outcome)
    st.rerun()
