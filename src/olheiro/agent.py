"""O agente analista: ferramentas, saída estruturada e validação da evidência (Pydantic AI).

Fluxo de uma pergunta:
    1. O modelo consulta os dados com as ferramentas (run_sql, profile_column).
    2. Entrega um AnalysisAnswer: resposta, SQL de evidência, insights e gráfico sugerido.
    3. O validador reexecuta o SQL de evidência; se falhar, ModelRetry devolve o erro ao modelo.
    4. `ask` reexecuta o SQL para a tabela: os números mostrados vêm do banco, não do LLM.
"""

from dataclasses import dataclass
from numbers import Number
from typing import Literal

import duckdb
from pydantic import BaseModel, Field, SecretStr
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from olheiro import tools
from olheiro.config import Settings
from olheiro.tools import QueryResult, query_rows


@dataclass
class AgentDeps:
    """Dependências de uma execução: o que as ferramentas e o validador acessam via ctx.deps."""

    con: duckdb.DuckDBPyConnection


class ChartSpec(BaseModel):
    """Gráfico sugerido pelo modelo. Os dados vêm do SQL de evidência, não do modelo."""

    kind: Literal["bar", "line"] = Field(
        description="'bar' para comparar categorias; 'line' para evolução ao longo das temporadas."
    )
    x: str = Field(description="Coluna do resultado do SQL de evidência para o eixo X.")
    y: str = Field(description="Coluna numérica do resultado do SQL de evidência para o eixo Y.")
    title: str = Field(description="Título curto, em português.")


class AnalysisAnswer(BaseModel):
    """Saída estruturada do agente: o formato que o modelo é obrigado a entregar."""

    answerable: bool = Field(
        description="False quando os dados disponíveis não permitem responder."
    )
    answer: str = Field(
        description="Resposta direta em português. Se não der para responder, explique o porquê."
    )
    sql: str | None = Field(
        default=None,
        description="Consulta SELECT que sustenta a resposta. Obrigatória se answerable for true.",
    )
    insights: list[str] = Field(
        default_factory=list,
        description="Até 3 observações curtas, cada uma verificável no resultado do campo sql.",
    )
    chart: ChartSpec | None = Field(
        default=None,
        description="Gráfico do resultado do SQL, só quando ajudar (comparação ou série temporal).",
    )


@dataclass(frozen=True)
class AgentReport:
    """Tudo que uma interface mostra: a resposta do modelo e a evidência executada pelo código."""

    output: AnalysisAnswer
    evidence: QueryResult | None
    model_name: str
    usage: RunUsage
    messages: list[ModelMessage]


INSTRUCTIONS = """\
Você é o Olheiro, um analista de dados. Responda sempre em português do Brasil.

Como trabalhar:
- Responda só com base nos dados do banco DuckDB, consultados com as ferramentas.
- Use o dialeto DuckDB e qualifique as tabelas com o schema (ex.: raw.teams).
- Antes de filtrar por um texto (nome de time, estado, região), use profile_column para ver
  como os valores estão escritos.
- Se uma consulta der erro, leia a mensagem e corrija.
- Se os dados não permitirem responder, marque answerable=false e explique o que falta.
  Nunca invente números.
- O campo sql deve conter uma única consulta que reproduza a evidência da resposta.
- Resposta e insights só podem afirmar o que aparece no resultado desse sql. Para afirmar
  posição em um ranking ("melhor ataque", "3º lugar"), calcule-a no próprio sql (ex.:
  RANK() OVER (...)) sobre todos os times da temporada. Um resultado com LIMIT não prova ranking.
"""

# Prazo de cada requisição ao modelo. Sem ele, uma chamada pendurada trava a CLI para sempre;
# com FallbackModel, estourar o prazo passa a pergunta para o modelo reserva.
REQUEST_TIMEOUT_SECONDS = 60

# O modelo não é fixado aqui: vem do .env na hora de rodar (ou de um modelo falso nos testes).
agent = Agent(
    output_type=AnalysisAnswer,
    deps_type=AgentDeps,
    instructions=INSTRUCTIONS,
    retries=2,
    model_settings=ModelSettings(request_timeout=REQUEST_TIMEOUT_SECONDS),
)


@agent.instructions
def schema_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Instrução dinâmica: o schema é lido do banco a cada execução, nunca fica desatualizado."""
    return "Tabelas disponíveis (tabela: coluna tipo, ...):\n" + tools.describe_schema(ctx.deps.con)


@agent.tool
def run_sql(ctx: RunContext[AgentDeps], query: str) -> dict[str, str]:
    """Executa uma consulta SQL (DuckDB, somente leitura) e devolve até 50 linhas em markdown.

    Args:
        query: Uma única consulta SELECT, com tabelas qualificadas pelo schema (ex.: raw.teams).
    """
    return tools.run_sql(ctx.deps.con, query)


@agent.tool
def profile_column(ctx: RunContext[AgentDeps], table: str, column: str) -> dict[str, str]:
    """Mostra tipo, nulos, distintos, mínimo/máximo e os valores mais frequentes de uma coluna.

    Args:
        table: Nome da tabela (ex.: brasileirao ou raw.brasileirao).
        column: Nome da coluna.
    """
    return tools.profile_column(ctx.deps.con, table, column)


@agent.output_validator
def validate_evidence(ctx: RunContext[AgentDeps], output: AnalysisAnswer) -> AnalysisAnswer:
    """Só aceita a resposta se a evidência se sustenta; senão o modelo recebe o motivo e corrige."""
    if not output.answerable:
        return output
    if output.sql is None:
        raise ModelRetry("Resposta sem evidência: preencha `sql` com a consulta que a sustenta.")
    try:
        evidence = query_rows(ctx.deps.con, output.sql)
    except duckdb.Error as error:
        raise ModelRetry(f"O SQL de evidência falhou: {error}. Corrija a consulta.") from error
    if output.chart is not None:
        check_chart(output.chart, evidence)
    return output


def check_chart(chart: ChartSpec, evidence: QueryResult) -> None:
    """O gráfico precisa usar colunas do resultado, e o eixo Y precisa ser numérico."""
    missing = [name for name in (chart.x, chart.y) if name not in evidence.columns]
    if missing:
        raise ModelRetry(
            f"O gráfico usa colunas fora do resultado do SQL: {missing}. "
            f"Colunas disponíveis: {evidence.columns}."
        )
    y_values = evidence.column_values(chart.y)
    if not all(value is None or isinstance(value, Number) for value in y_values):
        raise ModelRetry(f"O eixo Y do gráfico ('{chart.y}') precisa ser uma coluna numérica.")


def ask(question: str, con: duckdb.DuckDBPyConnection, model: Model | None = None) -> AgentReport:
    """Faz uma pergunta ao agente e devolve a resposta com a evidência reexecutada."""
    result = agent.run_sync(question, deps=AgentDeps(con), model=model)
    output = result.output
    evidence = query_rows(con, output.sql) if output.answerable and output.sql else None
    return AgentReport(
        output=output,
        evidence=evidence,
        model_name=result.response.model_name or "desconhecido",
        usage=result.usage,
        messages=result.all_messages(),
    )


# Retentativas (com espera crescente) do SDK em 429/5xx, só no último modelo da cadeia:
# o principal falha na hora para o fallback entrar sem atraso; o reserva insiste antes de desistir.
LAST_MODEL_RETRIES = 2


def build_model(settings: Settings) -> Model:
    """Monta o modelo do .env, com fallback opcional (ex.: principal sem cota ou com 503)."""
    if settings.olheiro_fallback_model is None:
        return google_model(settings.olheiro_model, settings.google_api_key, LAST_MODEL_RETRIES)
    primary = google_model(settings.olheiro_model, settings.google_api_key, retries=0)
    fallback = google_model(
        settings.olheiro_fallback_model, settings.google_api_key, LAST_MODEL_RETRIES
    )
    return FallbackModel(primary, fallback)


def google_model(model_id: str, api_key: SecretStr | None, retries: int) -> GoogleModel:
    """'google:gemini-3.8-flash' -> GoogleModel com a chave passada explicitamente."""
    provider, _, name = model_id.partition(":")
    if provider != "google":
        raise ValueError(f"Provedor '{provider}' ainda não suportado (Claude entra na Fase 5).")
    if api_key is None:
        raise ValueError("GOOGLE_API_KEY não definida no .env.")
    return GoogleModel(
        name,
        provider=GoogleProvider(api_key=api_key.get_secret_value()),
        settings=ModelSettings(max_retries=retries),
    )
