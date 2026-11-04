"""Comando `olheiro-ask`: pergunta em português, resposta com evidência (SQL, tabela e gráfico).

Uso:
    uv run olheiro-ask "Quem foi o campeão de 2019?"
    uv run olheiro-ask --verbose "Qual região tem mais títulos?"
    uv run olheiro-ask --no-cache "Quem foi o campeão de 2019?"   (força ir ao modelo)

Se o agente quiser salvar um resultado (save_result), a CLI mostra o SQL e uma prévia e só
grava em workspace com a confirmação do usuário.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import duckdb
import pydantic_ai
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup
from pydantic_ai.models import Model

from olheiro.agent import (
    AgentDeps,
    AgentReport,
    PendingApproval,
    ask,
    build_model,
    describe_steps,
    resume,
)
from olheiro.cache import AnswerCache, ask_with_cache
from olheiro.charts import build_figure, save_figure
from olheiro.config import get_settings
from olheiro.conversation import Conversation
from olheiro.datasets import cache_revision, database_revision
from olheiro.db import WORKSPACE_CATALOG, WorkspaceInUseError, connect_agent
from olheiro.errors import explain_model_failure
from olheiro.semantic import load_glossary
from olheiro.telemetry import RunLog, tracked
from olheiro.tools import query_rows
from olheiro.tracing import setup_tracing

PREVIEW_ROWS = 5


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="olheiro-ask", description="Pergunte aos dados.")
    parser.add_argument("question", nargs="?", help="pergunta em português")
    parser.add_argument(
        "--chat", action="store_true", help="conversa local; /nova limpa e /sair encerra"
    )
    parser.add_argument("--verbose", action="store_true", help="mostra as chamadas de ferramenta")
    parser.add_argument("--no-cache", action="store_true", help="ignora respostas guardadas")
    args = parser.parse_args(argv)
    if not args.chat and not args.question:
        parser.error("informe uma pergunta ou use --chat.")
    return args


def format_report(report: AgentReport, chart_path: Path | None) -> str:
    """Resposta, insights, SQL, tabela de evidência, gráfico e custo da execução."""
    output = report.output
    sections = [
        output.answer if output.answerable else f"⚠ Sem dados para responder. {output.answer}"
    ]
    if output.insights:
        sections.append("Insights:\n" + "\n".join(f"  • {item}" for item in output.insights))
    if report.evidence is not None:
        sections.append(f"SQL:\n{output.sql}")
        sections.append(
            f"Evidência ({len(report.evidence.rows)} linhas):\n{report.evidence.to_markdown()}"
        )
    if chart_path is not None:
        sections.append(f"Gráfico: {chart_path}")
    usage = report.usage
    if report.from_cache:
        sections.append(f"── resposta do cache (gerada por {report.model_name}) · 0 requisições")
    else:
        sections.append(
            f"── {report.model_name} · {usage.requests} requisições · "
            f"{usage.tool_calls} ferramentas · {usage.input_tokens + usage.output_tokens} tokens"
        )
    return "\n\n".join(sections)


def confirm_save(pending: PendingApproval, con: duckdb.DuckDBPyConnection) -> bool:
    """Mostra o que o agente quer gravar, com prévia real, e pergunta ao usuário."""
    for save in pending.saves:
        print(f"\nO agente quer salvar {WORKSPACE_CATALOG}.{save.name}:\n{save.query}")
        try:
            preview = query_rows(con, save.query, max_rows=PREVIEW_ROWS)
            print(f"\nPrévia:\n{preview.to_markdown()}")
        except duckdb.Error as error:
            print(f"\nPrévia indisponível: {error}")
    try:
        return input("\nSalvar? [s/N] ").strip().lower() in {"s", "sim"}
    except EOFError:  # sem terminal interativo: na dúvida, não grava
        return False


def run_question(
    question: str,
    deps: AgentDeps,
    cache: AnswerCache | None,
    conversation: Conversation | None,
    model: Callable[[], Model],
    runs: RunLog,
    refresh_glossary: Callable[[], None],
) -> AgentReport:
    """Um turno, com construção do modelo só quando necessária e aprovação sempre atual."""
    outcome: AgentReport | PendingApproval
    with tracked(runs, question, "cli") as run:
        context_key = conversation.cache_key() if conversation is not None else None
        cached = cache.lookup(question, deps.con, context_key) if cache is not None else None
        if cached is not None:
            outcome = run.finish(cached)
            if conversation is not None:
                conversation.remember(question, cached)
        elif cache is not None:
            outcome = run.finish(
                ask_with_cache(
                    question,
                    deps,
                    cache,
                    model(),
                    conversation=conversation,
                )
            )
        else:
            outcome = run.finish(
                ask(
                    question,
                    deps,
                    model(),
                    message_history=conversation.messages() if conversation is not None else None,
                )
            )
    had_approval = isinstance(outcome, PendingApproval)
    while isinstance(outcome, PendingApproval):
        approved = confirm_save(outcome, deps.con)
        refresh_glossary()  # uma regra pode mudar enquanto o usuário decide
        with tracked(runs, question, "cli", phase="resume") as run:
            outcome = run.finish(resume(outcome, approved, deps, model()))
    if conversation is not None and (cache is None or had_approval):
        conversation.remember(question, outcome)
    return outcome


def print_report(report: AgentReport, exports_dir: Path, verbose: bool) -> None:
    chart_path = None
    if report.output.chart is not None and report.evidence is not None:
        chart_path = save_figure(build_figure(report.output.chart, report.evidence), exports_dir)
    if verbose:
        steps = describe_steps(report.messages) or ["(resposta do cache: nenhum passo)"]
        print("Passos do agente:\n" + "\n".join(f"  {step}" for step in steps) + "\n")
    print(format_report(report, chart_path))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    pydantic_ai.BANNER_ENABLED = False  # a CLI é dona da própria saída
    settings = get_settings()
    setup_tracing(settings)
    runs = RunLog.from_settings(settings)
    try:
        con = connect_agent(settings.duckdb_path, settings.workspace_path)
    except WorkspaceInUseError as error:
        sys.exit(str(error))
    with con:
        deps = AgentDeps(con)
        conversation = Conversation() if args.chat else None
        data_revision = database_revision(settings)
        active_model: Model | None = None

        def model() -> Model:
            nonlocal active_model
            if active_model is None:
                active_model = build_model(settings)
            return active_model

        def refresh_glossary() -> None:
            current = (
                settings.for_dataset(settings.olheiro_dataset)
                if settings.olheiro_dataset is not None
                else settings
            )
            deps.glossary = load_glossary(current.glossary_path)

        question = args.question
        if args.chat:
            print("Conversa local: /nova limpa o contexto; /sair encerra.")
        while True:
            if question is None:
                try:
                    question = input("\nVocê: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            if args.chat and question == "/sair":
                break
            if args.chat and question == "/nova":
                assert conversation is not None
                conversation.clear()
                print("Nova exploração iniciada.")
            elif question:
                try:
                    current = (
                        settings.for_dataset(settings.olheiro_dataset)
                        if settings.olheiro_dataset is not None
                        else settings
                    )
                    refresh_glossary()
                    namespace = cache_revision(current, data_revision)
                    if conversation is not None:
                        conversation.bind(deps, namespace)
                    cache = (
                        None if args.no_cache else AnswerCache(current.answer_cache_path, namespace)
                    )
                    report = run_question(
                        question,
                        deps,
                        cache,
                        conversation,
                        model,
                        runs,
                        refresh_glossary,
                    )
                except (AgentRunError, FallbackExceptionGroup, ValueError) as error:
                    message = f"Erro ao consultar o modelo. {explain_model_failure(error)}"
                    if not args.chat:
                        sys.exit(message)
                    print(message)
                else:
                    print_report(report, current.exports_dir, args.verbose)
            if not args.chat:
                break
            question = None
