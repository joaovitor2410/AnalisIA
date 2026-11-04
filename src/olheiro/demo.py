"""Exemplos curados e limite compartilhado da demonstração, independentes da interface."""

import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.usage import RunUsage

from olheiro.agent import AnalysisAnswer, build_report
from olheiro.cache import AnswerCache
from olheiro.charts import check_chart
from olheiro.sql_guard import check_query
from olheiro.storage import JsonFile, MemoryStore


class DemoExample(BaseModel):
    question: str
    output: AnalysisAnswer


class DemoExamples(BaseModel):
    examples: list[DemoExample]


def load_examples(path: Path, con: duckdb.DuckDBPyConnection) -> AnswerCache:
    """Valida e executa cada exemplo; nenhuma resposta ou tabela vem de um LLM."""
    with path.open("rb") as file:
        examples = DemoExamples.model_validate(tomllib.load(file))
    cache = AnswerCache(None)
    for example in examples.examples:
        output = example.output
        if output.answerable and not output.sql:
            raise ValueError(f"Exemplo sem SQL de evidência: {example.question}")
        if output.sql:
            check_query(output.sql)
        report = build_report(output, con, "curadoria SQL", RunUsage(), [])
        if output.chart is not None:
            if report.evidence is None:
                raise ValueError(f"Gráfico sem evidência: {example.question}")
            check_chart(output.chart, report.evidence)
        cache.store(example.question, report)
    return cache


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date | None = None
    used: int = Field(default=0, ge=0)


class BudgetUnavailableError(RuntimeError):
    """Sem acesso confiável à quota, nenhuma requisição nova pode ser autorizada."""


def utc_today() -> date:
    return datetime.now(UTC).date()


class QuestionBudget:
    """Tentativas por dia UTC; com caminho, persiste e coordena processos no mesmo disco."""

    def __init__(self, limit: int, path: Path | None = None) -> None:
        if limit < 0:
            raise ValueError("O limite de perguntas não pode ser negativo.")
        self.limit = limit
        self.file = JsonFile(path, BudgetState) if path is not None else MemoryStore(BudgetState)

    def take(self) -> bool:
        try:
            with self.file.update() as state:
                today = utc_today()
                if state.day is not None and state.day > today:
                    raise ValueError("A data da quota está no futuro.")
                if state.day != today:
                    state.day, state.used = today, 0
                if state.used >= self.limit:
                    return False
                state.used += 1
            return True
        except (OSError, ValueError) as error:
            raise BudgetUnavailableError(
                "Não foi possível reservar a quota da demonstração. "
                "Nenhuma chamada ao modelo foi autorizada. Tente novamente mais tarde."
            ) from error
