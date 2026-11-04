"""Continuações com evidência própria, cache contextual e aprovações descartáveis."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from olheiro.agent import (
    AgentDeps,
    AgentReport,
    AnalysisAnswer,
    ApprovalContextError,
    PendingApproval,
    ask,
    build_report,
    resume,
)
from olheiro.cache import AnswerCache, ask_with_cache
from olheiro.conversation import Conversation
from olheiro.db import connect, connect_agent, scalar, session_cursor
from olheiro.semantic import Glossary

SQL = "SELECT season, team, points FROM raw.seasons WHERE season = 2019"
NEXT_SQL = "SELECT season, team, points FROM raw.seasons WHERE season = 2020"


@pytest.fixture
def deps(tmp_path: Path) -> Iterator[AgentDeps]:
    database = tmp_path / "source.duckdb"
    with connect(database) as con:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.seasons AS SELECT * FROM (VALUES "
            "(2019, 'Flamengo', 90), (2020, 'Flamengo', 71)) t(season, team, points)"
        )
    with connect_agent(database, None) as con:
        yield AgentDeps(con)


def report(deps: AgentDeps, sql: str = SQL) -> AgentReport:
    return build_report(
        AnalysisAnswer(answerable=True, answer="Resultado na evidência.", sql=sql),
        deps.con,
        "roteirizado",
        RunUsage(),
        [],
    )


def text_history(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, UserPromptPart | TextPart)
    ]


def final(info: AgentInfo, sql: str = NEXT_SQL) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "answerable": True,
                    "answer": "Confira a evidência atual.",
                    "sql": sql,
                },
            )
        ]
    )


def test_continuation_after_cache_hit_receives_prior_question_and_sql(deps: AgentDeps) -> None:
    cache, conversation = AnswerCache(None), Conversation()
    cache.store("Quem foi campeão em 2019?", report(deps))
    first = ask_with_cache("Quem foi campeão em 2019?", deps, cache, conversation=conversation)
    assert isinstance(first, AgentReport) and first.from_cache
    received: list[list[str]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        received.append(text_history(messages))
        return final(info)

    second = ask_with_cache(
        "E em 2020?",
        deps,
        cache,
        FunctionModel(respond),
        conversation=conversation,
    )
    assert isinstance(second, AgentReport) and second.evidence is not None
    assert second.evidence.rows == [(2020, "Flamengo", 71)]
    assert received[0][0] == "Quem foi campeão em 2019?"
    assert SQL in received[0][1] and received[0][-1] == "E em 2020?"
    assert conversation.turn_count == 2
    assert "E em 2020?" not in cache.questions()
    assert cache.lookup("E em 2020?", deps.con) is None


def test_same_continuation_has_distinct_cache_for_each_context(deps: AgentDeps) -> None:
    cache = AnswerCache(None)
    first, second = Conversation(), Conversation()
    for conversation, question, sql in (
        (first, "Campeão em 2019?", SQL),
        (second, "Campeão em 2020?", NEXT_SQL),
    ):
        conversation.bind(deps)
        conversation.remember(question, report(deps, sql))
    first_key, second_key = first.cache_key(), second.cache_key()
    assert first_key != second_key
    cache.store("E os pontos?", report(deps), first_key)
    assert cache.lookup("E os pontos?", deps.con, second_key) is None
    assert cache.lookup("E os pontos?", deps.con, first_key) is not None
    assert cache.questions() == []
    # Outra instância com o mesmo contexto pode reexecutar a evidência sem modelo.
    third = Conversation()
    third.bind(deps)
    third.remember("Campeão em 2019?", report(deps))
    outcome = ask_with_cache("E os pontos?", deps, cache, conversation=third)
    assert isinstance(outcome, AgentReport) and outcome.from_cache
    assert outcome.evidence is not None and outcome.evidence.rows == [(2019, "Flamengo", 90)]


@pytest.mark.parametrize("change", ["connection", "glossary", "namespace", "permissions"])
def test_conversation_resets_for_another_scope(deps: AgentDeps, change: str) -> None:
    conversation = Conversation()
    conversation.bind(deps, "revision-a")
    conversation.remember("Questão privada", report(deps))
    with session_cursor(deps.con) as other:
        updated = AgentDeps(
            other if change == "connection" else deps.con,
            Glossary(rules=["Nova regra"]) if change == "glossary" else deps.glossary,
            allow_saves=change != "permissions",
        )
        conversation.bind(updated, "revision-b" if change == "namespace" else "revision-a")
        assert conversation.turn_count == 0 and conversation.cache_key() is None


def test_trim_keeps_complete_turns_and_never_replays_tool_calls(deps: AgentDeps) -> None:
    conversation = Conversation(max_turns=2)
    conversation.bind(deps)
    previous = report(deps)
    previous.messages.append(
        ModelResponse(
            parts=[
                ToolCallPart(
                    "save_result",
                    {
                        "name": "segredo",
                        "query": SQL,
                    },
                )
            ]
        )
    )
    for question in ("primeira", "segunda", "terceira"):
        conversation.remember(question, previous)
    messages = conversation.messages()
    assert len(messages) == 4 and conversation.truncated
    assert text_history(messages)[::2] == ["segunda", "terceira"]
    assert not any(
        isinstance(part, ToolCallPart | ToolReturnPart)
        for message in messages
        for part in message.parts
    )
    limited = Conversation(max_chars=10)
    limited.remember("Uma análise grande", previous)
    assert limited.messages() == [] and limited.truncated


def test_old_context_is_not_mutated_by_history_consumers(deps: AgentDeps) -> None:
    conversation = Conversation()
    conversation.bind(deps)
    conversation.remember("Original", report(deps))
    before = conversation.cache_key()
    messages = conversation.messages()
    messages[0].parts.clear()  # a cópia entregue a uma integração é descartável
    assert conversation.cache_key() == before
    assert text_history(conversation.messages())[0] == "Original"


def test_failure_does_not_enter_the_conversation(deps: AgentDeps) -> None:
    cache, conversation = AnswerCache(None), Conversation()

    def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise UnexpectedModelBehavior("Falha simulada")

    with pytest.raises(UnexpectedModelBehavior):
        ask_with_cache("Pergunta", deps, cache, FunctionModel(fail), conversation=conversation)
    assert conversation.turn_count == 0 and cache.questions() == []


def test_continuation_still_requires_its_own_valid_evidence(deps: AgentDeps) -> None:
    conversation = Conversation()
    conversation.bind(deps)
    conversation.remember("Campeão em 2019?", report(deps))
    received: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        received.append(messages)
        if len(received) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "answerable": True,
                            "answer": "Mesmo campeão, sem SQL.",
                        },
                    )
                ]
            )
        return final(info)

    outcome = ask(
        "E em 2020?", deps, FunctionModel(respond), message_history=conversation.messages()
    )
    assert isinstance(outcome, AgentReport) and outcome.evidence is not None
    assert outcome.evidence.rows == [(2020, "Flamengo", 71)]
    assert any(isinstance(part, RetryPromptPart) for msg in received[1] for part in msg.parts)


@pytest.mark.parametrize("change", ["connection", "glossary", "permissions"])
def test_approval_cannot_cross_scope(deps: AgentDeps, change: str) -> None:
    model = FunctionModel(
        lambda messages, info: ModelResponse(
            parts=[
                ToolCallPart(
                    "save_result",
                    {"name": "saved", "query": SQL},
                )
            ]
        )
    )
    pending = ask("Salve o campeão", deps, model)
    assert isinstance(pending, PendingApproval)
    with session_cursor(deps.con) as other:
        updated = AgentDeps(
            other if change == "connection" else deps.con,
            Glossary(rules=["Outra regra"]) if change == "glossary" else deps.glossary,
            allow_saves=change != "permissions",
        )
        with pytest.raises(ApprovalContextError, match="mudaram"):
            resume(pending, True, updated, model)
    assert scalar(deps.con, "SELECT count(*) FROM duckdb_tables() WHERE table_name='saved'") == 0


def test_pending_is_not_remembered_and_decision_can_only_be_used_once(deps: AgentDeps) -> None:
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("save_result", {"name": "saved", "query": SQL})]
            )
        return final(info, SQL)

    model = FunctionModel(respond)
    conversation = Conversation()
    pending = ask_with_cache("Salve", deps, AnswerCache(None), model, conversation=conversation)
    assert isinstance(pending, PendingApproval) and conversation.turn_count == 0
    result = resume(pending, True, deps, model)
    assert isinstance(result, AgentReport) and result.usage.requests == 2
    assert scalar(deps.con, "SELECT count(*) FROM workspace.saved") == 1
    with pytest.raises(ApprovalContextError, match="já foi utilizada"):
        resume(pending, True, deps, model)
    assert calls == 2


def test_new_save_in_later_turn_requires_another_decision(deps: AgentDeps) -> None:
    def save(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("save_result", {"name": "later", "query": SQL})])

    conversation = Conversation()
    conversation.bind(deps)
    conversation.remember("Salve a tabela anterior", report(deps))
    outcome = ask_with_cache(
        "Salve novamente com outro nome",
        deps,
        AnswerCache(None),
        FunctionModel(save),
        conversation=conversation,
    )
    assert isinstance(outcome, PendingApproval)
    assert scalar(deps.con, "SELECT count(*) FROM duckdb_tables() WHERE table_name='later'") == 0
