"""Testes dos gráficos: a figura usa os dados do resultado, não do modelo."""

from pathlib import Path

from olheiro.agent import ChartSpec
from olheiro.charts import build_figure, save_figure
from olheiro.tools import QueryResult

EVIDENCE = QueryResult(columns=["season", "points"], rows=[(2019, 90), (2020, 71)])


def test_bar_chart_uses_evidence_columns() -> None:
    spec = ChartSpec(kind="bar", x="season", y="points", title="Pontos")
    trace = build_figure(spec, EVIDENCE).data[0]
    assert trace.type == "bar"
    assert list(trace.x) == [2019, 2020]
    assert list(trace.y) == [90, 71]


def test_line_chart_is_a_scatter_with_lines() -> None:
    spec = ChartSpec(kind="line", x="season", y="points", title="Pontos")
    trace = build_figure(spec, EVIDENCE).data[0]
    assert trace.type == "scatter"
    assert trace.mode == "lines+markers"


def test_save_figure_writes_html(tmp_path: Path) -> None:
    spec = ChartSpec(kind="bar", x="season", y="points", title="Pontos")
    path = save_figure(build_figure(spec, EVIDENCE), tmp_path / "exports")
    assert path.suffix == ".html"
    assert "Pontos" in path.read_text(encoding="utf-8")
