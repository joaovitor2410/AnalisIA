"""Benchmark multidomínio: gabaritos independentes e falhas que a integração deve detectar."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_evals import Case, Dataset

from olheiro import evaluation
from olheiro.eval_suites import SUITES, suite_database
from olheiro.evaluation import (
    CaseMeta,
    EvalOutput,
    evaluate,
    golden_results,
    grounding,
    load_cases,
    main,
    save_summary,
    summarize,
)
from olheiro.telemetry import RunLog
from olheiro.tools import query_rows

# Expectativas calculadas à parte do SQL: mudanças acidentais em fixtures ou gabaritos falham.
EXPECTED: dict[str, dict[str, list[tuple[Any, ...]]]] = {
    "vendas": {
        "faturamento_realizado": [(Decimal("460.40"),)],
        "receita_por_regiao": [("Sul", Decimal("370.50")), ("Norte", Decimal("89.90"))],
        "ticket_medio": [(460.4 / 3,)],
        "clientes_sem_receita": [("Cliente C",)],
        "participacao_cancelados": [(25.0,)],
        "faturamento_diario": [
            (date(2026, 9, 1), Decimal("120.50")),
            (date(2026, 9, 2), Decimal("89.90")),
            (date(2026, 9, 3), Decimal("250.00")),
        ],
        "maior_cliente": [("Cliente A", Decimal("370.50"))],
    },
    "estoque": {
        "codigo_com_zeros": [("001", 12)],
        "codigos_distintos": [("001", 12), ("01", 0), ("1", 5)],
        "saldo_desconhecido": [("002", 1)],
        "estoque_sem_cadastro": [("999", 7)],
        "abaixo_do_minimo": [("001", 12, 15), ("01", 0, 2)],
        "valor_conhecido": [(Decimal("145.00"),)],
        "valor_por_fornecedor": [
            ("Fornecedor Alfa", Decimal("120.00")),
            ("Fornecedor Beta", Decimal("25.00")),
        ],
        "fornecedores_duplicados": [(10, 2)],
    },
}


@pytest.mark.parametrize("suite_name", SUITES)
def test_suite_goldens_run_in_hardened_database(suite_name: str) -> None:
    suite = SUITES[suite_name]
    with suite_database(suite) as (con, _):
        goldens = golden_results(load_cases(suite.cases), con)
        assert goldens
        for name, expected in EXPECTED.get(suite_name, {}).items():
            actual = sorted(goldens[name].rows)
            expected = sorted(expected)
            assert len(actual) == len(expected), name
            for actual_row, expected_row in zip(actual, expected, strict=True):
                for value, wanted in zip(actual_row, expected_row, strict=True):
                    if isinstance(wanted, Decimal | float):
                        assert float(value) == pytest.approx(float(wanted)), name
                    else:
                        assert value == wanted, name
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE raw.forbidden AS SELECT 1")
    assert len(suite.revision()) == 64


@pytest.mark.parametrize("suite_name", SUITES)
def test_validation_cli_never_builds_model_or_loads_personal_settings(
    suite_name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Validação offline tentou acessar configuração/modelo/relatórios.")

    monkeypatch.setattr(evaluation, "google_model", forbidden)
    monkeypatch.setattr(evaluation, "Settings", forbidden)
    monkeypatch.setattr(evaluation, "save_summary", forbidden)
    monkeypatch.setenv("OLHEIRO_DATASET", "/base-pessoal-inexistente/dataset.toml")
    main(["--suite", suite_name, "--validate-only"])
    assert f"{suite_name}:" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--limit", "0"], ["--limit", "-1"], ["--concurrency", "0"]])
def test_invalid_limits_fail_before_model(args: list[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(args)


@pytest.mark.parametrize(
    ("suite_name", "case_name", "sql", "expected"),
    [
        ("vendas", "faturamento_realizado", "SELECT sum(amount) FROM raw.orders", False),
        (
            "vendas",
            "faturamento_realizado",
            "SELECT sum(amount) FROM raw.orders WHERE status='concluido'",
            True,
        ),
        (
            "estoque",
            "codigo_com_zeros",
            "SELECT '001' AS sku, sum(quantity) FROM raw.stock WHERE CAST(sku AS BIGINT)=1",
            False,
        ),
        (
            "estoque",
            "codigo_com_zeros",
            "SELECT sku, sum(quantity) FROM raw.stock WHERE sku='001' GROUP BY sku",
            True,
        ),
        (
            "estoque",
            "valor_por_fornecedor",
            "SELECT f.supplier_name, sum(s.quantity*p.unit_cost) FROM raw.stock s "
            "JOIN raw.products p USING(sku) JOIN raw.suppliers f USING(supplier_id) "
            "GROUP BY f.supplier_name",
            False,
        ),
    ],
)
def test_scripted_agent_exposes_domain_errors(
    suite_name: str, case_name: str, sql: str, expected: bool, tmp_path: Path
) -> None:
    suite = SUITES[suite_name]
    dataset = load_cases(suite.cases)
    dataset.cases = [case for case in dataset.cases if case.name == case_name]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": True,
                        "answer": "Resultado conforme a tabela.",
                        "sql": sql,
                    },
                )
            ]
        )

    with suite_database(suite) as (con, glossary):
        report = evaluate(
            dataset,
            con,
            glossary,
            FunctionModel(respond),
            "offline",
            RunLog(tmp_path / "runs.jsonl"),
        )
    summary = summarize(report, "offline", suite.name, suite.revision())
    assert summary.cases[0].checks["comportamento"] is True
    assert summary.cases[0].checks["evidencia"] is expected


def test_results_for_same_model_keep_domains_separate(tmp_path: Path) -> None:
    # Um relatório vazio basta para testar a identidade de publicação, sem chamar o agente.
    from olheiro.evaluation import RunSummary

    for name in ("vendas", "estoque"):
        summary = RunSummary(
            model="google:example", run_date=date(2026, 11, 4), cases=[], suite=name
        )
        path = save_summary(summary, tmp_path)
        assert path.parent.name == name
        assert path.is_file()
    readme = (tmp_path / "README.md").read_text()
    assert "| Suíte | estoque | vendas |" in readme


def test_grounding_requires_evidence_for_numbers_previously_treated_as_seasons() -> None:
    output = EvalOutput(answerable=True, answer="Foram 2019 unidades.", rows=[[12]])
    assert grounding(output, "Qual o saldo?") == (0.0, ["2019"])
    assert grounding(output, "Qual o saldo em 2019?")[0] == 1.0
    dated = EvalOutput(answerable=True, answer="Em 2026, o SKU 001.", rows=[["2026-09-01", "001"]])
    assert grounding(dated, "Qual a data e o SKU?")[0] == 1.0


def test_golden_validation_rejects_mutation_and_truncation() -> None:
    with suite_database(SUITES["vendas"]) as (con, _):
        for sql in (
            "DELETE FROM raw.orders",
            "SELECT 1 FROM raw.orders CROSS JOIN raw.orders CROSS JOIN raw.orders",
        ):
            dataset = Dataset[str, EvalOutput, CaseMeta](
                name="invalid",
                cases=[
                    Case(
                        name="invalid",
                        inputs="Teste",
                        metadata=CaseMeta(
                            category="teste",
                            expect="answer",
                            golden_sql=sql,
                        ),
                    )
                ],
            )
            with pytest.raises(ValueError):
                golden_results(dataset, con)
        assert query_rows(con, "SELECT count(*) FROM raw.orders").rows == [(4,)]


@pytest.mark.parametrize("failure", [False, True])
def test_each_case_closes_its_cursor_even_on_model_failure(
    failure: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cursors: list[duckdb.DuckDBPyConnection] = []
    original = evaluation.session_cursor

    def cursor_for(base: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
        cursor = original(base)
        cursors.append(cursor)
        return cursor

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if failure:
            raise UnexpectedModelBehavior("Falha simulada")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "answerable": False,
                        "answer": "Não há custos nem margem na base de vendas.",
                    },
                )
            ]
        )

    monkeypatch.setattr(evaluation, "session_cursor", cursor_for)
    suite = SUITES["vendas"]
    dataset = load_cases(suite.cases)
    dataset.cases = [case for case in dataset.cases if case.name == "margem_ausente"]
    with suite_database(suite) as (con, glossary):
        report = evaluate(
            dataset,
            con,
            glossary,
            FunctionModel(respond),
            "offline",
            RunLog(tmp_path / "runs.jsonl"),
        )
        assert len(cursors) == 1
        with pytest.raises(duckdb.Error, match="closed"):
            cursors[0].execute("SELECT 1")
        assert query_rows(con, "SELECT count(*) FROM raw.orders").rows == [(4,)]
    assert summarize(report, "offline").cases[0].checks["comportamento"] is not failure
