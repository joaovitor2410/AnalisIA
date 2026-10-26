"""Testes da interface Streamlit com o AppTest (headless): sem navegador, sem rede, sem cota."""

from collections.abc import Callable, Iterator
from pathlib import Path

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
from olheiro.config import PROJECT_ROOT
from olheiro.dashboard import DashboardItem
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
    AnswerCache(tmp_path / "answer_cache.json").store(CACHED_QUESTION, report)


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

    app.chat_input[0].set_value("qual time tem mais TITULOS").run()  # normalização da chave

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
