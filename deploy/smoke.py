"""Verificação do contêiner, sem chave/modelo: docker compose exec app python deploy/smoke.py.

Valida o runtime real (base, blindagem, usuário, filesystem, interface e rede), além do health
HTTP que só prova que o servidor está no ar. Não serve como teste de chamada ao Gemini.
"""

import http.client
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from streamlit.testing.v1 import AppTest

from olheiro.config import Settings, get_settings
from olheiro.datasets import import_dataset
from olheiro.db import connect_agent, scalar
from olheiro.demo import QuestionBudget
from olheiro.import_options import FileOptions, ImportOptions
from olheiro.ingestion import preview_files
from olheiro.launcher import ensure_database
from olheiro.quality import check_relationship, table_quality
from olheiro.semantic import Glossary, load_glossary
from olheiro.semantic_store import manifest_revision, save_dataset_glossary
from olheiro.storage import JsonLinesFile
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


def check_import(settings: Settings) -> None:
    """Confere CSV e Parquet no volume gravável, sem tocar na base usada pela interface."""
    settings.datasets_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="smoke-import-", dir=settings.datasets_dir) as folder:
        root = Path(folder)
        # Estado persistente e retenção devem funcionar com UID sem root no volume.
        quota = root / "quota.json"
        assert QuestionBudget(1, quota).take()
        assert not QuestionBudget(1, quota).take()
        log = JsonLinesFile(root / "probe.jsonl", max_bytes=100, backup_count=2)
        for i in range(30):
            log.append([f'{{"index":{i},"text":"teste"}}'])
        assert log.archives() and '"index":29' in log.read()[-1]
        assert all(file.stat().st_size <= 100 for file in [log.path, *log.archives()])
        csv = root / "pedidos.csv"
        csv.write_text("cliente_id;valor\n001;10\n002;20\n", encoding="utf-8")
        parquet = root / "clientes.parquet"
        with duckdb.connect() as con:
            con.execute(
                "COPY (SELECT * FROM (VALUES ('001'), ('002')) t(cliente_id)) "
                "TO ? (FORMAT PARQUET)",
                [str(parquet)],
            )
        options = ImportOptions(files={csv.name: FileOptions(types={"cliente_id": "VARCHAR"})})
        preview = preview_files([csv, parquet], options)
        manifest = import_dataset([csv, parquet], root / "bases", "loja", "Loja", options=options)
        # A demo não oferece importação; esta verificação exercita apenas o backend local.
        config = settings.model_copy(update={"olheiro_demo_mode": False}).for_dataset(manifest)
        with connect_agent(config.duckdb_path, None) as con:
            assert (
                scalar(
                    con, "SELECT sum(valor) FROM raw.pedidos JOIN raw.clientes USING (cliente_id)"
                )
                == 30
            )
            assert "error" in run_sql(con, "SELECT * FROM read_csv('/etc/hosts')")
            assert con.execute("SELECT * FROM raw.pedidos").fetchall() == preview[0].sample.rows
            assert table_quality(con, "pedidos").duplicate_rows == 0
            assert check_relationship(
                con, "pedidos", "cliente_id", "clientes", "cliente_id"
            ).compatible
            glossary = Glossary(rules=["Valores dos pedidos em reais."])
            updated = save_dataset_glossary(config, con, glossary, manifest_revision(manifest))
            assert load_glossary(updated.glossary_path) == glossary


def main() -> None:
    settings = get_settings()
    workspace_before = (
        settings.workspace_path.read_bytes() if settings.workspace_path.exists() else None
    )
    assert os.getuid() != 0, "O contêiner está rodando como root."
    assert not Path("/app/.env").exists(), "Um .env entrou na imagem."
    assert ensure_database(settings) is False, "A base deve vir pronta na imagem."
    try:
        Path("/app/write-check").write_text("probe", encoding="utf-8")
    except OSError:
        pass
    else:
        raise AssertionError("O filesystem da aplicação permite escrita.")
    workspace = None if settings.olheiro_demo_mode else settings.workspace_path
    with connect_agent(settings.duckdb_path, workspace) as con:
        assert scalar(con, "SELECT count(*) FROM raw.brasileirao") == 450
        assert scalar(con, "SELECT count(*) FROM raw.teams") == 45
        assert "error" in run_sql(con, "DROP TABLE raw.teams")
        if not settings.olheiro_demo_mode:
            con.execute("CREATE TABLE workspace.smoke_probe AS SELECT 1 AS n")
            con.execute("DROP TABLE workspace.smoke_probe")
    app = AppTest.from_file("/app/src/olheiro/app.py", default_timeout=30).run()
    assert not app.exception, [error.message for error in app.exception]
    assert app.title[0].value == "Perguntar aos dados"
    if settings.olheiro_demo_mode:
        assert len(app.pills(key="example").options) == 6
        app.chat_input[0].set_value("Quantas temporadas estão disponíveis?").run()
        assert not app.exception and not app.error
        report = app.session_state["history"][-1].report
        assert report.from_cache and report.usage.requests == 0
        assert report.evidence.rows == [(22,)]
        app.button(key="pin-0").click().run()
        other = AppTest.from_file("/app/src/olheiro/app.py", default_timeout=30).run()
        assert not other.exception
        assert other.session_state["demo_resources"].dashboard.read().items == []
        workspace_after = (
            settings.workspace_path.read_bytes() if settings.workspace_path.exists() else None
        )
        assert workspace_before == workspace_after, "A demo alterou o workspace pessoal."
    check_import(settings)
    check_network()
    print("OK: base, blindagem, usuário, filesystem, interface e saída de rede verificados.")


if __name__ == "__main__":
    main()
