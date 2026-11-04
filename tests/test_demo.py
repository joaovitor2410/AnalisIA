"""Demonstração sem rede: isolamento de visitantes, curadoria, orçamento e privacidade."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import streamlit as st
from pydantic import BaseModel
from pydantic_ai import models
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from streamlit.testing.v1 import AppTest

from olheiro import check_setup
from olheiro.config import PROJECT_ROOT, Settings
from olheiro.db import connect, connect_agent, load_raw_dir, scalar
from olheiro.demo import QuestionBudget, load_examples
from olheiro.sql_guard import UnsafeQueryError
from olheiro.storage import MemoryStore
from olheiro.telemetry import RunLog
from olheiro.ui import resources

APP = str(PROJECT_ROOT / "src/olheiro/app.py")
SQL = "SELECT count(DISTINCT season) AS seasons FROM raw.brasileirao"
SEED_QUESTION = "Quantas temporadas estão disponíveis?"
PRIVATE_QUESTION = "Análise privada da visitante Ana"


@pytest.fixture
def demo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with connect(tmp_path / "olheiro.duckdb") as con:
        load_raw_dir(con, PROJECT_ROOT / "data/raw")
    for variable, filename in {
        "DUCKDB_PATH": "olheiro.duckdb",
        "WORKSPACE_PATH": "personal.duckdb",
        "ANSWER_CACHE_PATH": "personal-cache.json",
        "DASHBOARD_PATH": "personal-dashboard.json",
        "RUNS_PATH": "runs.jsonl",
        "TRACES_PATH": "traces.jsonl",
    }.items():
        monkeypatch.setenv(variable, str(tmp_path / filename))
    # Estes arquivos não são válidos de propósito: ler o estado pessoal faria a demo falhar.
    for filename in ("personal.duckdb", "personal-cache.json", "personal-dashboard.json"):
        (tmp_path / filename).write_text("estado pessoal preservado", encoding="utf-8")
    monkeypatch.setenv("OLHEIRO_DEMO_MODE", "true")
    monkeypatch.setenv("OLHEIRO_DEMO_MODEL_ENABLED", "false")
    monkeypatch.setenv("OLHEIRO_DEMO_TOTAL_QUESTION_LIMIT", "10")
    monkeypatch.delenv("OLHEIRO_SESSION_QUESTION_LIMIT", raising=False)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    monkeypatch.setattr(resources, "build_model", lambda _: pytest.fail("Construiu o modelo"))
    st.cache_resource.clear()
    yield tmp_path
    st.cache_resource.clear()


def scripted_model(monkeypatch: pytest.MonkeyPatch, *, loop: bool = False) -> list[AgentInfo]:
    calls: list[AgentInfo] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(info)
        if loop:
            return ModelResponse(parts=[ToolCallPart("run_sql", {"query": SQL})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answerable": True, "answer": "Veja a evidência.", "sql": SQL},
                )
            ]
        )

    monkeypatch.setenv("OLHEIRO_DEMO_MODEL_ENABLED", "true")
    monkeypatch.setattr(resources, "build_model", lambda _: FunctionModel(respond))
    return calls


def test_default_demo_starts_without_model_and_reexecutes_all_examples(demo_env: Path) -> None:
    app = AppTest.from_file(APP, default_timeout=20).run()
    assert not app.exception
    examples = app.pills(key="example").options
    assert len(examples) == 6
    for question in examples:
        app.chat_input[0].set_value(question).run()
        assert not app.exception and not app.error
    assert app.session_state["model_questions"] == 0
    reports = [turn.report for turn in app.session_state["history"]]
    assert all(report.from_cache and report.usage.requests == 0 for report in reports)
    assert reports[0].evidence.rows == [(22,)]
    assert reports[1].evidence.rows == [("Corinthians", 4, 1), ("Palmeiras", 4, 1)]
    assert reports[-1].output.answerable is False and reports[-1].evidence is None
    assert app.session_state["demo_resources"].settings.session_question_limit == 5
    for filename in ("personal.duckdb", "personal-cache.json", "personal-dashboard.json"):
        assert (demo_env / filename).read_text() == "estado pessoal preservado"


def test_model_requires_explicit_opt_in_even_when_a_key_exists(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "chave-falsa-que-nao-deve-ser-usada")
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value(PRIVATE_QUESTION).run()
    assert not app.exception
    assert "desabilitadas" in app.error[0].value
    assert app.session_state["model_questions"] == 0
    assert RunLog(demo_env / "runs.jsonl").read() == []


def test_demo_diagnostics_accept_no_env_file_and_no_api_key(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        google_api_key=None,
        olheiro_demo_mode=True,
        olheiro_demo_model_enabled=False,
        duckdb_path=demo_env / "olheiro.duckdb",
        workspace_path=demo_env / "personal.duckdb",
    )
    monkeypatch.setattr(check_setup, "get_settings", lambda: settings)
    monkeypatch.setattr(check_setup, "PROJECT_ROOT", demo_env)
    checks = check_setup.run_checks()
    assert all(check.ok for check in checks), checks
    assert any("exemplos sem chave" in check.detail for check in checks)


def test_two_visitors_have_independent_dashboards_history_and_caches(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_model(monkeypatch)
    first = AppTest.from_file(APP, default_timeout=20).run()
    first.chat_input[0].set_value(PRIVATE_QUESTION).run()
    first.button(key="pin-0").click().run()
    first_resources = first.session_state["demo_resources"]
    assert len(first_resources.dashboard.read().items) == 1
    assert PRIVATE_QUESTION in first_resources.cache.questions()

    second = AppTest.from_file(APP, default_timeout=20).run()
    second_resources = second.session_state["demo_resources"]
    assert second_resources.dashboard.read().items == []
    assert PRIVATE_QUESTION not in second_resources.cache.questions()
    assert PRIVATE_QUESTION not in second.pills(key="example").options
    assert second.session_state["history"] == []
    assert second.session_state["conversation"].turn_count == 0
    assert first.session_state["conversation"] is not second.session_state["conversation"]
    assert first_resources.con is second_resources.con  # só os dados públicos são comuns
    assert first.session_state["deps"].con is not second.session_state["deps"].con
    assert first_resources.budget is second_resources.budget

    second.chat_input[0].set_value(PRIVATE_QUESTION).run()
    assert len(calls) == 2  # a resposta privada da primeira sessão não virou cache global
    first.run()
    assert len(first.session_state["demo_resources"].dashboard.read().items) == 1
    assert len(first.session_state["history"]) == 1


def test_session_limit_blocks_model_but_not_curated_questions(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLHEIRO_SESSION_QUESTION_LIMIT", "1")
    calls = scripted_model(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value(PRIVATE_QUESTION).run()
    app.chat_input[0].set_value("Outra análise privada").run()
    assert "perguntas livres" in app.error[0].value
    app.chat_input[0].set_value(SEED_QUESTION).run()
    assert not app.exception and len(calls) == 1
    assert app.session_state["history"][-1].report.from_cache is True
    assert app.session_state["model_questions"] == 1


def test_unavailable_persistent_budget_blocks_model_but_keeps_examples_available(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olheiro.config import Settings

    calls = scripted_model(monkeypatch)
    budget = Settings().olheiro_demo_budget_path
    budget.write_text('{"day":')
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value(PRIVATE_QUESTION).run()
    assert not app.exception and app.error
    assert "reservar a quota" in app.error[0].value
    assert not calls and app.session_state["model_questions"] == 0
    assert budget.read_text() == '{"day":'
    app.chat_input[0].set_value(SEED_QUESTION).run()
    assert not app.exception and app.session_state["history"][-1].report.from_cache
    assert not calls


def test_total_budget_is_shared_across_new_sessions_and_cache_is_free(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLHEIRO_DEMO_TOTAL_QUESTION_LIMIT", "1")
    calls = scripted_model(monkeypatch)
    first = AppTest.from_file(APP, default_timeout=20).run()
    first.chat_input[0].set_value(PRIVATE_QUESTION).run()
    second = AppTest.from_file(APP, default_timeout=20).run()
    second.chat_input[0].set_value("Pergunta de outro visitante").run()
    assert "demonstração foram esgotadas" in second.error[0].value
    assert second.session_state["model_questions"] == 0
    second.chat_input[0].set_value(SEED_QUESTION).run()
    assert len(calls) == 1 and not second.exception
    assert second.session_state["history"][-1].report.from_cache is True


def test_demo_hides_save_tool_and_bounds_the_agent_loop(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = scripted_model(monkeypatch, loop=True)
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value("Salve esta análise privada").run()
    assert not app.exception and app.error
    assert len(calls) == 6
    assert all("save_result" not in {tool.name for tool in call.function_tools} for call in calls)
    assert app.session_state["pending"] is None
    deps = app.session_state["deps"]
    assert deps.allow_saves is False
    assert (
        scalar(deps.con, "SELECT count(*) FROM duckdb_tables() WHERE database_name='workspace'")
        == 0
    )


def run_ops_page() -> None:
    from olheiro.ui.ops_page import ops_page

    ops_page()


def test_operation_is_blocked_even_when_invoked_directly(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RunLog, "read", lambda _: pytest.fail("Leu registros de outros visitantes"))
    app = AppTest.from_function(run_ops_page, default_timeout=20).run()
    assert not app.exception and not app.dataframe
    assert "modo pessoal" in app.info[0].value


def test_demo_omits_content_from_logs_and_disables_detailed_traces(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLHEIRO_TRACING", "file")
    monkeypatch.setenv("OLHEIRO_TRACE_CONTENT", "true")
    scripted_model(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value(PRIVATE_QUESTION).run()
    records = RunLog(demo_env / "runs.jsonl").read()
    assert len(records) == 1 and records[0].outcome == "answer"
    assert records[0].requests == 1 and records[0].question == "(conteúdo omitido)"
    assert PRIVATE_QUESTION not in (demo_env / "runs.jsonl").read_text()
    assert not (demo_env / "traces.jsonl").exists()
    assert app.session_state["demo_resources"].settings.olheiro_trace_content is False


def test_failed_model_does_not_write_question_or_exception_content_to_log(
    demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise UnexpectedModelBehavior("conteúdo privado na exceção")

    monkeypatch.setenv("OLHEIRO_DEMO_MODEL_ENABLED", "true")
    monkeypatch.setattr(resources, "build_model", lambda _: FunctionModel(fail))
    app = AppTest.from_file(APP, default_timeout=20).run()
    app.chat_input[0].set_value(PRIVATE_QUESTION).run()
    assert not app.exception and app.error
    (record,) = RunLog(demo_env / "runs.jsonl").read()
    assert record.outcome == "error" and record.error is None
    saved = (demo_env / "runs.jsonl").read_text()
    assert PRIVATE_QUESTION not in saved and "conteúdo privado" not in saved


def test_memory_store_reads_are_independent_and_failed_updates_roll_back() -> None:
    class Example(BaseModel):
        items: list[str] = []

    store = MemoryStore(Example)
    with store.update() as data:
        data.items.append("original")
    data.items.append("mutação fora da transação")
    copy = store.read()
    copy.items.append("mutação na cópia")
    assert store.read().items == ["original"]
    with pytest.raises(RuntimeError), store.update() as data:
        data.items.append("não deve persistir")
        raise RuntimeError("falhou")
    assert store.read().items == ["original"]


def test_budget_never_exceeds_limit_under_concurrency() -> None:
    budget = QuestionBudget(3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = list(pool.map(lambda _: budget.take(), range(100)))
    assert sum(allowed) == 3
    assert QuestionBudget(0).take() is False


def test_examples_refuse_unsafe_sql_before_execution(demo_env: Path) -> None:
    path = demo_env / "unsafe.toml"
    path.write_text(
        '[[examples]]\nquestion="q"\n[examples.output]\nanswerable=true\n'
        'answer="a"\nsql="DROP TABLE raw.teams"\n',
        encoding="utf-8",
    )
    with connect_agent(demo_env / "olheiro.duckdb", None) as con:
        with pytest.raises(UnsafeQueryError):
            load_examples(path, con)
        assert scalar(con, "SELECT count(*) FROM raw.teams") == 45


def test_memory_workspace_is_discarded_on_close(demo_env: Path) -> None:
    with connect_agent(demo_env / "olheiro.duckdb", None) as con:
        con.execute("CREATE TABLE workspace.ephemeral AS SELECT 1 AS n")
    with connect_agent(demo_env / "olheiro.duckdb", None) as con:
        assert (
            scalar(con, "SELECT count(*) FROM duckdb_tables() WHERE database_name='workspace'") == 0
        )
        assert scalar(con, "SELECT count(*) FROM raw.teams") == 45


@pytest.mark.parametrize(
    "fields",
    [
        'answerable=true\nanswer="sem evidência"\n',
        'answerable=true\nanswer="gráfico inválido"\nsql="SELECT 1 AS n"\n'
        '[examples.output.chart]\nkind="bar"\nx="missing"\ny="n"\ntitle="x"\n',
    ],
)
def test_invalid_examples_fail_before_becoming_cache(demo_env: Path, fields: str) -> None:
    path = demo_env / "invalid.toml"
    path.write_text('[[examples]]\nquestion="q"\n[examples.output]\n' + fields, encoding="utf-8")
    with connect_agent(demo_env / "olheiro.duckdb", None) as con:
        with pytest.raises(ValueError):
            load_examples(path, con)
