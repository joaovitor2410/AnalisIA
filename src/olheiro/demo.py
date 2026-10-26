"""Exemplos curados e limite compartilhado da demonstração, independentes da interface."""

import threading
import tomllib
from pathlib import Path

import duckdb
from pydantic import BaseModel
from pydantic_ai.usage import RunUsage

from olheiro.agent import AnalysisAnswer, build_report
from olheiro.cache import AnswerCache
from olheiro.charts import check_chart
from olheiro.sql_guard import check_query


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


class QuestionBudget:
    """Limite de tentativas ao modelo por processo; cache não consome esse orçamento."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True
