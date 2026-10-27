"""Acesso ao DuckDB: carga dos arquivos tabulares e conexão blindada do agente.

Organização:
- Banco configurado, schema "raw": uma tabela por CSV/Parquet importado. O agente só lê.
- Workspace separado, anexado como "workspace": único lugar onde o agente grava
  (via save_result, com confirmação do usuário).
"""

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from olheiro.config import get_settings

RAW_SCHEMA = "raw"
# Nome com que o banco de trabalho é anexado: tabelas salvas viram workspace.<nome>.
WORKSPACE_CATALOG = "workspace"
DATA_READERS = {".csv": "read_csv", ".parquet": "read_parquet"}
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


class WorkspaceInUseError(RuntimeError):
    """Outro processo mantém o lock de escrita do workspace."""

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        match = re.search(r"\(PID (\d+)\)", detail)
        self.owner_pid = int(match.group(1)) if match else None
        owner = f" (PID {self.owner_pid})" if self.owner_pid is not None else ""
        super().__init__(
            f"O workspace {path} já está em uso por outro processo{owner}. "
            "Encerre a instância anterior da AnalisIA com Ctrl+C no terminal onde ela foi "
            "iniciada e tente novamente. Para executar app, CLI ou MCP simultaneamente, "
            "configure WORKSPACE_PATH com um arquivo diferente para cada processo."
        )


@dataclass(frozen=True)
class LoadedTable:
    """Resumo de uma tabela carregada."""

    name: str
    source: Path
    row_count: int
    column_count: int


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    """Primeiro valor da primeira linha (ex.: um count). Consultas assim sempre devolvem linha;
    se não devolverem, é erro de programação, e falhar aqui é melhor que um TypeError adiante."""
    row = con.execute(sql, params or []).fetchone()
    if row is None:
        raise ValueError(f"A consulta não devolveu linha: {sql}")
    return row[0]


def quote_identifier(name: str) -> str:
    """Escapa identificadores, inclusive colunas reais contendo aspas ou espaços."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Escapa caminhos para comandos como ATTACH, que não aceitam parâmetros."""
    return "'" + value.replace("'", "''") + "'"


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


def connect_agent(db_path: Path, workspace_path: Path | None) -> duckdb.DuckDBPyConnection:
    """Conexão que o agente usa: raw somente leitura, workspace gravável, motor blindado.

    O banco principal é anexado com READ_ONLY: escrever em raw falha no próprio DuckDB.
    workspace_path=None anexa um banco vazio em memória, usado pela demo sem abrir o pessoal.
    """
    if workspace_path is not None:
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH {quote_literal(str(db_path))} AS {LAKE_CATALOG} (READ_ONLY)")
        con.execute(f"USE {LAKE_CATALOG}")  # "raw.teams" resolve sem prefixar o catálogo
        try:
            workspace = str(workspace_path) if workspace_path is not None else ":memory:"
            con.execute(f"ATTACH {quote_literal(workspace)} AS {WORKSPACE_CATALOG}")
        except duckdb.IOException as error:
            if workspace_path is not None and "Could not set lock on file" in str(error):
                raise WorkspaceInUseError(workspace_path, str(error)) from error
            raise
        for statement in AGENT_HARDENING:
            con.execute(statement)
    except Exception:
        con.close()  # uma falha no ATTACH não pode manter o banco bruto anexado
        raise
    return con


def session_cursor(base: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Cursor para uma sessão/thread (ex.: um visitante no Streamlit) sobre a conexão do agente.

    O DuckDB pede um cursor por thread. Ele herda a blindagem (configuração global do banco),
    mas não o USE (vale só para a conexão onde rodou): sem repetir, "raw.teams" não resolve.
    """
    cursor = base.cursor()
    cursor.execute(f"USE {LAKE_CATALOG}")
    return cursor


def find_csv_files(raw_dir: Path) -> list[Path]:
    """Lista os CSVs da pasta de dados brutos, em ordem alfabética."""
    return sorted(raw_dir.glob("*.csv"))


def find_data_files(source: Path) -> list[Path]:
    """Arquivo ou pasta local de CSV/Parquet, sem busca recursiva nem URLs."""
    if source.is_file():
        return [source] if source.suffix.lower() in DATA_READERS else []
    if not source.is_dir():
        return []
    return sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in DATA_READERS)


def validate_data_files(files: list[Path]) -> None:
    """Recusa entradas vazias, formatos inválidos e colisões antes de alterar o banco."""
    if not files:
        raise ValueError("Nenhum CSV ou Parquet encontrado na origem informada.")
    names: dict[str, Path] = {}
    for path in files:
        if not path.is_file() or path.suffix.lower() not in DATA_READERS:
            raise ValueError(f"Arquivo inexistente ou formato não suportado: {path.name}")
        name = table_name_from_file(path)
        if name in names:
            raise ValueError(
                f"Nomes de tabela em conflito: {names[name].name} e {path.name} → {name}"
            )
        names[name] = path


def load_csv(con: duckdb.DuckDBPyConnection, csv_path: Path) -> LoadedTable:
    """Cria raw.<nome> a partir de um CSV, deixando o DuckDB detectar
    separador, cabeçalho e tipos das colunas."""
    return load_data_file(con, csv_path)


def load_data_file(con: duckdb.DuckDBPyConnection, path: Path) -> LoadedTable:
    """Materializa um arquivo: o agente consulta a tabela sem acesso externo ao arquivo."""
    name = table_name_from_file(path)
    reader = DATA_READERS[path.suffix.lower()]
    options = ", sample_size=-1" if reader == "read_csv" else ""
    con.execute(
        f'CREATE TABLE {RAW_SCHEMA}."{name}" AS SELECT * FROM {reader}(?{options})',
        [str(path)],
    )
    row_count = scalar(con, f'SELECT count(*) FROM {RAW_SCHEMA}."{name}"')
    column_count = len(con.execute(f'DESCRIBE {RAW_SCHEMA}."{name}"').fetchall())
    return LoadedTable(name, path, row_count, column_count)


def load_raw_dir(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> list[LoadedTable]:
    """Recria raw com CSV/Parquet da pasta; falhas preservam a carga anterior."""
    return load_files(con, find_data_files(raw_dir))


def load_files(con: duckdb.DuckDBPyConnection, files: list[Path]) -> list[LoadedTable]:
    """Recria o schema raw do zero com os arquivos validados.

    Tudo roda numa transação: se um CSV falhar, o banco continua como estava.
    """
    validate_data_files(files)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DROP SCHEMA IF EXISTS {RAW_SCHEMA} CASCADE")
        con.execute(f"CREATE SCHEMA {RAW_SCHEMA}")
        # Até a Fase 2 havia um schema "workspace" vazio aqui; ele colidiria com o catálogo
        # "workspace" anexado na conexão do agente (referência ambígua).
        con.execute(f"DROP SCHEMA IF EXISTS {WORKSPACE_CATALOG} CASCADE")
        loaded = [load_data_file(con, path) for path in files]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return loaded


def main() -> None:
    """Comando `olheiro-load`: carrega CSV/Parquet da base configurada no DuckDB."""
    settings = get_settings()
    if not find_data_files(settings.raw_data_dir):
        sys.exit(f"Nenhum CSV ou Parquet em {settings.raw_data_dir}. Coloque os arquivos lá.")

    with connect(settings.duckdb_path) as con:
        loaded = load_raw_dir(con, settings.raw_data_dir)

    print(f"Banco: {settings.duckdb_path}")
    for table in loaded:
        print(
            f"  {RAW_SCHEMA}.{table.name:<20} {table.row_count:>8} linhas  "
            f"{table.column_count:>3} colunas  <- {table.source.name}"
        )
