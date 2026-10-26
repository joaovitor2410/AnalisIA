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
from pathlib import Path

import duckdb
import pydantic_ai
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup

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
from olheiro.db import WORKSPACE_CATALOG, WorkspaceInUseError, connect_agent
from olheiro.errors import explain_model_failure
from olheiro.semantic import load_glossary
from olheiro.telemetry import RunLog, tracked
from olheiro.tools import query_rows
from olheiro.tracing import setup_tracing

PREVIEW_ROWS = 5


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="olheiro-ask", description="Pergunte aos dados.")
    parser.add_argument("question", help="pergunta em português")
    parser.add_argument("--verbose", action="store_true", help="mostra as chamadas de ferramenta")
    parser.add_argument("--no-cache", action="store_true", help="ignora respostas guardadas")
    return parser.parse_args(argv)


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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    pydantic_ai.BANNER_ENABLED = False  # a CLI é dona da própria saída
    settings = get_settings()
    try:
        model = build_model(settings)
    except ValueError as error:
        sys.exit(str(error))

    glossary = load_glossary(settings.glossary_path)
    setup_tracing(settings)
    runs = RunLog(settings.runs_path)
    try:
        con = connect_agent(settings.duckdb_path, settings.workspace_path)
    except WorkspaceInUseError as error:
        sys.exit(str(error))
    with con:
        deps = AgentDeps(con, glossary)
        try:
            with tracked(runs, args.question, "cli") as run:
                if args.no_cache:
                    outcome = run.finish(ask(args.question, deps, model))
                else:
                    cache = AnswerCache(settings.answer_cache_path)
                    outcome = run.finish(ask_with_cache(args.question, deps, cache, model))
            while isinstance(outcome, PendingApproval):
                approved = confirm_save(outcome, con)  # o tempo de decisão não entra na medida
                with tracked(runs, args.question, "cli", phase="resume") as run:
                    outcome = run.finish(resume(outcome, approved, deps, model))
        except (AgentRunError, FallbackExceptionGroup) as error:
            # Falha da API (cota, 503 em todos os modelos) ou modelo que esgotou as retentativas.
            sys.exit(f"Erro ao consultar o modelo. {explain_model_failure(error)}")

    report = outcome
    chart_path = None
    if report.output.chart is not None and report.evidence is not None:
        chart_path = save_figure(
            build_figure(report.output.chart, report.evidence), settings.exports_dir
        )

    if args.verbose:
        steps = describe_steps(report.messages) or ["(resposta do cache: nenhum passo)"]
        print("Passos do agente:\n" + "\n".join(f"  {step}" for step in steps) + "\n")
    print(format_report(report, chart_path))
