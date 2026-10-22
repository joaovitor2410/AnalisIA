"""Página Dados: o que o agente enxerga (tabelas, glossário, regras), sem chamar o modelo."""

import duckdb
import pandas as pd
import streamlit as st

from olheiro.db import RAW_SCHEMA, WORKSPACE_CATALOG
from olheiro.semantic import Glossary, column_doc, columns_by_table
from olheiro.tools import column_profile, query_rows
from olheiro.ui.components import show_table
from olheiro.ui.resources import load_resources, session_deps

PREVIEW_ROWS = 20


def data_page() -> None:
    resources = load_resources()
    con = session_deps(resources).con
    glossary = resources.glossary

    st.title("Dados")
    st.caption(
        "O que o agente enxerga: as tabelas, o significado de cada coluna (glossário) e as "
        "regras de negócio que ele recebe nas instruções."
    )
    tables = columns_by_table(con, "schema_name", RAW_SCHEMA)
    tabs = st.tabs([f"{RAW_SCHEMA}.{name}" for name in tables] + ["Regras de negócio", "Workspace"])
    for tab, (table, columns) in zip(tabs, tables.items(), strict=False):
        with tab:
            show_table_overview(con, glossary, table, columns)
    with tabs[-2]:
        st.markdown("\n".join(f"- {rule}" for rule in glossary.rules))
    with tabs[-1]:
        show_workspace(con)


def show_table_overview(
    con: duckdb.DuckDBPyConnection, glossary: Glossary, table: str, columns: list[tuple[str, str]]
) -> None:
    doc = glossary.tables.get(table)
    if doc is not None:
        st.markdown(doc.description)
    (rows,) = con.execute(f'SELECT count(*) FROM {RAW_SCHEMA}."{table}"').fetchone()
    st.caption(f"{rows} linhas · {len(columns)} colunas")
    st.dataframe(
        pd.DataFrame(
            [(name, kind, column_doc(glossary, table, name).description) for name, kind in columns],
            columns=["coluna", "tipo", "significado"],
        ),
        hide_index=True,
    )

    st.subheader("Prévia")
    show_table(query_rows(con, f'SELECT * FROM {RAW_SCHEMA}."{table}"', max_rows=PREVIEW_ROWS))

    st.subheader("Perfil de uma coluna")
    column = st.selectbox("Coluna", [name for name, _ in columns], key=f"profile-{table}")
    profile = column_profile(con, table, column)
    st.caption(f"Tipo: {profile.data_type}")
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
                    con, f'SELECT * FROM {WORKSPACE_CATALOG}."{table}"', max_rows=PREVIEW_ROWS
                )
            )
