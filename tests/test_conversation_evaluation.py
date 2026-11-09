"""Os avaliadores de conversa detectam perda de filtros; não medem LLM com scripts."""

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from olheiro import conversation_evaluation as evaluation
from olheiro.eval_suites import SUITES, suite_database
from olheiro.tools import query_rows


def test_validation_never_reads_settings_or_builds_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A validação offline tentou acessar configuração/modelo.")

    monkeypatch.setattr(evaluation, "Settings", forbidden)
    monkeypatch.setattr(evaluation, "google_model", forbidden)
    evaluation.main(["--validate-only"])


@pytest.mark.parametrize("drop_filter", [False, True])
def test_conversation_evaluation_preserves_context_and_detects_a_dropped_region(
    drop_filter: bool,
) -> None:
    scenarios = evaluation.load_scenarios()
    answers: dict[str, dict[str, object]] = {}
    for case in scenarios.cases:
        with suite_database(SUITES[case.suite]) as (con, _):
            for turn in case.turns:
                answer: dict[str, object] = {
                    "answerable": turn.answerable,
                    "answer": "Confira a evidência."
                    if turn.answerable
                    else "Faltam dados/contexto.",
                    "sql": turn.sql,
                }
                if turn.chart_kinds and turn.sql:
                    evidence = query_rows(con, turn.sql)
                    answer["chart"] = {
                        "kind": turn.chart_kinds[0],
                        "x": evidence.columns[0],
                        "y": evidence.columns[-1],
                        "title": "Comparação",
                    }
                answers[turn.question] = answer
    if drop_filter:
        answers["E na região Norte?"]["sql"] = scenarios.cases[0].turns[0].sql
    received: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        questions = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        question = questions[-1]
        assert isinstance(question, str)
        received.append(
            "\n".join(
                str(part.content)
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart | TextPart)
            )
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers[question])])

    results = evaluation.evaluate_scenarios(scenarios, FunctionModel(respond), "offline")
    assert len(results) == 5 and sum(len(case.turns) for case in results) == 12
    assert "região Sul" in received[1] and "status='concluido'" in received[1]
    assert results[0].turns[0].checks["evidencia"]
    assert results[0].turns[1].checks["evidencia"] is not drop_filter
    if not drop_filter:
        assert all(
            all(turn.checks.values()) and not turn.error for case in results for turn in case.turns
        )


def test_conversation_goldens_refuse_unsafe_sql() -> None:
    scenarios = evaluation.load_scenarios()
    scenarios.cases[0].turns[0].sql = "DELETE FROM raw.orders"
    with pytest.raises(ValueError):
        evaluation.validate_scenarios(scenarios)
