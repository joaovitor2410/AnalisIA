"""Gráficos da evidência (Plotly): o modelo escolhe tipo e colunas; os dados vêm do SQL."""

from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go

from olheiro.agent import ChartSpec
from olheiro.tools import QueryResult


def build_figure(spec: ChartSpec, evidence: QueryResult) -> go.Figure:
    """Monta a figura a partir do resultado real da consulta."""
    x, y = evidence.column_values(spec.x), evidence.column_values(spec.y)
    trace = go.Bar(x=x, y=y) if spec.kind == "bar" else go.Scatter(x=x, y=y, mode="lines+markers")
    figure = go.Figure(trace)
    figure.update_layout(
        title=spec.title, xaxis_title=spec.x, yaxis_title=spec.y, template="plotly_white"
    )
    return figure


def save_figure(figure: go.Figure, exports_dir: Path) -> Path:
    """Salva em HTML interativo. O plotly.js vem da CDN para o arquivo ficar leve."""
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / f"chart-{datetime.now():%Y%m%d-%H%M%S}.html"
    figure.write_html(path, include_plotlyjs="cdn")
    return path
