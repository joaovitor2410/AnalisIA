"""Servidor MCP local: o mesmo núcleo da AnalisIA, acessível por qualquer cliente MCP.

Dois caminhos: o cliente escreve SQL (sem LLM no servidor), ou delega a pergunta ao agente
completo (cache + Gemini + observabilidade). Só leitura: não há ferramenta de gravação nem
retomada de aprovações pelo protocolo. stdout fica reservado às mensagens MCP.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Annotated, Self

import duckdb
import pydantic_ai
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, JsonValue, TypeAdapter
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup

from olheiro import semantic
from olheiro.agent import AgentDeps, AgentReport, AnalysisAnswer, PendingApproval, ask, build_model
from olheiro.cache import AnswerCache
from olheiro.config import Settings, get_settings
from olheiro.datasets import cache_revision, database_revision
from olheiro.db import connect_agent, session_cursor
from olheiro.errors import explain_model_failure
from olheiro.semantic import Glossary, load_glossary, render_context
from olheiro.sql_guard import UnsafeQueryError, check_query
from olheiro.telemetry import RunLog, tracked
from olheiro.tools import QueryResult, describe_db_error, profile_column, query_rows
from olheiro.tracing import setup_tracing


class EvidenceTable(BaseModel):
    """Tabela JSON: preserva ordem, nomes repetidos de colunas e indicação de corte."""

    columns: list[str]
    rows: list[list[JsonValue]]
    truncated: bool

    @classmethod
    def from_result(cls, result: QueryResult) -> Self:
        # Datas e decimais viram strings JSON; tipos incomuns usam sua representação textual.
        data = TypeAdapter(QueryResult).dump_python(result, mode="json", fallback=str)
        return cls.model_validate(data)


class AnalysisResult(BaseModel):
    """Contrato MCP: resposta, evidência real, ChartSpec e consumo do agente."""

    output: AnalysisAnswer
    evidence: EvidenceTable | None
    model_name: str
    from_cache: bool
    requests: int
    input_tokens: int
    output_tokens: int

    @classmethod
    def from_report(cls, report: AgentReport) -> Self:
        return cls(
            output=report.output,
            evidence=EvidenceTable.from_result(report.evidence) if report.evidence else None,
            model_name=report.model_name,
            from_cache=report.from_cache,
            requests=report.usage.requests,
            input_tokens=report.usage.input_tokens,
            output_tokens=report.usage.output_tokens,
        )


@dataclass(frozen=True)
class ServerState:
    """Recursos do processo; cada chamada cria e fecha seu próprio cursor."""

    settings: Settings
    con: duckdb.DuckDBPyConnection
    glossary: Glossary
    cache: AnswerCache
    runs: RunLog
    data_revision: str | None = None

    @contextmanager
    def dependencies(self, settings: Settings | None = None) -> Iterator[AgentDeps]:
        cursor = session_cursor(self.con)
        try:
            settings = settings or self.current_settings()
            glossary = (
                load_glossary(settings.glossary_path) if settings.olheiro_dataset else self.glossary
            )
            yield AgentDeps(cursor, glossary)
        finally:
            cursor.close()

    def current_settings(self) -> Settings:
        return (
            self.settings.for_dataset(self.settings.olheiro_dataset)
            if self.settings.olheiro_dataset is not None
            else self.settings
        )


def analyze(question: str, state: ServerState, use_cache: bool) -> AnalysisResult:
    """Executa no worker síncrono do SDK; nunca chama run_sync dentro do loop assíncrono."""
    settings = state.current_settings()
    with state.dependencies(settings) as deps:
        cache = (
            AnswerCache(settings.answer_cache_path, cache_revision(settings, state.data_revision))
            if settings.olheiro_dataset
            else state.cache
        )
        cache.file = state.cache.file
        try:
            with tracked(state.runs, question, "mcp") as run:
                cached = cache.lookup(question, deps.con) if use_cache else None
                if cached is not None:
                    return AnalysisResult.from_report(run.finish(cached))
                # Construção tardia: SQL, recursos e respostas do cache funcionam sem chave.
                outcome = ask(question, deps, build_model(state.settings))
                if isinstance(outcome, PendingApproval):
                    raise ToolError(
                        "O MCP da AnalisIA permite apenas leitura. Nenhuma tabela foi gravada. "
                        "Para salvar com aprovação humana, use o app ou olheiro-ask."
                    )
                if use_cache and outcome.output.answerable:
                    cache.store(question, outcome)
                result = AnalysisResult.from_report(outcome)
                run.finish(outcome)
                return result
        except (AgentRunError, FallbackExceptionGroup, ValueError) as error:
            raise ToolError(explain_model_failure(error)) from error


def create_server(settings: Settings | None = None) -> MCPServer[ServerState]:
    """Monta o contrato sem abrir banco, configurar traces ou exigir chave na importação."""
    config = settings if settings is not None else get_settings()
    state: ServerState | None = None

    @asynccontextmanager
    async def lifespan(server: MCPServer[ServerState]) -> AsyncIterator[ServerState]:
        nonlocal state
        glossary = load_glossary(config.glossary_path)
        con = connect_agent(config.duckdb_path, config.workspace_path)
        try:
            setup_tracing(config)
            revision = database_revision(config)
            state = ServerState(
                config,
                con,
                glossary,
                AnswerCache(config.answer_cache_path, cache_revision(config, revision)),
                RunLog.from_settings(config),
                revision,
            )
            yield state
        finally:
            state = None
            con.close()

    server = MCPServer(
        "AnalisIA",
        instructions=(
            "Analista de dados tabulares. Leia olheiro://context para conhecer tabelas, "
            "valores e regras. run_sql e profile_column não chamam o Gemini; ask_question "
            "delega ao agente e pode consumir cota. Só leitura; SQL DuckDB, até 50 linhas. "
            "Responda em português, mostre SQL e evidência e respeite empates e dados ausentes."
        ),
        lifespan=lifespan,
    )

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def run_sql(
        query: Annotated[str, Field(min_length=1, max_length=20_000)],
        ctx: Context[ServerState],
    ) -> EvidenceTable:
        """Executa um SELECT DuckDB validado, sem LLM. Retorna até 50 linhas e truncated.

        Use tabelas qualificadas (raw.<tabela> ou workspace.<nome>).
        Consulte olheiro://context antes de escolher colunas e filtros.
        """
        try:
            check_query(query)
            with ctx.request_context.lifespan_context.dependencies() as deps:
                return EvidenceTable.from_result(query_rows(deps.con, query))
        except UnsafeQueryError as error:
            raise ToolError(f"Consulta recusada: {error}") from error
        except duckdb.Error as error:
            raise ToolError(describe_db_error(error)) from error

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_semantics(
        ctx: Context[ServerState], table: str = "", column: str = "", offset: int = 0
    ) -> str:
        """Lê descrições completas ou regras por página, sem Gemini."""
        with ctx.request_context.lifespan_context.dependencies() as deps:
            try:
                return semantic.read_semantics(deps.glossary, table, column, offset)
            except ValueError as error:
                raise ToolError(str(error)) from error

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def discover_tables(ctx: Context[ServerState], search: str = "", offset: int = 0) -> str:
        """Busca tabelas por nome, coluna e descrição; até vinte por página, sem Gemini."""
        with ctx.request_context.lifespan_context.dependencies() as deps:
            try:
                return semantic.discover_tables(deps.glossary, deps.con, search, offset)
            except ValueError as error:
                raise ToolError(str(error)) from error

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def describe_table(ctx: Context[ServerState], table: str, offset: int = 0) -> str:
        """Lê nomes, tipos e descrições das colunas de uma tabela por página, sem Gemini."""
        with ctx.request_context.lifespan_context.dependencies() as deps:
            try:
                return semantic.describe_table(deps.glossary, deps.con, table, offset)
            except ValueError as error:
                raise ToolError(str(error)) from error

    @server.tool(
        name="profile_column",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def profile_data_column(table: str, column: str, ctx: Context[ServerState]) -> dict[str, str]:
        """Mostra tipo, nulos, distintos e valores frequentes de uma coluna de raw, sem LLM."""
        try:
            with ctx.request_context.lifespan_context.dependencies() as deps:
                result = profile_column(deps.con, table, column)
        except duckdb.Error as error:
            raise ToolError(describe_db_error(error)) from error
        if "error" in result:
            raise ToolError(result["error"])
        return result

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    def ask_question(
        question: Annotated[str, Field(min_length=1, max_length=4_000, pattern=r"\S")],
        ctx: Context[ServerState],
        use_cache: bool = True,
    ) -> AnalysisResult:
        """Pergunta à AnalisIA em português: resposta, SQL, tabela, ChartSpec e consumo.

        Pode chamar o Gemini e consumir cota; cache reexecuta o SQL sem LLM. Perguntas são
        independentes, sem memória de conversa. Pedidos de gravação são recusados no MCP.
        """
        return analyze(question, ctx.request_context.lifespan_context, use_cache)

    @server.resource("olheiro://context", mime_type="text/plain")
    def data_context() -> str:
        """Catálogo atualizado, glossário, valores reais e regras de negócio (sem LLM)."""
        # O SDK 2.3 não injeta Context em recursos estáticos. O estado fica na fábrica,
        # preenchido/limpo pelo lifespan; nunca global e nunca criado na importação.
        if state is None:
            raise RuntimeError("Servidor ainda não iniciado.")
        with state.dependencies() as deps:
            return render_context(deps.glossary, deps.con)

    @server.prompt()
    def analyze_data(question: str) -> str:
        """Prepara uma análise em português com SQL e evidências, respeitando o glossário."""
        return (
            "Leia olheiro://context e responda à pergunta abaixo usando run_sql ou "
            "ask_question. Mostre o SQL, a tabela de evidência e até três insights sustentados "
            "pelo resultado. Confira empates; se os dados faltarem, explique a limitação.\n\n"
            f"Pergunta: {question}"
        )

    return server


def main() -> None:
    """Comando olheiro-mcp: servidor stdio local, sem abrir porta HTTP."""
    pydantic_ai.BANNER_ENABLED = False
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
