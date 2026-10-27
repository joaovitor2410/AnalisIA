"""Visualizações da evidência (Plotly): o modelo escolhe tipo e colunas; os dados vêm do SQL.

ChartSpec é a especificação serializável de uma visualização: o agente a devolve e o
dashboard a guarda. A mesma figura serve à CLI (HTML) e ao Streamlit.
"""

from datetime import datetime
from numbers import Number
from pathlib import Path
from typing import Literal

import plotly.graph_objects as go
from pydantic import BaseModel, Field

from olheiro.tools import QueryResult


class ChartSpec(BaseModel):
    """Visualização sugerida pelo modelo. Os dados vêm do SQL de evidência, não do modelo."""

    kind: Literal["bar", "line", "metric"] = Field(
        description=(
            "'bar' para comparar categorias; 'line' para evolução ao longo do tempo; "
            "'metric' para um número em destaque (KPI), lido da primeira linha do resultado."
        )
    )
    x: str | None = Field(
        default=None,
        description="Coluna do eixo X (obrigatória em bar/line). Em metric, coluna do rótulo.",
    )
    y: str = Field(description="Coluna numérica do resultado: eixo Y, ou o valor do KPI.")
    title: str = Field(description="Título curto, em português.")


class ChartError(ValueError):
    """A especificação não combina com o resultado do SQL."""


def check_chart(spec: ChartSpec, evidence: QueryResult) -> None:
    """Colunas precisam existir no resultado, Y precisa ser numérico, bar/line precisam de X."""
    if spec.kind != "metric" and spec.x is None:
        raise ChartError(f"Gráfico '{spec.kind}' precisa da coluna x.")
    missing = [name for name in (spec.x, spec.y) if name and name not in evidence.columns]
    if missing:
        raise ChartError(
            f"O gráfico usa colunas fora do resultado do SQL: {missing}. "
            f"Colunas disponíveis: {evidence.columns}."
        )
    y_values = evidence.column_values(spec.y)
    if not all(value is None or isinstance(value, Number) for value in y_values):
        raise ChartError(f"A coluna '{spec.y}' precisa ser numérica.")
    if spec.kind == "metric" and not evidence.rows:
        raise ChartError("Um KPI (metric) precisa de pelo menos uma linha no resultado.")


def build_figure(spec: ChartSpec, evidence: QueryResult) -> go.Figure:
    """Monta a figura a partir do resultado real da consulta."""
    if spec.kind == "metric":
        return metric_figure(spec, evidence)
    if spec.x is None:  # check_chart já recusa; aqui protege quem chamar sem validar
        raise ChartError(f"Gráfico '{spec.kind}' precisa da coluna x.")
    x, y = evidence.column_values(spec.x), evidence.column_values(spec.y)
    trace = (
        go.Bar(x=x, y=y, marker_color="#6558E8", marker_cornerradius=5)
        if spec.kind == "bar"
        else go.Scatter(
            x=x,
            y=y,
            mode="lines+markers",
            line={"color": "#6558E8", "width": 3},
            marker={"size": 7},
        )
    )
    figure = go.Figure(trace)
    figure.update_layout(
        title=spec.title, xaxis_title=spec.x, yaxis_title=spec.y, template="plotly_white"
    )
    figure.update_layout(
        font={"family": "Arial, sans-serif", "color": "#526079"},
        title_font={"color": "#18243B", "size": 19},
        margin={"t": 65, "b": 45, "l": 20, "r": 20},
        hoverlabel={"bgcolor": "#111C30", "font_color": "#FFFFFF"},
    )
    figure.update_xaxes(showgrid=False, zeroline=False)
    figure.update_yaxes(gridcolor="#EDF0F7", zeroline=False)
    return figure


def metric_figure(spec: ChartSpec, evidence: QueryResult) -> go.Figure:
    """KPI: o valor de y na primeira linha, com o valor de x (se houver) como rótulo."""
    value = evidence.column_values(spec.y)[0]
    title = spec.title
    if spec.x is not None:
        title += f"<br><span style='font-size:0.8em'>{evidence.column_values(spec.x)[0]}</span>"
    figure = go.Figure(go.Indicator(mode="number", value=value, title={"text": title}))
    figure.update_layout(template="plotly_white", height=220)
    return figure


def save_figure(figure: go.Figure, exports_dir: Path) -> Path:
    """Salva em HTML interativo. O plotly.js vem da CDN para o arquivo ficar leve."""
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / f"chart-{datetime.now():%Y%m%d-%H%M%S}.html"
    figure.write_html(path, include_plotlyjs="cdn")
    return path
