"""Página Dados: o que o agente enxerga (tabelas, glossário, regras), sem chamar o modelo."""

from typing import cast

import duckdb
import pandas as pd
import streamlit as st

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG, quote_identifier, scalar
from olheiro.semantic import Glossary, column_doc, columns_by_table
from olheiro.tools import column_profile, describe_db_error, query_rows
from olheiro.ui.components import show_table
from olheiro.ui.import_panel import show_import
from olheiro.ui.presentation import context_strip, page_intro
from olheiro.ui.quality_panel import show_quality
from olheiro.ui.resources import load_resources, session_deps
from olheiro.ui.semantic_editor import show_semantic_editor

PREVIEW_ROWS = 20


def data_page() -> None:
    resources = load_resources()
    con = session_deps(resources).con
    glossary = resources.glossary

    page_intro(
        "Conheça o ponto de partida",
        "Dados",
        "Explore tabelas, entenda as colunas e conheça as regras que orientam cada análise.",
    )
    tables = columns_by_table(con, "schema_name", RAW_SCHEMA)
    context_strip(resources.settings.dataset_title, len(tables), sum(map(len, tables.values())))
    if not resources.settings.olheiro_demo_mode:
        show_import(resources.settings)
        show_semantic_editor(resources.settings, con, glossary)
    if not glossary.tables:
        st.info(
            "Catálogo automático: nomes e tipos foram detectados. Descrições e regras de "
            "negócio ainda não foram informadas; o agente não deve supor unidades ou relações."
        )
    tabs = st.tabs([f"{RAW_SCHEMA}.{name}" for name in tables] + ["Regras de negócio", "Workspace"])
    for tab, (table, columns) in zip(tabs, tables.items(), strict=False):
        with tab:
            try:
                show_table_overview(con, glossary, table, columns)
                show_quality(con, table, str(resources.settings.duckdb_path))
            except duckdb.Error as error:
                st.error(describe_db_error(error))
    with tabs[-2]:
        if glossary.rules:
            st.markdown("\n".join(f"- {rule}" for rule in glossary.rules))
        else:
            st.info("Nenhuma regra de negócio informada para esta base.")
    with tabs[-1]:
        show_workspace(con)


def show_table_overview(
    con: duckdb.DuckDBPyConnection, glossary: Glossary, table: str, columns: list[tuple[str, str]]
) -> None:
    doc = glossary.tables.get(table)
    if doc is not None:
        st.markdown(doc.description)
    source = f"{RAW_SCHEMA}.{quote_identifier(table)}"
    rows = scalar(con, f"SELECT count(*) FROM {source}")
    st.caption(f"{rows} linhas · {len(columns)} colunas")
    with st.expander("Dicionário de colunas"):
        st.dataframe(
            pd.DataFrame(
                [
                    (name, kind, column_doc(glossary, table, name).description)
                    for name, kind in columns
                ],
                columns=["coluna", "tipo", "significado"],
            ),
            hide_index=True,
        )

    st.subheader("Prévia")
    preview_rows = st.select_slider(
        "Linhas na prévia", [10, 20, 30, 50], value=PREVIEW_ROWS, key=f"preview-{table}"
    )
    show_table(query_rows(con, f"SELECT * FROM {source}", max_rows=preview_rows))

    st.subheader("Perfil de uma coluna")
    column = st.selectbox("Coluna", [name for name, _ in columns], key=f"profile-{table}")
    profile = column_profile(con, table, column)
    st.caption(f"Tipo: {profile.data_type}")
    stats = dict(zip(profile.stats.columns, profile.stats.rows[0], strict=True))
    total, non_null = cast(int, stats["total_rows"]), cast(int, stats["non_null"])
    metrics = st.columns(3)
    metrics[0].metric("Registros", total, border=True)
    metrics[1].metric("Valores ausentes", total - non_null, border=True)
    metrics[2].metric("Valores distintos", cast(int, stats["distinct_values"]), border=True)
    with st.expander("Estatísticas completas · mínimo e máximo"):
        show_table(profile.stats)
    st.markdown("**Valores por frequência**")
    show_table(profile.top_values)


def show_workspace(con: duckdb.DuckDBPyConnection) -> None:
    saved = columns_by_table(con, "database_name", WORKSPACE_CATALOG)
    if not saved:
        st.info(
            "Nenhuma tabela salva. Peça ao agente para salvar um resultado na página Perguntar."
        )
    for table in saved:
        with st.expander(f"{WORKSPACE_CATALOG}.{table}"):
            show_table(
                query_rows(
                    con,
                    f"SELECT * FROM {WORKSPACE_CATALOG}.{quote_identifier(table)}",
                    max_rows=PREVIEW_ROWS,
                )
            )
