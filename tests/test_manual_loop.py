"""Testes do loop manual (learning/manual_loop.py) com um modelo falso: sem rede, sem cota."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from google.genai import types
from manual_loop import run_agent

from olheiro.db import connect


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    db_path = tmp_path / "test.duckdb"
    with connect(db_path) as setup:
        setup.execute("CREATE SCHEMA raw")
        setup.execute("CREATE TABLE raw.campeoes AS SELECT 2019 AS season, 'Flamengo' AS team")
    with connect(db_path, read_only=True) as read_only_con:
        yield read_only_con


def model_reply(*parts: types.Part) -> types.GenerateContentResponse:
    """Monta uma resposta do modelo como a API devolveria."""
    content = types.Content(role="model", parts=list(parts))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def sql_call(query: str) -> types.Part:
    return types.Part.from_function_call(name="run_sql", args={"query": query})


class ScriptedModel:
    """Modelo falso: devolve respostas prontas, em ordem, e guarda o histórico que recebeu."""

    def __init__(self, *replies: types.GenerateContentResponse) -> None:
        self.replies = list(replies)
        self.received: list[list[types.Content]] = []

    def __call__(self, contents: list[types.Content]) -> types.GenerateContentResponse:
        self.received.append(list(contents))
        return self.replies.pop(0)


def tool_response(content: types.Content) -> dict:
    return content.parts[0].function_response.response


def test_loop_executes_tool_and_returns_final_text(con: duckdb.DuckDBPyConnection) -> None:
    model = ScriptedModel(
        model_reply(sql_call("SELECT team FROM raw.campeoes WHERE season = 2019")),
        model_reply(types.Part.from_text(text="O campeão de 2019 foi o Flamengo.")),
    )

    answer = run_agent("Quem foi campeão em 2019?", model, con)

    assert answer == "O campeão de 2019 foi o Flamengo."
    # 2ª chamada: pergunta + pedido do modelo + resultado da ferramenta
    history = model.received[1]
    assert [content.role for content in history] == ["user", "model", "user"]
    assert "Flamengo" in tool_response(history[2])["result"]


def test_loop_sends_sql_errors_back_to_the_model(con: duckdb.DuckDBPyConnection) -> None:
    model = ScriptedModel(
        model_reply(sql_call("SELECT time FROM raw.campeoes")),
        model_reply(types.Part.from_text(text="ok")),
    )

    run_agent("pergunta", model, con)

    assert "error" in tool_response(model.received[1][2])


def test_loop_answers_all_parallel_calls_in_one_message(con: duckdb.DuckDBPyConnection) -> None:
    model = ScriptedModel(
        model_reply(sql_call("SELECT 1 AS a"), sql_call("SELECT 2 AS b")),
        model_reply(types.Part.from_text(text="ok")),
    )

    run_agent("pergunta", model, con)

    assert len(model.received[1][2].parts) == 2


def test_loop_stops_after_max_steps(con: duckdb.DuckDBPyConnection) -> None:
    model = ScriptedModel(*[model_reply(sql_call("SELECT 1")) for _ in range(3)])

    answer = run_agent("pergunta", model, con, max_steps=3)

    assert "3 passos" in answer
    assert model.replies == []
