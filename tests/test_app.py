"""Testes da interface Streamlit com o AppTest (headless): sem navegador, sem rede, sem cota."""

from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import pytest
import streamlit as st
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage
from streamlit.testing.v1 import AppTest

from olheiro.agent import AnalysisAnswer, build_report
from olheiro.cache import AnswerCache
from olheiro.charts import ChartSpec
from olheiro.config import PROJECT_ROOT, get_settings
from olheiro.dashboard import DashboardItem
from olheiro.datasets import cache_revision, dataset_identity
from olheiro.db import WorkspaceInUseError, connect, load_raw_dir
from olheiro.ui import resources

models.ALLOW_MODEL_REQUESTS = False

TITLES_SQL = (
    "SELECT team, count(*) AS titles FROM raw.brasileirao WHERE place = 1 "
    "GROUP BY team ORDER BY titles DESC, team LIMIT 1"
)
CACHED_QUESTION = "Qual time tem mais títulos?"


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Banco temporário com os CSVs reais e todos os arquivos do app apontando para tmp_path."""
    with connect(tmp_path / "olheiro.duckdb") as setup:
        load_raw_dir(setup, PROJECT_ROOT / "data" / "raw")
    for variable, file in {
        "DUCKDB_PATH": "olheiro.duckdb",
        "WORKSPACE_PATH": "workspace.duckdb",
        "ANSWER_CACHE_PATH": "answer_cache.json",
        "DASHBOARD_PATH": "dashboard.json",
    }.items():
        monkeypatch.setenv(variable, str(tmp_path / file))
    st.cache_resource.clear()  # cada teste monta os próprios recursos
    yield tmp_path
    st.cache_resource.clear()


def cache_answer(tmp_path: Path) -> None:
    output = AnalysisAnswer(
        answerable=True,
        answer="Corinthians e Palmeiras empatam com 4 títulos.",
        sql=TITLES_SQL,
        chart=ChartSpec(kind="metric", x="team", y="titles", title="Mais títulos"),
    )
    with connect(tmp_path / "olheiro.duckdb", read_only=True) as con:
        report = build_report(output, con, "gemini-teste", RunUsage(), [])
    AnswerCache(tmp_path / "answer_cache.json", cache_revision(get_settings())).store(
        CACHED_QUESTION, report
    )


def page_app(page: Callable[[], None]) -> AppTest:
    return AppTest.from_function(page, default_timeout=20)


def run_ask_page() -> None:
    from olheiro.ui.ask_page import ask_page

    ask_page()


def run_dashboard_page() -> None:
    from olheiro.ui.dashboard_page import dashboard_page

    dashboard_page()


def run_data_page() -> None:
    from olheiro.ui.data_page import data_page

    data_page()


@pytest.mark.parametrize("limit", [None, "0", "5"])
def test_full_app_starts_on_the_ask_page(
    app_env: Path, monkeypatch: pytest.MonkeyPatch, limit: str | None
) -> None:
    if limit is not None:
        monkeypatch.setenv("OLHEIRO_SESSION_QUESTION_LIMIT", limit)
    else:
        monkeypatch.delenv("OLHEIRO_SESSION_QUESTION_LIMIT", raising=False)
    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "olheiro" / "app.py"), default_timeout=20)
    app.run()
    assert not app.exception
    assert app.title[0].value == "Perguntar aos dados"


def test_data_page_shows_tables_glossary_and_profile(app_env: Path) -> None:
    app = page_app(run_data_page).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs][:2] == ["raw.brasileirao", "raw.teams"]
    assert "Classificação final" in app.markdown[0].value  # descrição vinda do glossário
    assert app.selectbox(key="profile-brasileirao").value == "season"


def test_data_page_reports_profile_timeout_without_breaking_other_tabs(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from olheiro.ui import data_page

    original = data_page.column_profile

    def profile(con: duckdb.DuckDBPyConnection, table: str, column: str) -> object:
        if table == "brasileirao":
            raise duckdb.InterruptException()
        return original(con, table, column)

    monkeypatch.setattr(data_page, "column_profile", profile)
    app = page_app(run_data_page).run()
    assert not app.exception
    assert "interrompida" in app.error[0].value
    assert app.selectbox(key="profile-teams").value == "team"


def test_workspace_conflict_has_a_clear_message_and_recovers_on_retry(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = resources.connect_agent

    def locked(*args: object) -> None:
        raise WorkspaceInUseError(app_env / "workspace.duckdb", "Conflicting lock (PID 12345)")

    monkeypatch.setattr(resources, "connect_agent", locked)
    app = AppTest.from_file(str(PROJECT_ROOT / "src/olheiro/app.py"), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "Workspace em uso"
    assert "PID 12345" in app.error[0].value
    assert "WORKSPACE_PATH" in app.error[0].value
    monkeypatch.setattr(resources, "connect_agent", original)
    app.button(key="retry-workspace").click().run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Perguntar aos dados"


def test_cached_question_is_answered_without_the_model(app_env: Path) -> None:
    cache_answer(app_env)
    app = page_app(run_ask_page).run()
    assert app.pills(key="example").options == [CACHED_QUESTION]  # vira atalho

    app.chat_input[0].set_value(f"  {CACHED_QUESTION}  ").run()

    assert not app.exception
    assert app.metric[0].value == "4"  # KPI reexecutado no banco
    assert any("Resposta do cache" in caption.value for caption in app.caption)


def test_session_limit_blocks_new_model_questions(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLHEIRO_SESSION_QUESTION_LIMIT", "0")
    # O teste mede o limite, não a presença da chave local; também roda na CI sem .env.
    monkeypatch.setattr(
        resources,
        "build_model",
        lambda settings: FunctionModel(lambda messages, info: pytest.fail("Chamou o modelo")),
    )
    app = page_app(run_ask_page).run()

    app.chat_input[0].set_value("Quem foi o campeão de 2019?").run()

    assert "perguntas livres" in app.error[0].value


def scripted_model(*responses: Callable[[AgentInfo], ModelResponse]) -> FunctionModel:
    steps = list(responses)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return steps.pop(0)(info)

    return FunctionModel(respond)


def test_save_needs_the_users_click(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = {"answerable": True, "answer": "Tabela salva.", "sql": TITLES_SQL}
    model = scripted_model(
        lambda info: ModelResponse(
            parts=[ToolCallPart("save_result", {"name": "maior_campeao", "query": TITLES_SQL})]
        ),
        lambda info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, final)]),
    )
    monkeypatch.setattr(resources, "build_model", lambda settings: model)
    app = page_app(run_ask_page).run()

    app.chat_input[0].set_value("Salve o maior campeão").run()
    assert "maior_campeao" in app.info[0].value  # pausou: pede aprovação, nada gravado ainda
    assert not saved_tables()

    app.button(key="approve").click().run()

    assert not app.exception
    assert saved_tables() == ["maior_campeao"]
    assert "Tabela salva." in [block.value for block in app.markdown]


def saved_tables() -> list[str]:
    """Pela conexão do próprio app: o DuckDB não anexa o mesmo arquivo duas vezes."""
    rows = (
        resources.load_resources()
        .con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'workspace'")
        .fetchall()
    )
    return [name for (name,) in rows]


def test_dashboard_redraws_pinned_items_from_sql(app_env: Path) -> None:
    store = resources.DashboardStore(app_env / "dashboard.json")
    with store.file.update() as dashboard:
        dashboard.namespace = dataset_identity(get_settings())
        dashboard.items = [
            DashboardItem(
                title="Mais títulos",
                question=CACHED_QUESTION,
                sql=TITLES_SQL,
                chart=ChartSpec(kind="metric", x="team", y="titles", title="Mais títulos"),
            ),
            DashboardItem(title="Tabela", question="q", sql="SELECT 1 AS x"),
        ]
    app = page_app(run_dashboard_page).run()

    assert not app.exception
    assert app.metric[0].label == "Mais títulos · Corinthians"
    assert app.metric[0].value == "4"
    assert len(app.dataframe) == 1  # o item sem visualização vira tabela


def test_empty_dashboard_explains_how_to_pin(app_env: Path) -> None:
    app = page_app(run_dashboard_page).run()
    assert "Fixar no dashboard" in app.info[0].value


def test_suggestion_is_editable_and_only_calls_model_after_explicit_send(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        received.extend(
            str(part.content)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answerable": True, "answer": "Veja os dados.", "sql": TITLES_SQL},
                )
            ]
        )

    monkeypatch.setattr(resources, "build_model", lambda settings: FunctionModel(respond))
    app = page_app(run_ask_page).run()
    app.button(key="suggest-overview").click().run()
    assert not app.exception and not received
    assert app.session_state["model_questions"] == 0
    assert "raw." in app.text_area(key="question_draft").value
    question = "Quais os maiores campeões?"
    app.text_area(key="question_draft").set_value(question).run()
    assert not received
    app.button(key="send-draft").click().run()
    assert not app.exception
    assert received == [question] and app.session_state["model_questions"] == 1
    assert not app.session_state["question_draft"]
    assert app.get("download_button")  # evidência pode ser exportada sem perguntar de novo


def test_new_exploration_preserves_quota_and_pinned_analysis(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_answer(app_env)
    app = page_app(run_ask_page).run()
    app.chat_input[0].set_value(CACHED_QUESTION).run()
    app.button(key="pin-0").click().run()
    app.session_state["model_questions"] = 3
    app.button(key="new-exploration").click().run()
    assert not app.exception and app.session_state["history"] == []
    assert app.session_state["model_questions"] == 3
    assert app.session_state["conversation"].turn_count == 0
    assert len(resources.load_resources().dashboard.read().items) == 1


def test_ui_continues_cached_analysis_and_new_exploration_clears_model_context(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import TextPart, UserPromptPart

    received: list[list[str]] = []
    followup = "E quantos pontos em 2020?"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        received.append(
            [
                str(part.content)
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart | TextPart)
            ]
        )
        fields: dict[str, object] = (
            {
                "answerable": True,
                "answer": "Flamengo: 71 pontos.",
                "sql": "SELECT team, points FROM raw.brasileirao WHERE season=2020 AND place=1",
            }
            if len(received) == 1
            else {
                "answerable": False,
                "answer": "Qual competição e qual equipe você quer analisar?",
            }
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, fields)])

    monkeypatch.setattr(resources, "build_model", lambda _: FunctionModel(respond))
    cache_answer(app_env)
    app = page_app(run_ask_page).run()
    app.chat_input[0].set_value(CACHED_QUESTION).run()
    app.chat_input[0].set_value(followup).run()
    assert not app.exception and not app.error
    assert received[0][0] == CACHED_QUESTION and TITLES_SQL in received[0][1]
    assert app.session_state["history"][-1].report.evidence.rows == [("Flamengo", 71)]
    assert app.session_state["conversation"].turn_count == 2
    assert followup not in app.pills(key="example").options
    app.button(key="new-exploration").click().run()
    app.chat_input[0].set_value(followup).run()
    assert not app.exception and received[1] == [followup]
    assert not app.session_state["history"][-1].report.output.answerable
    assert app.session_state["model_questions"] == 2


def test_ready_question_restarts_context_and_stays_free_after_a_continuation(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLHEIRO_SESSION_QUESTION_LIMIT", "1")
    model = scripted_model(
        lambda info: ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"answerable": True, "answer": "Confira.", "sql": TITLES_SQL},
                )
            ]
        )
    )
    monkeypatch.setattr(resources, "build_model", lambda _: model)
    cache_answer(app_env)
    app = page_app(run_ask_page).run()
    app.chat_input[0].set_value(CACHED_QUESTION).run()
    app.chat_input[0].set_value("E os pontos?").run()
    assert app.session_state["conversation"].turn_count == 2
    app.pills(key="example").set_value(CACHED_QUESTION).run()
    assert not app.exception and not app.error
    assert app.session_state["history"][-1].report.from_cache
    assert app.session_state["model_questions"] == 1
    assert app.session_state["conversation"].turn_count == 1


def test_dashboard_filters_without_changing_pinned_items(app_env: Path) -> None:
    store = resources.DashboardStore(app_env / "dashboard.json", dataset_identity(get_settings()))
    with connect(app_env / "olheiro.duckdb", read_only=True) as con:
        for question, chart in [
            ("Indicador de títulos", ChartSpec(kind="metric", y="titles", title="Títulos")),
            ("Tabela de campeões", None),
        ]:
            report = build_report(
                AnalysisAnswer(answerable=True, answer="Resultado", sql=TITLES_SQL, chart=chart),
                con,
                "teste",
                RunUsage(),
                [],
            )
            store.pin(question, report)
    app = page_app(run_dashboard_page).run()
    app.segmented_control(key="dashboard-kind").set_value("Tabelas").run()
    assert not app.exception and not app.metric
    assert len(app.dataframe) == 1
    app.text_input(key="dashboard-search").set_value("inexistente").run()
    assert not app.exception and not app.dataframe
    assert len(store.read().items) == 2


def test_pending_approval_disables_cached_examples(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_answer(app_env)
    monkeypatch.setattr(
        resources,
        "build_model",
        lambda settings: scripted_model(
            lambda info: ModelResponse(
                parts=[ToolCallPart("save_result", {"name": "pendente", "query": TITLES_SQL})]
            )
        ),
    )
    app = page_app(run_ask_page).run()
    app.chat_input[0].set_value("Salve os campeões.").run()
    assert not app.exception and app.pills(key="example").disabled
    assert app.chat_input[0].disabled
    assert not saved_tables()
