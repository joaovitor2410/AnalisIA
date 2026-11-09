"""Testes dos gráficos: a figura usa os dados do resultado, não do modelo."""

from pathlib import Path

import pytest

from olheiro.charts import ChartError, ChartSpec, build_figure, check_chart, save_figure
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


def test_metric_shows_single_value_with_label() -> None:
    evidence = QueryResult(columns=["team", "titles"], rows=[("Corinthians", 4)])
    spec = ChartSpec(kind="metric", x="team", y="titles", title="Mais títulos")
    indicator = build_figure(spec, evidence).data[0]
    assert indicator.type == "indicator"
    assert indicator.value == 4
    assert "Corinthians" in indicator.title.text


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        (ChartSpec(kind="bar", y="points", title="t"), "precisa da coluna x"),
        (ChartSpec(kind="line", x="season", y="gols", title="t"), "fora do resultado"),
        (ChartSpec(kind="bar", x="points", y="season_name", title="t"), "fora do resultado"),
    ],
)
def test_check_chart_rejects_specs_that_do_not_fit_the_result(spec: ChartSpec, reason: str) -> None:
    with pytest.raises(ChartError, match=reason):
        check_chart(spec, EVIDENCE)


def test_metric_needs_at_least_one_row() -> None:
    spec = ChartSpec(kind="metric", y="points", title="t")
    with pytest.raises(ChartError, match="pelo menos uma linha"):
        check_chart(spec, QueryResult(columns=["points"], rows=[]))


def test_metric_cannot_hide_a_tie_or_ignore_additional_rows() -> None:
    spec = ChartSpec(kind="metric", y="points", title="t")
    with pytest.raises(ChartError, match="única linha"):
        build_figure(spec, EVIDENCE)


def test_axes_cannot_select_ambiguous_duplicate_column_names() -> None:
    spec = ChartSpec(kind="bar", x="team", y="total", title="t")
    with pytest.raises(ChartError, match="repetido"):
        check_chart(spec, QueryResult(["team", "total", "total"], [("A", 1, 99)]))
