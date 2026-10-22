"""Página Dashboard: as respostas fixadas, redesenhadas a partir do SQL salvo, sem o modelo."""

from collections.abc import Sequence

import streamlit as st

from olheiro.dashboard import RenderedItem, render_item
from olheiro.ui.components import show_metric, show_table
from olheiro.ui.resources import AppResources, load_resources, session_deps

KPIS_PER_ROW = 4
CARDS_PER_ROW = 2


def dashboard_page() -> None:
    resources = load_resources()
    con = session_deps(resources).con

    st.title("Dashboard")
    st.caption(
        "Respostas fixadas. Cada item guarda o SQL e a visualização: ao abrir, o SQL roda de "
        "novo no banco, sem chamar o modelo."
    )
    items = resources.dashboard.read().items
    if not items:
        st.info("Nada fixado ainda. Na página Perguntar, use **Fixar no dashboard** numa resposta.")
        return

    rendered = [render_item(item, con) for item in items]
    kpis = [r for r in rendered if r.item.chart is not None and r.item.chart.kind == "metric"]
    cards = [r for r in rendered if r not in kpis]
    for row in chunks(kpis, KPIS_PER_ROW):
        for column, item in zip(st.columns(KPIS_PER_ROW), row, strict=False):
            with column:
                show_card(item, resources)
    for row in chunks(cards, CARDS_PER_ROW):
        for column, item in zip(st.columns(CARDS_PER_ROW), row, strict=False):
            with column:
                show_card(item, resources)


def chunks(items: Sequence[RenderedItem], size: int) -> list[Sequence[RenderedItem]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def show_card(rendered: RenderedItem, resources: AppResources) -> None:
    item = rendered.item
    with st.container(border=True):
        if rendered.error is not None:
            st.markdown(f"**{item.title}**")
            st.error(f"Não foi possível atualizar: {rendered.error}", icon=":material/error:")
        elif item.chart is not None and item.chart.kind == "metric":
            show_metric(item.chart, rendered.evidence)
        elif rendered.figure is not None:
            st.plotly_chart(rendered.figure, key=f"dashboard-{item.id}")
        else:
            st.markdown(f"**{item.title}**")
            show_table(rendered.evidence)

        with st.expander("Pergunta e SQL"):
            st.caption(item.question)
            st.code(item.sql, language="sql")
        if st.button("Remover", key=f"remove-{item.id}", icon=":material/delete:", type="tertiary"):
            resources.dashboard.unpin(item.id)
            st.rerun()
