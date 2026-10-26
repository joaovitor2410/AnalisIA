"""Dashboard: respostas fixadas como SQL + visualização, redesenhadas sem chamar o modelo.

O LLM cria a análise uma vez; o painel só valida e reexecuta o SQL guardado. Fica barato,
rápido e sempre com os dados atuais.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import plotly.graph_objects as go
from pydantic import BaseModel, Field

from olheiro.agent import AgentReport
from olheiro.charts import ChartError, ChartSpec, build_figure, check_chart
from olheiro.sql_guard import UnsafeQueryError, check_query
from olheiro.storage import JsonFile, MemoryStore
from olheiro.tools import QueryResult, query_rows


class DashboardItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str
    question: str
    sql: str
    chart: ChartSpec | None = None  # sem visualização, o item é uma tabela
    created_at: datetime = Field(default_factory=datetime.now)


class Dashboard(BaseModel):
    items: list[DashboardItem] = []


@dataclass(frozen=True)
class RenderedItem:
    """Item pronto para exibir: a evidência e a figura, ou o motivo de não renderizar."""

    item: DashboardItem
    evidence: QueryResult | None = None
    figure: go.Figure | None = None
    error: str | None = None


class DashboardStore:
    def __init__(self, path: Path | None) -> None:
        self.file = JsonFile(path, Dashboard) if path is not None else MemoryStore(Dashboard)

    def read(self) -> Dashboard:
        return self.file.read()

    def pin(self, question: str, report: AgentReport) -> DashboardItem:
        """Fixa uma resposta. Só respostas com evidência (SQL válido) podem ir para o painel."""
        output = report.output
        if not output.answerable or output.sql is None:
            raise ValueError("Só respostas com evidência (SQL) podem ser fixadas.")
        check_query(output.sql)
        title = output.chart.title if output.chart else question
        item = DashboardItem(title=title, question=question, sql=output.sql, chart=output.chart)
        with self.file.update() as dashboard:
            dashboard.items.append(item)
        return item

    def unpin(self, item_id: str) -> None:
        with self.file.update() as dashboard:
            dashboard.items = [item for item in dashboard.items if item.id != item_id]


def render_item(item: DashboardItem, con: duckdb.DuckDBPyConnection) -> RenderedItem:
    """Valida e reexecuta o SQL do item (o arquivo pode ter sido editado à mão) e monta a figura."""
    try:
        check_query(item.sql)
        evidence = query_rows(con, item.sql)
        if item.chart is None:
            return RenderedItem(item, evidence)
        check_chart(item.chart, evidence)
        return RenderedItem(item, evidence, build_figure(item.chart, evidence))
    except (UnsafeQueryError, ChartError, duckdb.Error) as error:
        return RenderedItem(item, error=str(error))
