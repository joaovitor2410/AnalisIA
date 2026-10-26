"""Entrada do app: prepara a base ausente e inicia a interface Streamlit.

`olheiro-app` abre a interface; `olheiro-mcp` é uma integração stdio. A carga inicial usa
arquivo temporário e publicação atômica: falhar não deixa um banco vazio no caminho final.
Uma base existente é validada, nunca substituída automaticamente.
"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from olheiro.check_setup import check_glossary_sync, check_tables
from olheiro.config import Settings, get_settings
from olheiro.db import connect, find_csv_files, load_raw_dir


def validate_database(settings: Settings) -> None:
    """Falha com orientação se a base estiver incompleta ou divergir do glossário."""
    for check in (check_tables(settings), check_glossary_sync(settings)):
        if not check.ok:
            raise ValueError(f"{check.label}: {check.detail}. Confira `uv run olheiro-check`.")


def ensure_database(settings: Settings) -> bool:
    """Cria a base apenas quando ausente; retorna True se fez a carga inicial."""
    if settings.duckdb_path.exists():
        validate_database(settings)
        return False
    if not find_csv_files(settings.raw_data_dir):
        raise ValueError(f"Nenhum CSV em {settings.raw_data_dir}. Consulte data/raw/SOURCE.md.")
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="olheiro-load-", dir=settings.duckdb_path.parent) as folder:
        candidate = Path(folder) / "olheiro.duckdb"
        with connect(candidate) as con:
            load_raw_dir(con, settings.raw_data_dir)
        validate_database(settings.model_copy(update={"duckdb_path": candidate}))
        try:
            # O link publica o arquivo completo sem substituir uma base que outro
            # processo tenha criado entre a verificação inicial e o fim da carga.
            os.link(candidate, settings.duckdb_path)
        except FileExistsError:
            validate_database(settings)
            return False
    return True


def main(argv: list[str] | None = None) -> None:
    """Comando olheiro-app; opções extras são encaminhadas ao Streamlit."""
    args = sys.argv[1:] if argv is None else argv
    if "--help" not in args:
        try:
            if ensure_database(get_settings()):
                print("Base de demonstração inicializada a partir dos CSVs.", flush=True)
        except (OSError, ValueError, duckdb.Error) as error:
            sys.exit(f"Não foi possível iniciar o Olheiro: {error}")
    # Substitui o processo: sinais de parada chegam ao servidor, inclusive no Docker.
    app_path = Path(__file__).with_name("app.py")
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", str(app_path), *args])


if __name__ == "__main__":
    main()
