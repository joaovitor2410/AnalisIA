"""Comando `olheiro-ask`: pergunta em português, resposta com evidência (SQL, tabela e gráfico).

Uso:
    uv run olheiro-ask "Quem foi o campeão de 2019?"
    uv run olheiro-ask --verbose "Qual região tem mais títulos?"

Se o agente quiser salvar um resultado (save_result), a CLI mostra o SQL e uma prévia e só
grava em workspace com a confirmação do usuário.
"""

import argparse
import sys
from pathlib import Path

import duckdb
import pydantic_ai
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup
from pydantic_ai.messages import ModelMessage, RetryPromptPart, ToolCallPart

from olheiro.agent import AgentDeps, AgentReport, PendingApproval, ask, build_model, resume
from olheiro.charts import build_figure, save_figure
from olheiro.config import get_settings
from olheiro.db import WORKSPACE_CATALOG, connect_agent
from olheiro.errors import explain_model_failure
from olheiro.semantic import load_glossary
from olheiro.tools import query_rows

PREVIEW_ROWS = 5


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="olheiro-ask", description="Pergunte aos dados.")
    parser.add_argument("question", help="pergunta em português")
    parser.add_argument("--verbose", action="store_true", help="mostra as chamadas de ferramenta")
    return parser.parse_args(argv)


def format_trace(messages: list[ModelMessage]) -> list[str]:
    """Uma linha por chamada de ferramenta e por retentativa pedida ao modelo."""
    lines = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                lines.append(f"  → {part.tool_name}({part.args_as_dict()})")
            elif isinstance(part, RetryPromptPart):
                lines.append(f"  ↻ retentativa: {str(part.content).splitlines()[0][:200]}")
    return lines


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
    sections.append(
        f"── {report.model_name} · {usage.requests} requisições · {usage.tool_calls} ferramentas · "
        f"{usage.input_tokens + usage.output_tokens} tokens"
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
    with connect_agent(settings.duckdb_path, settings.workspace_path) as con:
        deps = AgentDeps(con, glossary)
        try:
            outcome = ask(args.question, deps, model)
            while isinstance(outcome, PendingApproval):
                outcome = resume(outcome, confirm_save(outcome, con), deps, model)
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
        print("Passos do agente:\n" + "\n".join(format_trace(report.messages)) + "\n")
    print(format_report(report, chart_path))
