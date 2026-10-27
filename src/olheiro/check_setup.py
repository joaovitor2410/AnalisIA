"""Comando `olheiro-check`: diagnóstico do ambiente, com ✅/❌ por item.

Cada verificação é uma função pequena que devolve um CheckResult.
Nunca imprime o valor de chaves de API, só se estão definidas.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from olheiro.config import PROJECT_ROOT, PROVIDER_KEY_FIELDS, Settings, get_settings
from olheiro.db import (
    RAW_SCHEMA,
    WorkspaceInUseError,
    connect,
    connect_agent,
    find_data_files,
    quote_identifier,
    scalar,
    table_name_from_file,
)
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
    detail = "encontrado" if exists else "opcional: configuração também pode vir do ambiente"
    return CheckResult(True, "Arquivo .env", detail)


def check_model_key(settings: Settings) -> CheckResult:
    label = f"Chave da API para {settings.olheiro_model}"
    if settings.provider not in PROVIDER_KEY_FIELDS:
        return CheckResult(False, label, f"provedor desconhecido: '{settings.provider}'")
    key_field = PROVIDER_KEY_FIELDS[settings.provider].upper()
    if settings.api_key_for_model() is None:
        return CheckResult(False, label, f"{key_field} não definida no .env")
    return CheckResult(True, label, f"{key_field} definida")


def check_raw_files(settings: Settings) -> CheckResult:
    files = find_data_files(settings.raw_data_dir)
    detail = ", ".join(f.name for f in files) or f"nenhum CSV ou Parquet em {settings.raw_data_dir}"
    return CheckResult(bool(files), "Arquivos CSV/Parquet", detail)


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
    """Confere as tabelas da origem, inclusive tabelas válidas que estejam vazias."""
    expected = {table_name_from_file(f) for f in find_data_files(settings.raw_data_dir)}
    with connect(settings.duckdb_path, read_only=True) as con:
        names = con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = ?", [RAW_SCHEMA]
        ).fetchall()
        found = {
            name: scalar(con, f"SELECT count(*) FROM {RAW_SCHEMA}.{quote_identifier(name)}")
            for (name,) in names
        }
    missing = expected - found.keys()
    summary = ", ".join(f"{name} ({size} linhas)" for name, size in sorted(found.items()))
    if missing:
        return CheckResult(False, "Tabelas raw", f"faltando: {', '.join(sorted(missing))}")
    return CheckResult(bool(found), "Tabelas raw", summary or "nenhuma tabela")


def check_agent_connection(settings: Settings) -> CheckResult:
    """A conexão do agente abre e o motor recusa ler arquivos do disco."""
    label = "Conexão blindada do agente"
    try:
        workspace = None if settings.olheiro_demo_mode else settings.workspace_path
        with connect_agent(settings.duckdb_path, workspace) as con:
            con.execute("SELECT * FROM read_csv('/etc/hosts')")
    except duckdb.PermissionException:
        return CheckResult(True, label, "raw somente leitura, sem acesso a disco/rede")
    except WorkspaceInUseError as error:
        return CheckResult(False, label, str(error))
    except duckdb.Error as error:
        return CheckResult(False, label, f"erro ao abrir: {error}")
    return CheckResult(False, label, "acesso a arquivos NÃO está bloqueado")


def check_glossary_sync(settings: Settings) -> CheckResult:
    """Descrições são opcionais; referências a tabelas/colunas inexistentes são erros."""
    if settings.glossary_path is None:
        return CheckResult(True, "Glossário x banco", "opcional; contexto pelo catálogo automático")
    with connect(settings.duckdb_path, read_only=True) as con:
        problems = check_glossary(
            load_glossary(settings.glossary_path), con, require_complete=False
        )
    return CheckResult(not problems, "Glossário x banco", "; ".join(problems) or "em sincronia")


def run_checks() -> list[CheckResult]:
    """Roda as verificações em ordem. As do banco só rodam se ele abrir."""
    settings = get_settings()
    results = [
        check_python(),
        check_env_file(),
        (
            CheckResult(True, "Consultas ao modelo", "desabilitadas na demo; exemplos sem chave")
            if settings.olheiro_demo_mode and not settings.olheiro_demo_model_enabled
            else check_model_key(settings)
        ),
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
