"""Importação em duas etapas: conferir leitura/tipos e publicar a base escolhida."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import duckdb
import pandas as pd
import streamlit as st

from olheiro.config import Settings
from olheiro.datasets import import_dataset
from olheiro.import_options import IMPORT_TYPES, FileOptions, ImportOptions, ImportType
from olheiro.ingestion import FilePreview, preview_files
from olheiro.ui.components import show_table


def fingerprint(files: list[Path], options: ImportOptions) -> str:
    digest = hashlib.sha256(options.model_dump_json().encode())
    for file in files:
        digest.update(file.name.encode())
        digest.update(b"\x00")
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def file_controls(path: Path) -> FileOptions:
    if path.suffix.lower() != ".csv":
        return FileOptions()
    with st.expander(f"Leitura de {path.name}"):
        encoding = st.selectbox(
            "Codificação",
            ["utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16"],
            key=f"encoding-{path.name}",
        )
        separator = st.selectbox(
            "Separador", ["Automático", ";", ",", "Tabulação", "|"], key=f"separator-{path.name}"
        )
        header = st.selectbox(
            "Cabeçalho",
            ["Automático", "Primeira linha", "Sem cabeçalho"],
            key=f"header-{path.name}",
        )
        decimal = st.selectbox("Separador decimal", [".", ","], key=f"decimal-{path.name}")
        text = st.checkbox("Ler todas as colunas como texto", key=f"text-{path.name}")
    return FileOptions.model_validate(
        {
            "encoding": encoding,
            "delimiter": {"Automático": None, "Tabulação": "\t"}.get(separator, separator),
            "header": {"Automático": None, "Primeira linha": True, "Sem cabeçalho": False}[header],
            "decimal_separator": decimal,
            "all_varchar": text,
        }
    )


def show_import(settings: Settings) -> None:
    if settings.olheiro_demo_mode:
        return
    with st.expander("Importar outra base (CSV ou Parquet)"):
        st.subheader("Confira os dados antes de começar")
        title = st.text_input("Nome da base", placeholder="Vendas da loja")
        name = st.text_input("Identificador único", placeholder="vendas_loja")
        uploads = st.file_uploader(
            "Arquivos CSV ou Parquet",
            type=["csv", "parquet"],
            accept_multiple_files=True,
            max_upload_size=settings.olheiro_import_max_mb,
        )
        st.caption(
            f"Até {settings.olheiro_import_max_mb} MB no total. Cada arquivo vira uma tabela."
        )
        if not uploads:
            st.session_state.pop("import_preview", None)
            if st.button("Conferir prévia", key="preview-import"):
                st.error("Selecione ao menos um arquivo CSV ou Parquet.")
            return
        try:
            if sum(upload.size for upload in uploads) > settings.olheiro_import_max_mb * 1024**2:
                raise ValueError("Os arquivos ultrapassam o limite total de importação.")
            with TemporaryDirectory(prefix="olheiro-upload-") as folder:
                files: list[Path] = []
                for upload in uploads:
                    path = Path(folder) / Path(upload.name).name
                    if path.exists():
                        raise ValueError(f"Nome de arquivo repetido: {path.name}")
                    path.write_bytes(upload.getvalue())
                    files.append(path)
                options = ImportOptions(files={path.name: file_controls(path) for path in files})
                parse_signature = fingerprint(files, options)
                snapshot = st.session_state.get("import_preview")
                if snapshot and snapshot["parse_signature"] == parse_signature:
                    for preview in snapshot["previews"]:
                        with st.expander(f"Tipos de {preview.name}", expanded=True):
                            st.caption(
                                "Use VARCHAR para preservar identificadores e zeros iniciais."
                            )
                            data = pd.DataFrame(
                                [
                                    {"coluna": col, "detectado": kind, "usar": "Automático"}
                                    for col, kind in preview.columns
                                ]
                            )
                            edited = st.data_editor(
                                data,
                                hide_index=True,
                                disabled=["coluna", "detectado"],
                                column_config={
                                    "usar": st.column_config.SelectboxColumn(
                                        "Tipo escolhido",
                                        options=["Automático", *IMPORT_TYPES],
                                        required=True,
                                    )
                                },
                                key=f"types-{preview.name}-{parse_signature}",
                            )
                            options.files[preview.name].types = {
                                str(row["coluna"]): cast(ImportType, row["usar"])
                                for row in edited.to_dict("records")
                                if row["usar"] != "Automático"
                            }
                options = ImportOptions.model_validate(options.model_dump())
                signature = fingerprint(files, options)
                if st.button("Conferir prévia", key="preview-import", type="secondary"):
                    previews = preview_files(files, options)
                    st.session_state.import_preview = {
                        "signature": signature,
                        "parse_signature": parse_signature,
                        "previews": previews,
                    }
                    st.rerun()
                current = snapshot is not None and snapshot["signature"] == signature
                if snapshot:
                    if not current:
                        st.warning("A leitura ou os tipos mudaram. Confira a prévia novamente.")
                    for preview in cast(list[FilePreview], snapshot["previews"]):
                        st.markdown(f"**{preview.name}** · {preview.row_count} linhas")
                        show_table(preview.sample)
                st.caption(
                    "A prévia valida o arquivo inteiro; a tabela exibida mostra até vinte linhas."
                )
                if st.button(
                    "Importar base", key="confirm-import", type="primary", disabled=not current
                ):
                    manifest = import_dataset(
                        files, settings.datasets_dir, name, title, options=options
                    )
                    st.session_state.pop("import_preview", None)
                    st.session_state.next_dataset = str(manifest)
                    st.rerun()
        except (ValueError, OSError, duckdb.Error) as error:
            st.error(f"Não foi possível importar: {error}")
