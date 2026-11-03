"""Editor pessoal de descrições, unidades e regras, separado das ferramentas do agente."""

import duckdb
import streamlit as st

from olheiro.config import Settings
from olheiro.semantic import ColumnDoc, Glossary, TableDoc, column_doc, columns_by_table
from olheiro.semantic_store import manifest_revision, save_dataset_glossary


def show_semantic_editor(
    settings: Settings, con: duckdb.DuckDBPyConnection, glossary: Glossary
) -> None:
    if settings.olheiro_demo_mode:
        return
    with st.expander("Editar descrições e regras"):
        if settings.olheiro_dataset is None:
            st.info(
                "Importe uma base pessoal para editar sua semântica. "
                "O exemplo mantém as regras originais."
            )
            return
        tables = columns_by_table(con, "schema_name", "raw")
        table = st.selectbox("Tabela para documentar", list(tables), key="semantic-table")
        column = st.selectbox(
            "Coluna para documentar", [name for name, _ in tables[table]], key="semantic-column"
        )
        revision = manifest_revision(settings.olheiro_dataset)
        current = settings.for_dataset(settings.olheiro_dataset)
        if current.glossary_path != settings.glossary_path:
            st.warning("A semântica mudou em outra sessão. Recarregue para editar a versão atual.")
            if st.button("Recarregar semântica"):
                st.rerun()
            return
        doc = glossary.tables.get(table, TableDoc(description=""))
        col_doc = column_doc(glossary, table, column)
        with st.form(f"semantics-{settings.olheiro_dataset}-{revision}-{table}-{column}"):
            description = st.text_area("Descrição da tabela", value=doc.description, max_chars=4000)
            meaning = st.text_area(
                "Significado da coluna", value=col_doc.description, max_chars=4000
            )
            unit = st.text_input("Unidade (opcional)", value=col_doc.unit, max_chars=120)
            list_values = st.checkbox(
                "Incluir amostra de valores no contexto", value=col_doc.list_values
            )
            rules = st.text_area(
                "Regras de negócio (uma por linha)",
                value="\n".join(glossary.rules),
                max_chars=40000,
            )
            submitted = st.form_submit_button("Salvar semântica", type="primary")
        if submitted:
            updated = glossary.model_copy(deep=True)
            updated.tables.setdefault(table, TableDoc(description=""))
            updated.tables[table].description = description
            updated.tables[table].columns[column] = ColumnDoc(
                description=meaning,
                unit=unit,
                list_values=list_values,
            )
            updated.rules = [line.strip() for line in rules.splitlines() if line.strip()]
            try:
                save_dataset_glossary(
                    settings, con, Glossary.model_validate(updated.model_dump()), revision
                )
            except (OSError, ValueError, duckdb.Error) as error:
                st.error(f"Não foi possível salvar: {error}")
                return
            st.toast("Semântica atualizada. Respostas antigas do cache foram invalidadas.")
            st.rerun()
