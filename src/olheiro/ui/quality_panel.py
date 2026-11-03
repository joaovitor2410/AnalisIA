"""Diagnósticos sob demanda para não varrer todas as tabelas a cada interação."""

from dataclasses import asdict

import duckdb
import pandas as pd
import streamlit as st

from olheiro.quality import check_relationship, table_quality
from olheiro.semantic import columns_by_table
from olheiro.ui.components import show_table


def show_quality(con: duckdb.DuckDBPyConnection, table: str, identity: str) -> None:
    key = f"quality-{identity}-{table}"
    with st.expander("Qualidade e possíveis relacionamentos"):
        st.caption("Diagnóstico calculado nos dados atuais, sem chamar o modelo.")
        if st.button("Analisar qualidade", key=key):
            try:
                report = table_quality(con, table)
                st.metric("Linhas duplicadas excedentes", report.duplicate_rows)
                st.dataframe(
                    pd.DataFrame([asdict(column) for column in report.columns]).rename(
                        columns={
                            "column": "coluna",
                            "data_type": "tipo",
                            "nulls": "nulos",
                            "distinct": "distintos",
                            "candidate_key": "candidata a chave",
                        }
                    ),
                    hide_index=True,
                )
                st.caption(
                    "Candidata a chave: coluna única, sem nulos, em tabela não vazia. "
                    "A definição da chave de negócio ainda precisa ser confirmada."
                )
                for sql in report.sql:
                    st.code(sql, language="sql")
            except (duckdb.Error, ValueError) as error:
                st.error(f"Não foi possível analisar a qualidade: {error}")
        catalog = columns_by_table(con, "schema_name", "raw")
        left = st.selectbox(
            "Coluna de origem", [name for name, _ in catalog[table]], key=key + "-left"
        )
        right_table = st.selectbox("Tabela de destino", list(catalog), key=key + "-table")
        right = st.selectbox(
            "Coluna de destino", [name for name, _ in catalog[right_table]], key=key + "-right"
        )
        if st.button("Verificar relacionamento", key=key + "-join"):
            try:
                relationship = check_relationship(con, table, left, right_table, right)
                show_table(relationship.evidence)
                st.code(relationship.sql, language="sql")
                if relationship.compatible:
                    st.success(f"Compatível nos dados atuais: {relationship.cardinality}.")
                else:
                    st.warning("Cobertura ou unicidade insuficiente; confira nulos e chaves órfãs.")
                st.caption(
                    "Compatibilidade estatística não confirma o significado do relacionamento."
                )
            except (duckdb.Error, ValueError) as error:
                st.error(str(error))
