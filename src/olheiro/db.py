"""Acesso ao DuckDB: carga dos CSVs brutos e a conexão blindada do agente.

Organização:
- data/olheiro.duckdb, schema "raw": uma tabela por CSV de data/raw/. O agente só lê.
- data/workspace.duckdb, anexado como "workspace": único lugar onde o agente grava
  (via save_result, com confirmação do usuário).
"""

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import duckdb

from olheiro.config import get_settings

RAW_SCHEMA = "raw"
# Nome com que o banco de trabalho é anexado: tabelas salvas viram workspace.<nome>.
WORKSPACE_CATALOG = "workspace"
# Nome com que o banco principal é anexado na conexão do agente.
LAKE_CATALOG = "lake"

# Camada 2 da defesa (a 1 é o validador de SQL): mesmo que um SQL perigoso passe, o motor recusa.
# A ordem importa: lock_configuration por último, senão nada mais pode ser configurado.
AGENT_HARDENING = (
    "SET enable_external_access = false",  # sem read_csv/COPY/ATTACH de arquivos, sem rede
    "SET autoinstall_known_extensions = false",
    "SET autoload_known_extensions = false",
    "SET memory_limit = '1GB'",
    "SET lock_configuration = true",  # ninguém (nem o SQL do agente) desfaz o que está acima
)


@dataclass(frozen=True)
class LoadedTable:
    """Resumo de uma tabela carregada."""

    name: str
    source: Path
    row_count: int
    column_count: int


def table_name_from_file(path: Path) -> str:
    """Gera um nome de tabela SQL seguro a partir do nome do arquivo.

    Ex.: 'Brasileirão 2024.csv' -> 'brasileirao_2024'; '2024.csv' -> 't_2024'.
    """
    ascii_name = unicodedata.normalize("NFKD", path.stem).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    if not name or name[0].isdigit():
        name = f"t_{name}"
    return name


def connect(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre (ou cria) o arquivo DuckDB."""
    if not read_only:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def connect_agent(db_path: Path, workspace_path: Path) -> duckdb.DuckDBPyConnection:
    """Conexão que o agente usa: raw somente leitura, workspace gravável, motor blindado.

    O banco principal é anexado com READ_ONLY: escrever em raw falha no próprio DuckDB.
    """
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{db_path}' AS {LAKE_CATALOG} (READ_ONLY)")
    con.execute(f"USE {LAKE_CATALOG}")  # "raw.teams" resolve sem prefixar o catálogo
    con.execute(f"ATTACH '{workspace_path}' AS {WORKSPACE_CATALOG}")
    for statement in AGENT_HARDENING:
        con.execute(statement)
    return con


def find_csv_files(raw_dir: Path) -> list[Path]:
    """Lista os CSVs da pasta de dados brutos, em ordem alfabética."""
    return sorted(raw_dir.glob("*.csv"))


def load_csv(con: duckdb.DuckDBPyConnection, csv_path: Path) -> LoadedTable:
    """Cria raw.<nome> a partir de um CSV, deixando o DuckDB detectar
    separador, cabeçalho e tipos das colunas."""
    name = table_name_from_file(csv_path)
    con.execute(
        f'CREATE TABLE {RAW_SCHEMA}."{name}" AS SELECT * FROM read_csv(?)',
        [str(csv_path)],
    )
    row_count = con.execute(f'SELECT count(*) FROM {RAW_SCHEMA}."{name}"').fetchone()[0]
    column_count = len(con.execute(f'DESCRIBE {RAW_SCHEMA}."{name}"').fetchall())
    return LoadedTable(name, csv_path, row_count, column_count)


def load_raw_dir(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> list[LoadedTable]:
    """Recria o schema raw do zero com todos os CSVs da pasta.

    Tudo roda numa transação: se um CSV falhar, o banco continua como estava.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DROP SCHEMA IF EXISTS {RAW_SCHEMA} CASCADE")
        con.execute(f"CREATE SCHEMA {RAW_SCHEMA}")
        # Até a Fase 2 havia um schema "workspace" vazio aqui; ele colidiria com o catálogo
        # "workspace" anexado na conexão do agente (referência ambígua).
        con.execute(f"DROP SCHEMA IF EXISTS {WORKSPACE_CATALOG} CASCADE")
        loaded = [load_csv(con, path) for path in find_csv_files(raw_dir)]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return loaded


def main() -> None:
    """Comando `olheiro-load`: carrega data/raw/*.csv no DuckDB."""
    settings = get_settings()
    if not find_csv_files(settings.raw_data_dir):
        sys.exit(f"Nenhum CSV encontrado em {settings.raw_data_dir}. Coloque os arquivos lá.")

    with connect(settings.duckdb_path) as con:
        loaded = load_raw_dir(con, settings.raw_data_dir)

    print(f"Banco: {settings.duckdb_path}")
    for table in loaded:
        print(
            f"  {RAW_SCHEMA}.{table.name:<20} {table.row_count:>8} linhas  "
            f"{table.column_count:>3} colunas  <- {table.source.name}"
        )
