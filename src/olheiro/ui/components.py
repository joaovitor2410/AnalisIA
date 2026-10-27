"""Peças visuais reaproveitadas pelas páginas."""

from decimal import Decimal

import pandas as pd
import streamlit as st

from olheiro.agent import AgentReport, describe_steps
from olheiro.charts import ChartSpec, build_figure
from olheiro.tools import QueryResult


def to_dataframe(result: QueryResult) -> pd.DataFrame:
    return pd.DataFrame(result.rows, columns=result.columns)


def show_table(result: QueryResult) -> None:
    st.dataframe(to_dataframe(result), hide_index=True)
    if result.truncated:
        st.caption(f"Mostrando as primeiras {len(result.rows)} linhas.")


def show_metric(spec: ChartSpec, evidence: QueryResult) -> None:
    """KPI nativo do Streamlit: valor de y na 1ª linha, com o valor de x como legenda."""
    label = spec.title
    if spec.x is not None:
        label += f" · {evidence.column_values(spec.x)[0]}"
    st.metric(label, metric_value(evidence.column_values(spec.y)[0]), border=True)


def metric_value(value: object) -> int | float | str | None:
    """O st.metric aceita número, texto ou None; Decimal e outros tipos do banco são convertidos."""
    if value is None or isinstance(value, int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def show_visual(spec: ChartSpec, evidence: QueryResult, key: str) -> None:
    if spec.kind == "metric":
        show_metric(spec, evidence)
    else:
        st.plotly_chart(build_figure(spec, evidence), key=key)


def usage_caption(report: AgentReport) -> str:
    if report.from_cache:
        return f"⚡ Resposta do cache (gerada por {report.model_name}) · 0 requisições ao modelo"
    usage = report.usage
    tokens = usage.input_tokens + usage.output_tokens
    return (
        f"{report.model_name} · {usage.requests} requisições · "
        f"{usage.tool_calls} ferramentas · {tokens} tokens"
    )


def show_report(report: AgentReport, key: str) -> None:
    """Resposta, insights, visualização e as abas de evidência (tabela, SQL, passos)."""
    output = report.output
    if output.answerable and report.evidence is not None:
        st.caption("ANÁLISE COM EVIDÊNCIA · confira os dados e o SQL abaixo")
    if not output.answerable:
        st.warning(output.answer, icon=":material/block:")
    else:
        st.markdown(output.answer)
    if output.insights:
        st.markdown("\n".join(f"- {insight}" for insight in output.insights))
    if output.chart is not None and report.evidence is not None:
        show_visual(output.chart, report.evidence, key=f"{key}-chart")

    if report.evidence is not None:
        table_tab, sql_tab, steps_tab = st.tabs(["Tabela", "SQL", "Passos do agente"])
        with table_tab:
            show_table(report.evidence)
            st.download_button(
                "Baixar evidência em CSV",
                to_dataframe(report.evidence).to_csv(index=False).encode("utf-8-sig"),
                file_name="analisia-evidencia.csv",
                mime="text/csv",
                key=f"{key}-csv",
                icon=":material/download:",
                on_click="ignore",
                help="Baixa as linhas exibidas. Se houver corte, ele é indicado na tabela.",
            )
        with sql_tab:
            st.code(output.sql, language="sql")
        with steps_tab:
            show_steps(report)
    elif report.messages:
        with st.expander("Passos do agente"):
            show_steps(report)
    st.caption(usage_caption(report))


def show_steps(report: AgentReport) -> None:
    steps = describe_steps(report.messages)
    if not steps:
        st.caption("Resposta do cache: o modelo não foi chamado.")
    for step in steps:
        st.text(step)
