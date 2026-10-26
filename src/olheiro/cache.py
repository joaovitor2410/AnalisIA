"""Cache de respostas: uma pergunta repetida não chama o modelo (0 requisições).

Guarda a resposta estruturada (AnalysisAnswer), não a tabela: no acerto, o SQL é validado e
reexecutado, então os números vêm sempre do banco atual. A chave é a pergunta normalizada
(sem acento, pontuação ou maiúsculas). Numa demo pública, um cache de exemplos mantém a
demo funcionando mesmo sem cota.
"""

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
from pydantic import BaseModel
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from olheiro.agent import AgentDeps, AgentReport, AnalysisAnswer, PendingApproval, ask, build_report
from olheiro.sql_guard import UnsafeQueryError, check_query
from olheiro.storage import JsonFile, MemoryStore


class CachedAnswer(BaseModel):
    question: str
    output: AnalysisAnswer
    model_name: str
    created_at: datetime


class CacheFile(BaseModel):
    answers: dict[str, CachedAnswer] = {}


def normalize_question(question: str) -> str:
    """'Quem foi o Campeão de 2019?' -> 'quem foi o campeao de 2019'."""
    ascii_text = unicodedata.normalize("NFKD", question).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


class AnswerCache:
    def __init__(self, path: Path | None) -> None:
        self.file = JsonFile(path, CacheFile) if path is not None else MemoryStore(CacheFile)

    def read(self) -> CacheFile:
        return self.file.read()

    def questions(self) -> list[str]:
        """Perguntas já respondidas, na forma original: viram os exemplos do app."""
        return [entry.question for entry in self.read().answers.values()]

    def lookup(self, question: str, con: duckdb.DuckDBPyConnection) -> AgentReport | None:
        """Resposta guardada com a evidência reexecutada agora, ou None se não houver."""
        entry = self.read().answers.get(normalize_question(question))
        if entry is None:
            return None
        try:
            if entry.output.sql:
                check_query(entry.output.sql)  # o arquivo pode ter sido editado à mão
            return build_report(
                entry.output, con, entry.model_name, RunUsage(), [], from_cache=True
            )
        except (UnsafeQueryError, duckdb.Error):
            return None  # SQL antigo não serve mais (ex.: coluna mudou): trata como ausente

    def store(self, question: str, report: AgentReport) -> None:
        entry = CachedAnswer(
            question=question,
            output=report.output,
            model_name=report.model_name,
            created_at=datetime.now(),
        )
        with self.file.update() as cache:
            cache.answers[normalize_question(question)] = entry


def ask_with_cache(
    question: str, deps: AgentDeps, cache: AnswerCache, model: Model | None = None
) -> AgentReport | PendingApproval:
    """Responde do cache se puder; senão pergunta ao agente e guarda a resposta.

    Pausas para aprovação (save_result) não entram no cache: repetir a resposta não repetiria
    a gravação, então ela não vale como resposta pronta.
    """
    cached = cache.lookup(question, deps.con)
    if cached is not None:
        return cached
    outcome = ask(question, deps, model)
    if isinstance(outcome, AgentReport):
        cache.store(question, outcome)
    return outcome
