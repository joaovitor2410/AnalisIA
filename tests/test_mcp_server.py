"""Contrato MCP de ponta a ponta: cliente real, modelo falso e bancos temporários."""

import sys
from collections.abc import Callable
from pathlib import Path

import anyio
import duckdb
import pytest
from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, TextContent, TextResourceContents
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from olheiro import mcp_server
from olheiro.config import Settings
from olheiro.db import connect, scalar
from olheiro.telemetry import RunLog

QUESTION = "Quem foi o campeão de 2019?"
SQL = "SELECT team, points FROM raw.brasileirao WHERE season = 2019 AND place = 1"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    database = tmp_path / "test.duckdb"
    with connect(database) as con:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.brasileirao AS SELECT * FROM "
            "(VALUES (2019, 1, 'Flamengo', 90), (2019, 2, 'Santos', 74), "
            "(2020, 1, 'Flamengo', 71)) AS t(season, place, team, points)"
        )
    glossary = tmp_path / "glossary.toml"
    glossary.write_text('rules = ["Classificação final, não jogos."]', encoding="utf-8")
    return Settings(
        _env_file=None,
        google_api_key=None,
        duckdb_path=database,
        workspace_path=tmp_path / "workspace.duckdb",
        glossary_path=glossary,
        answer_cache_path=tmp_path / "cache.json",
        runs_path=tmp_path / "runs.jsonl",
        olheiro_tracing="off",
    )


def fake_model(monkeypatch: pytest.MonkeyPatch, *, save: bool = False) -> list[str]:
    calls: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("model")
        if save:
            return ModelResponse(
                parts=[ToolCallPart("save_result", {"name": "champions", "query": SQL})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "Flamengo, com 90 pontos.",
                        "sql": SQL,
                        "chart": {"kind": "metric", "y": "points", "title": "Pontos"},
                    },
                )
            ]
        )

    monkeypatch.setattr(mcp_server, "build_model", lambda settings: FunctionModel(respond))
    return calls


def error_text(result: CallToolResult) -> str:
    # Usado só nas asserções; o contrato real é exercitado pelo Client em cada teste.
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


@pytest.mark.anyio
async def test_discovery_exposes_typed_tools_resource_and_prompt(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert set(tools) == {
            "run_sql",
            "profile_column",
            "ask_question",
            "discover_tables",
            "describe_table",
            "read_semantics",
        }
        for tool in tools.values():
            assert tool.annotations.read_only_hint is True
            assert "ctx" not in tool.input_schema["properties"]
            assert tool.output_schema is not None
        assert tools["run_sql"].annotations.open_world_hint is False
        assert tools["ask_question"].annotations.open_world_hint is True
        assert [str(r.uri) for r in (await client.list_resources()).resources] == [
            "olheiro://context"
        ]
        assert [p.name for p in (await client.list_prompts()).prompts] == ["analyze_data"]
        context = (await client.read_resource("olheiro://context")).contents[0]
        assert isinstance(context, TextResourceContents)
        assert "raw.brasileirao" in context.text
        assert "Classificação final, não jogos." in context.text
        prompt = await client.get_prompt("analyze_data", {"question": QUESTION})
        assert isinstance(prompt.messages[0].content, TextContent)
        assert QUESTION in prompt.messages[0].content.text
        assert "olheiro://context" in prompt.messages[0].content.text


@pytest.mark.anyio
async def test_sql_and_profile_work_without_api_key_or_model(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        result = await client.call_tool("run_sql", {"query": SQL})
        assert not result.is_error
        assert result.structured_content == {
            "columns": ["team", "points"],
            "rows": [["Flamengo", 90]],
            "truncated": False,
        }
        profile = await client.call_tool(
            "profile_column", {"table": "raw.brasileirao", "column": "team"}
        )
        assert not profile.is_error and "Flamengo" in str(profile.structured_content)
        missing = await client.call_tool(
            "profile_column", {"table": "raw.brasileirao", "column": "missing"}
        )
        assert missing.is_error and "não existe" in error_text(missing)
    assert RunLog(settings.runs_path).read() == []  # SQL direto não é uma pergunta ao agente


@pytest.mark.anyio
async def test_sql_output_serializes_dates_decimals_null_and_truncation(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        typed = await client.call_tool(
            "run_sql",
            {"query": "SELECT DATE '2024-01-01' AS day, 1.25::DECIMAL(4,2) AS n, NULL AS x"},
        )
        assert not typed.is_error
        assert typed.structured_content["rows"] == [["2024-01-01", "1.25", None]]
        cut = await client.call_tool("run_sql", {"query": "SELECT unnest(range(51)) AS n"})
        assert cut.structured_content["truncated"] is True
        assert len(cut.structured_content["rows"]) == 50


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE raw.brasileirao",
        "SELECT 1; SELECT 2",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "COPY (SELECT 1) TO '/tmp/olheiro-mcp-test.csv'",
        "ATTACH '/tmp/olheiro-mcp-test.duckdb' AS other",
        "SET enable_external_access = true",
        "SELECT * FROM lake.raw.brasileirao",
        "CREATE TABLE workspace.champions AS SELECT 1",
    ],
)
async def test_unsafe_sql_is_a_protocol_tool_error_and_connection_survives(
    settings: Settings, query: str
) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        refused = await client.call_tool("run_sql", {"query": query})
        assert refused.is_error and "Consulta recusada" in error_text(refused)
        assert refused.structured_content is None
        valid = await client.call_tool("run_sql", {"query": SQL})
        assert not valid.is_error and valid.structured_content["rows"] == [["Flamengo", 90]]


@pytest.mark.anyio
async def test_database_error_is_explained_and_bad_inputs_are_rejected(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        missing = await client.call_tool(
            "run_sql", {"query": "SELECT missing FROM raw.brasileirao"}
        )
        assert missing.is_error and "BinderException" in error_text(missing)
        for name, args in [
            ("run_sql", {"query": ""}),
            ("run_sql", {"query": "x" * 20_001}),
            ("ask_question", {"question": "   "}),
            ("ask_question", {"question": "x" * 4_001}),
        ]:
            assert (await client.call_tool(name, args)).is_error
    assert not settings.answer_cache_path.exists()
    assert RunLog(settings.runs_path).read() == []


@pytest.mark.anyio
async def test_agent_answer_cache_and_telemetry_share_the_existing_core(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_model(monkeypatch)
    async with Client(mcp_server.create_server(settings)) as client:
        first = await client.call_tool("ask_question", {"question": QUESTION})
        assert not first.is_error, error_text(first)
        data = first.structured_content
        assert data["evidence"]["rows"] == [["Flamengo", 90]]
        assert data["output"]["sql"] == SQL
        assert data["output"]["chart"]["kind"] == "metric"
        assert data["from_cache"] is False and data["requests"] == 1
        # Nem construir o modelo é necessário para usar o cache.
        monkeypatch.setattr(mcp_server, "build_model", lambda settings: pytest.fail("usou modelo"))
        cached = await client.call_tool("ask_question", {"question": QUESTION})
        assert not cached.is_error
        assert cached.structured_content["from_cache"] is True
        assert cached.structured_content["requests"] == 0
        assert cached.structured_content["evidence"] == data["evidence"]
    assert len(calls) == 1
    records = RunLog(settings.runs_path).read()
    assert [(r.source, r.outcome, r.from_cache) for r in records] == [
        ("mcp", "answer", False),
        ("mcp", "answer", True),
    ]


@pytest.mark.anyio
async def test_no_cache_flag_calls_model_each_time_and_does_not_store(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_model(monkeypatch)
    async with Client(mcp_server.create_server(settings)) as client:
        for _ in range(2):
            result = await client.call_tool(
                "ask_question", {"question": QUESTION, "use_cache": False}
            )
            assert not result.is_error, error_text(result)
    assert len(calls) == 2 and not settings.answer_cache_path.exists()


@pytest.mark.anyio
async def test_save_request_never_writes_or_caches_and_is_recorded_as_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_model(monkeypatch, save=True)
    async with Client(mcp_server.create_server(settings)) as client:
        result = await client.call_tool("ask_question", {"question": "Salve os campeões"})
        assert result.is_error and "apenas leitura" in error_text(result)
    with connect(settings.workspace_path) as con:
        assert scalar(con, "SELECT count(*) FROM duckdb_tables()") == 0
    assert not settings.answer_cache_path.exists()
    (record,) = RunLog(settings.runs_path).read()
    assert record.source == "mcp" and record.outcome == "error"


@pytest.mark.anyio
async def test_missing_key_is_explained_and_logged(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:
        result = await client.call_tool("ask_question", {"question": QUESTION})
        assert result.is_error and "GOOGLE_API_KEY não definida" in error_text(result)
    assert RunLog(settings.runs_path).read()[0].outcome == "error"


@pytest.mark.anyio
async def test_refusal_is_a_successful_result_without_evidence(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answerable": False, "answer": "Não há dados de artilharia."},
                )
            ]
        )

    monkeypatch.setattr(mcp_server, "build_model", lambda settings: FunctionModel(refuse))
    async with Client(mcp_server.create_server(settings)) as client:
        result = await client.call_tool("ask_question", {"question": "Quem foi o artilheiro?"})
        assert not result.is_error, error_text(result)
        assert result.structured_content["output"]["answerable"] is False
        assert result.structured_content["evidence"] is None
    assert RunLog(settings.runs_path).read()[0].outcome == "refusal"


@pytest.mark.anyio
async def test_unexpected_failure_is_logged_and_server_can_still_query(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(settings: Settings) -> None:
        raise RuntimeError("Falha de teste")

    monkeypatch.setattr(mcp_server, "build_model", fail)
    async with Client(mcp_server.create_server(settings)) as client:
        result = await client.call_tool("ask_question", {"question": QUESTION})
        assert result.is_error
        assert not (await client.call_tool("run_sql", {"query": SQL})).is_error
    (record,) = RunLog(settings.runs_path).read()
    assert record.outcome == "error" and "Falha de teste" in record.error


@pytest.mark.anyio
async def test_concurrent_queries_do_not_share_cursor_state(settings: Settings) -> None:
    async with Client(mcp_server.create_server(settings)) as client:

        async def query(number: int) -> None:
            result = await client.call_tool("run_sql", {"query": f"SELECT {number} AS n"})
            assert not result.is_error and result.structured_content["rows"] == [[number]]

        async with anyio.create_task_group() as group:
            for number in range(12):
                group.start_soon(query, number)


@pytest.mark.anyio
async def test_lifespan_closes_connection_even_after_tool_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections: list[duckdb.DuckDBPyConnection] = []
    original: Callable[..., duckdb.DuckDBPyConnection] = mcp_server.connect_agent

    def capture(*args: object) -> duckdb.DuckDBPyConnection:
        con = original(*args)
        connections.append(con)
        return con

    monkeypatch.setattr(mcp_server, "connect_agent", capture)
    server = mcp_server.create_server(settings)
    assert not connections  # a fábrica não abre o banco
    async with Client(server) as client:
        assert (
            await client.call_tool("run_sql", {"query": "DELETE FROM raw.brasileirao"})
        ).is_error
        assert scalar(connections[0], "SELECT count(*) FROM raw.brasileirao") == 3
        # O recurso inclui tabelas salvas por outros canais, sem reconstruir o servidor.
        before = await client.read_resource("olheiro://context")
        assert "workspace.champions" not in before.contents[0].text
        connections[0].execute("CREATE TABLE workspace.champions AS SELECT 1 AS n")
        after = await client.read_resource("olheiro://context")
        assert "workspace.champions" in after.contents[0].text
    with pytest.raises(duckdb.ConnectionException):
        connections[0].execute("SELECT 1")


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_stdio_subprocess_from_another_directory(settings: Settings, mode: str) -> None:
    # Executa a entrada real; qualquer banner em stdout quebra a negociação do protocolo.
    env = {
        field.upper(): str(getattr(settings, field))
        for field in ("duckdb_path", "workspace_path", "glossary_path", "runs_path")
    }
    env["OLHEIRO_TRACING"] = "off"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "olheiro.mcp_server"],
        cwd=settings.duckdb_path.parent,
        env=env,
    )
    with anyio.fail_after(20):
        async with Client(params, mode=mode) as client:
            result = await client.call_tool("run_sql", {"query": SQL})
            assert not result.is_error and result.structured_content["rows"] == [["Flamengo", 90]]
            context = await client.read_resource("olheiro://context")
            assert "Classificação final, não jogos." in context.contents[0].text
