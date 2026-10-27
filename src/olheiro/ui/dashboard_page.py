"""Página Dashboard: as respostas fixadas, redesenhadas a partir do SQL salvo, sem o modelo."""

from collections.abc import Sequence

import streamlit as st

from olheiro.dashboard import DashboardItem, RenderedItem, render_item
from olheiro.ui.components import show_metric, show_table
from olheiro.ui.presentation import empty_state, page_intro, summary_tiles
from olheiro.ui.resources import AppResources, load_resources, session_deps

KPIS_PER_ROW = 4
CARDS_PER_ROW = 2


def dashboard_page() -> None:
    resources = load_resources()
    con = session_deps(resources).con

    page_intro(
        "Descobertas que ficam",
        "Dashboard",
        "Suas análises em um só lugar. Os dados são atualizados pelo SQL, sem novas chamadas à IA.",
    )
    st.caption(f"Base ativa: {resources.settings.dataset_title}")
    items = resources.dashboard.read().items
    if not items:
        empty_state(
            "Seu próximo insight merece um lugar aqui",
            "Transforme respostas em um painel que você pode consultar de novo. "
            "Fixe uma análise na página Perguntar para começar.",
        )
        st.info("Nada fixado ainda. Na página Perguntar, use **Fixar no dashboard** numa resposta.")
        return
    metrics = sum(item.chart is not None and item.chart.kind == "metric" for item in items)
    charts = sum(item.chart is not None and item.chart.kind != "metric" for item in items)
    summary_tiles(
        [("Análises fixadas", len(items)), ("Indicadores", metrics), ("Gráficos", charts)]
    )
    search = st.text_input(
        "Buscar análise",
        placeholder="Busque por título ou pergunta…",
        key="dashboard-search",
        icon=":material/search:",
    )
    kind = st.segmented_control(
        "Visualização",
        ["Todas", "Indicadores", "Gráficos", "Tabelas"],
        default="Todas",
        required=True,
        key="dashboard-kind",
    )
    items = filter_items(items, search, kind or "Todas")
    if not items:
        empty_state("Nenhuma análise com esses filtros", "Tente outro termo ou selecione Todas.")
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


def filter_items(items: list[DashboardItem], search: str, kind: str) -> list[DashboardItem]:
    """Filtra metadados locais; consultas e modelo não participam da busca."""
    term = search.strip().casefold()

    def matches(item: DashboardItem) -> bool:
        if term not in f"{item.title} {item.question}".casefold():
            return False
        if kind == "Indicadores":
            return item.chart is not None and item.chart.kind == "metric"
        if kind == "Gráficos":
            return item.chart is not None and item.chart.kind != "metric"
        return item.chart is None if kind == "Tabelas" else True

    return [item for item in items if matches(item)]


def chunks(items: Sequence[RenderedItem], size: int) -> list[Sequence[RenderedItem]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def show_card(rendered: RenderedItem, resources: AppResources) -> None:
    item, evidence = rendered.item, rendered.evidence
    with st.container(border=True):
        if rendered.error is not None or evidence is None:
            st.markdown(f"**{item.title}**")
            st.error(f"Não foi possível atualizar: {rendered.error}", icon=":material/error:")
        elif item.chart is not None and item.chart.kind == "metric":
            show_metric(item.chart, evidence)
        elif rendered.figure is not None:
            st.plotly_chart(rendered.figure, key=f"dashboard-{item.id}")
        else:
            st.markdown(f"**{item.title}**")
            show_table(evidence)

        with st.expander("Pergunta e SQL"):
            st.caption(item.question)
            st.code(item.sql, language="sql")
        if st.button("Remover", key=f"remove-{item.id}", icon=":material/delete:", type="tertiary"):
            resources.dashboard.unpin(item.id)
            st.rerun()
