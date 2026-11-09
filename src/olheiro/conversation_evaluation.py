"""Avaliação de conversas completas; validação padrão é offline e não lê chaves."""

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from olheiro.agent import AgentDeps, AgentReport, ask, google_model
from olheiro.charts import ChartSpec, check_chart
from olheiro.config import PROJECT_ROOT, Settings, resource_path
from olheiro.conversation import Conversation
from olheiro.errors import explain_model_failure
from olheiro.eval_suites import SUITES, suite_database
from olheiro.evaluation import confirm, estimated_cost, evidence_matches, jsonable
from olheiro.pricing import cost_usd
from olheiro.sql_guard import check_query
from olheiro.tools import query_rows


class Turn(BaseModel):
    question: str
    answerable: bool = True
    sql: str | None = None
    chart_kinds: list[Literal["bar", "line", "metric"]] = Field(default_factory=list)


class Scenario(BaseModel):
    name: str
    suite: str
    turns: list[Turn] = Field(min_length=1, max_length=6)


class Scenarios(BaseModel):
    cases: list[Scenario]


class TurnResult(BaseModel):
    question: str
    checks: dict[str, bool]
    answer: str = ""
    sql: str | None = None
    chart: ChartSpec | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[object]] = Field(default_factory=list)
    requests: int = 0
    tokens: int = 0
    cost_usd: float | None = None
    seconds: float = 0
    error: str | None = None


class ScenarioResult(BaseModel):
    name: str
    suite: str
    turns: list[TurnResult]


def load_scenarios() -> Scenarios:
    with resource_path("evals/conversations.toml").open("rb") as file:
        return Scenarios.model_validate(tomllib.load(file))


def validate_scenarios(scenarios: Scenarios) -> None:
    names: set[str] = set()
    for case in scenarios.cases:
        if case.name in names or case.suite not in SUITES:
            raise ValueError("Cenário duplicado ou suíte desconhecida.")
        names.add(case.name)
        with suite_database(SUITES[case.suite]) as (con, _):
            for turn in case.turns:
                if turn.answerable != bool(turn.sql):
                    raise ValueError("Respostas precisam de gabarito; recusas não devem tê-lo.")
                if turn.sql:
                    check_query(turn.sql)
                    result = query_rows(con, turn.sql, max_rows=51)
                    if result.truncated or len(result.rows) > 50:
                        raise ValueError("Gabarito excede a evidência exibida.")


def evaluate_scenarios(scenarios: Scenarios, model: Model, model_id: str) -> list[ScenarioResult]:
    validate_scenarios(scenarios)
    results = []
    for case in scenarios.cases:
        turns = []
        with suite_database(SUITES[case.suite]) as (con, glossary):
            deps = AgentDeps(
                con,
                glossary,
                allow_saves=False,
                usage_limits=UsageLimits(request_limit=6, tool_calls_limit=12),
            )
            conversation = Conversation()
            conversation.bind(deps)
            for turn in case.turns:
                usage, started = RunUsage(), perf_counter()
                result = TurnResult(question=turn.question, checks={"comportamento": False})
                try:
                    report = ask(
                        turn.question,
                        deps,
                        model,
                        message_history=conversation.messages(),
                        usage=usage,
                    )
                    if not isinstance(report, AgentReport):
                        raise ValueError("Uma avaliação de leitura não pode pedir aprovação.")
                    output = report.output
                    result.answer, result.sql, result.chart = (
                        output.answer,
                        output.sql,
                        output.chart,
                    )
                    result.checks["comportamento"] = output.answerable == turn.answerable
                    if report.evidence is not None:
                        result.columns = report.evidence.columns
                        result.rows = [[jsonable(v) for v in row] for row in report.evidence.rows]
                    if turn.sql:
                        result.checks["evidencia"] = (
                            report.evidence is not None
                            and evidence_matches(query_rows(con, turn.sql), report.evidence)[0]
                        )
                    if turn.chart_kinds:
                        valid = output.chart is not None and output.chart.kind in turn.chart_kinds
                        if valid and output.chart is not None and report.evidence is not None:
                            check_chart(output.chart, report.evidence)
                        result.checks["grafico"] = valid and report.evidence is not None
                    conversation.remember(turn.question, report)
                except (AgentRunError, FallbackExceptionGroup, ValueError) as error:
                    result.error = explain_model_failure(error)
                    result.checks["comportamento"] = False
                result.requests = usage.requests
                result.tokens = usage.input_tokens + usage.output_tokens
                result.cost_usd = cost_usd(model_id, usage.input_tokens, usage.output_tokens)
                result.seconds = perf_counter() - started
                turns.append(result)
        results.append(ScenarioResult(name=case.name, suite=case.suite, turns=turns))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="modelo real; sem este argumento, valida offline")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "evals/results/conversations"
    )
    args = parser.parse_args(argv)
    scenarios = load_scenarios()
    validate_scenarios(scenarios)
    count = sum(len(case.turns) for case in scenarios.cases)
    if not args.model or args.validate_only:
        print(f"{len(scenarios.cases)} conversas, {count} turnos validados offline; sem modelo.")
        return
    if not args.yes and not confirm(
        f"Executar {count} turnos? {estimated_cost(args.model, count)}"
    ):
        raise SystemExit("Cancelado.")
    settings = Settings()
    results = evaluate_scenarios(
        scenarios, google_model(args.model, settings.google_api_key, 0), args.model
    )
    source = resource_path("evals/conversations.toml").read_bytes()
    for name in sorted({case.suite for case in scenarios.cases}):
        source += SUITES[name].revision().encode()
    report = {
        "model": args.model,
        "revision": hashlib.sha256(source).hexdigest(),
        "cases": [case.model_dump(mode="json") for case in results],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / (re.sub(r"[^a-zA-Z0-9_.-]", "_", args.model) + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {path}")
