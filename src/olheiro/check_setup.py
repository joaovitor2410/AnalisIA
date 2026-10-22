"""Comando `olheiro-check`: diagnóstico do ambiente, com ✅/❌ por item.

Cada verificação é uma função pequena que devolve um CheckResult.
Nunca imprime o valor de chaves de API, só se estão definidas.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from olheiro.config import PROJECT_ROOT, PROVIDER_KEY_FIELDS, Settings, get_settings
from olheiro.db import RAW_SCHEMA, connect, connect_agent, find_csv_files, table_name_from_file
from olheiro.semantic import check_glossary, load_glossary

MIN_PYTHON = (3, 13)


@dataclass(frozen=True)
class CheckResult:
    """Resultado de uma verificação."""

    ok: bool
    label: str
    detail: str = ""


def check_python() -> CheckResult:
    version = ".".join(map(str, sys.version_info[:3]))
    return CheckResult(sys.version_info >= MIN_PYTHON, "Versão do Python", version)


def check_env_file() -> CheckResult:
    exists = (PROJECT_ROOT / ".env").exists()
    detail = "encontrado" if exists else "faltando: rode `cp .env.example .env`"
    return CheckResult(exists, "Arquivo .env", detail)


def check_model_key(settings: Settings) -> CheckResult:
    label = f"Chave da API para {settings.olheiro_model}"
    if settings.provider not in PROVIDER_KEY_FIELDS:
        return CheckResult(False, label, f"provedor desconhecido: '{settings.provider}'")
    key_field = PROVIDER_KEY_FIELDS[settings.provider].upper()
    if settings.api_key_for_model() is None:
        return CheckResult(False, label, f"{key_field} não definida no .env")
    return CheckResult(True, label, f"{key_field} definida")


def check_raw_files(settings: Settings) -> CheckResult:
    files = find_csv_files(settings.raw_data_dir)
    detail = ", ".join(f.name for f in files) or f"nenhum CSV em {settings.raw_data_dir}"
    return CheckResult(bool(files), "CSVs em data/raw", detail)


def check_database(settings: Settings) -> CheckResult:
    if not settings.duckdb_path.exists():
        return CheckResult(False, "Banco DuckDB", "não existe: rode `uv run olheiro-load`")
    try:
        with connect(settings.duckdb_path, read_only=True):
            pass
    except duckdb.Error as error:
        return CheckResult(False, "Banco DuckDB", f"erro ao abrir: {error}")
    return CheckResult(True, "Banco DuckDB", str(settings.duckdb_path))


def check_tables(settings: Settings) -> CheckResult:
    """Confere se cada CSV virou uma tabela com linhas no schema raw."""
    expected = {table_name_from_file(f) for f in find_csv_files(settings.raw_data_dir)}
    with connect(settings.duckdb_path, read_only=True) as con:
        names = con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = ?", [RAW_SCHEMA]
        ).fetchall()
        found = {
            name: con.execute(f'SELECT count(*) FROM {RAW_SCHEMA}."{name}"').fetchone()[0]
            for (name,) in names
        }
    missing = expected - found.keys()
    empty = [name for name, size in found.items() if size == 0]
    summary = ", ".join(f"{name} ({size} linhas)" for name, size in sorted(found.items()))
    if missing:
        return CheckResult(False, "Tabelas raw", f"faltando: {', '.join(sorted(missing))}")
    if empty:
        return CheckResult(False, "Tabelas raw", f"vazias: {', '.join(empty)}")
    return CheckResult(bool(found), "Tabelas raw", summary or "nenhuma tabela")


def check_agent_connection(settings: Settings) -> CheckResult:
    """A conexão do agente abre e o motor recusa ler arquivos do disco."""
    label = "Conexão blindada do agente"
    try:
        with connect_agent(settings.duckdb_path, settings.workspace_path) as con:
            con.execute("SELECT * FROM read_csv('/etc/hosts')")
    except duckdb.PermissionException:
        return CheckResult(True, label, "raw somente leitura, sem acesso a disco/rede")
    except duckdb.Error as error:
        return CheckResult(False, label, f"erro ao abrir: {error}")
    return CheckResult(False, label, "acesso a arquivos NÃO está bloqueado")


def check_glossary_sync(settings: Settings) -> CheckResult:
    """O glossário descreve exatamente as colunas que existem no banco."""
    with connect(settings.duckdb_path, read_only=True) as con:
        problems = check_glossary(load_glossary(settings.glossary_path), con)
    return CheckResult(not problems, "Glossário x banco", "; ".join(problems) or "em sincronia")


def run_checks() -> list[CheckResult]:
    """Roda as verificações em ordem. As do banco só rodam se ele abrir."""
    settings = get_settings()
    results = [
        check_python(),
        check_env_file(),
        check_model_key(settings),
        check_raw_files(settings),
        check_database(settings),
    ]
    if results[-1].ok:
        db_checks: list[Callable[[Settings], CheckResult]] = [
            check_tables,
            check_agent_connection,
            check_glossary_sync,
        ]
        results += [check(settings) for check in db_checks]
    return results


def main() -> None:
    results = run_checks()
    for result in results:
        icon = "✅" if result.ok else "❌"
        print(f"{icon} {result.label}: {result.detail}")
    if all(r.ok for r in results):
        print("\nTudo pronto.")
    else:
        sys.exit("\nCorrija os itens com ❌ e rode de novo.")
