"""Verificação do contêiner, sem chave/modelo: docker compose exec app python deploy/smoke.py.

Valida o runtime real (base, blindagem, usuário, filesystem, interface e rede), além do health
HTTP que só prova que o servidor está no ar. Não serve como teste de chamada ao Gemini.
"""

import http.client
import os
import socket
from pathlib import Path

from streamlit.testing.v1 import AppTest

from olheiro.config import get_settings
from olheiro.db import connect_agent, scalar
from olheiro.launcher import ensure_database
from olheiro.tools import run_sql


def check_network() -> None:
    """A rede interna não sai diretamente; o proxy recusa destinos fora da lista."""
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            raise AssertionError("A aplicação conseguiu sair diretamente para a internet.")
    except OSError:
        pass
    proxy = http.client.HTTPConnection("egress", 3128, timeout=10)
    proxy.set_tunnel("example.com", 443)
    try:
        proxy.connect()
    except OSError as error:
        assert "403" in str(error), f"Falha inesperada no proxy: {error}"
    else:
        raise AssertionError("O proxy permitiu um destino fora da lista.")
    finally:
        proxy.close()
    # Um túnel TCP não faz requisição ao modelo e não consome tokens/cota.
    allowed = http.client.HTTPConnection("egress", 3128, timeout=20)
    allowed.set_tunnel("generativelanguage.googleapis.com", 443)
    try:
        allowed.connect()
    finally:
        allowed.close()


def main() -> None:
    settings = get_settings()
    assert os.getuid() != 0, "O contêiner está rodando como root."
    assert not Path("/app/.env").exists(), "Um .env entrou na imagem."
    assert ensure_database(settings) is False, "A base deve vir pronta na imagem."
    try:
        Path("/app/write-check").write_text("probe", encoding="utf-8")
    except OSError:
        pass
    else:
        raise AssertionError("O filesystem da aplicação permite escrita.")
    with connect_agent(settings.duckdb_path, settings.workspace_path) as con:
        assert scalar(con, "SELECT count(*) FROM raw.brasileirao") == 450
        assert scalar(con, "SELECT count(*) FROM raw.teams") == 45
        assert "error" in run_sql(con, "DROP TABLE raw.teams")
        con.execute("CREATE TABLE workspace.smoke_probe AS SELECT 1 AS n")
        con.execute("DROP TABLE workspace.smoke_probe")
    app = AppTest.from_file("/app/src/olheiro/app.py", default_timeout=30).run()
    assert not app.exception, [error.message for error in app.exception]
    assert app.title[0].value == "Perguntar aos dados"
    check_network()
    print("OK: base, blindagem, usuário, filesystem, interface e saída de rede verificados.")


if __name__ == "__main__":
    main()
