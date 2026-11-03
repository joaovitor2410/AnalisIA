"""Cache de respostas: uma pergunta repetida não chama o modelo (0 requisições).

Guarda a resposta estruturada (AnalysisAnswer), não a tabela: no acerto, o SQL é validado e
reexecutado, então os números vêm sempre do banco atual. A chave é a pergunta normalizada
(Unicode canônico, sem espaços nas pontas). Filtros, códigos, acentos e caixa são preservados.
Numa demo pública, um cache de exemplos mantém a demo funcionando mesmo sem cota.
"""

import hashlib
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
from pydantic import BaseModel, TypeAdapter
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

from olheiro.agent import AgentDeps, AgentReport, AnalysisAnswer, PendingApproval, ask, build_report
from olheiro.charts import check_chart
from olheiro.sql_guard import UnsafeQueryError, check_query
from olheiro.storage import JsonFile, MemoryStore
from olheiro.tools import QueryResult


class CachedAnswer(BaseModel):
    question: str
    output: AnalysisAnswer
    model_name: str
    created_at: datetime
    evidence_hash: str | None = None


class CacheFile(BaseModel):
    namespace: str | None = None
    answers: dict[str, CachedAnswer] = {}


def evidence_hash(evidence: QueryResult | None) -> str:
    """Compara também o resultado: texto antigo não acompanha uma evidência alterada."""
    encoded = TypeAdapter(QueryResult | None).dump_json(evidence, fallback=str)
    return hashlib.sha256(encoded).hexdigest()


def normalize_question(question: str) -> str:
    """Normaliza somente diferenças que não alteram filtros nem valores literais.

    Remover pontuação confundia `valor > 100` com `valor < 100`; alterar caixa/acentos
    também confundiria códigos distintos. Espaços internos podem pertencer a um literal.
    """
    return unicodedata.normalize("NFC", question.strip())


class AnswerCache:
    def __init__(self, path: Path | None, namespace: str | None = None) -> None:
        self.file = JsonFile(path, CacheFile) if path is not None else MemoryStore(CacheFile)
        self.namespace = namespace

    def read(self) -> CacheFile:
        cache = self.file.read()
        if cache.namespace != self.namespace:
            return CacheFile(namespace=self.namespace)
        # Recupera a pergunta original de caches antigos, cujas chaves perdiam informação.
        # Uma resposta só pode ser encontrada pelo conteúdo que a originou.
        cache.answers = {
            normalize_question(entry.question): entry for entry in cache.answers.values()
        }
        return cache

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
            report = build_report(
                entry.output, con, entry.model_name, RunUsage(), [], from_cache=True
            )
            if entry.output.chart is not None and report.evidence is not None:
                check_chart(entry.output.chart, report.evidence)
            if (
                entry.evidence_hash is not None
                and evidence_hash(report.evidence) != entry.evidence_hash
            ):
                return None
            return report
        except (UnsafeQueryError, duckdb.Error, ValueError):
            return None  # SQL antigo não serve mais (ex.: coluna mudou): trata como ausente

    def store(self, question: str, report: AgentReport) -> None:
        entry = CachedAnswer(
            question=question,
            output=report.output,
            model_name=report.model_name,
            created_at=datetime.now(),
            evidence_hash=evidence_hash(report.evidence),
        )
        with self.file.update() as cache:
            if cache.namespace != self.namespace:
                cache.answers = {}
                cache.namespace = self.namespace
            cache.answers = {
                normalize_question(saved.question): saved for saved in cache.answers.values()
            }
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
    # Uma recusa pode deixar de valer após salvar outra tabela em workspace. Só exemplos
    # curados (load_examples) guardam recusas; respostas novas sem evidência não são cacheadas.
    if isinstance(outcome, AgentReport) and outcome.output.answerable:
        cache.store(question, outcome)
    return outcome
