"""Página Operação: como o agente está se saindo e o passo a passo de cada pergunta.

Lê o registro de execuções (data/runs.jsonl) e os traces (data/traces.jsonl). Não chama o modelo.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from olheiro.config import Settings
from olheiro.telemetry import RunRecord
from olheiro.tracing import SpanView, read_trace
from olheiro.ui.resources import load_resources

SOURCES = {"app": "App", "cli": "Terminal", "mcp": "MCP", "eval": "Avaliação"}
OUTCOMES = {
    "answer": "respondeu",
    "refusal": "recusou",
    "approval": "pediu aprovação",
    "error": "erro",
}
RECENT_RUNS = 30


def ops_page() -> None:
    resources = load_resources()
    if resources.settings.olheiro_demo_mode:
        st.info("A página Operação está disponível apenas no modo pessoal.")
        return
    st.title("Operação")
    st.caption(
        "Cada pergunta registra desfecho, latência, requisições, tokens e custo equivalente no "
        "nível pago; o trace mostra o passo a passo. Nada nesta página chama o modelo."
    )
    records = resources.runs.read()
    if not records:
        st.info("Nenhuma execução registrada ainda. Faça uma pergunta na página Perguntar.")
        return

    sources = st.pills(
        "Origem",
        list(SOURCES),
        default=["app", "cli", "mcp"],
        selection_mode="multi",
        format_func=SOURCES.__getitem__,
        key="ops-sources",
    )
    selected = [record for record in records if record.source in sources]
    if not selected:
        st.info("Nenhuma execução para as origens escolhidas.")
        return

    frame = runs_frame(selected)
    show_kpis(frame)
    show_charts(frame)
    show_recent(frame)
    show_trace(selected, resources.settings)


def runs_frame(records: list[RunRecord]) -> pd.DataFrame:
    frame = pd.DataFrame([record.model_dump() for record in records])
    frame["desfecho"] = frame["outcome"].map(OUTCOMES)
    frame["origem"] = frame["source"].map(SOURCES)
    return frame


def model_runs(frame: pd.DataFrame) -> pd.DataFrame:
    """Execuções que foram ao modelo (sem cache e sem erro): base de latência e requisições."""
    return frame[~frame["from_cache"] & (frame["outcome"] != "error")]


def show_kpis(frame: pd.DataFrame) -> None:
    questions = frame[frame["phase"] == "ask"]
    from_model = model_runs(frame)
    cost = frame["cost_usd"].fillna(0).sum()
    columns = st.columns(6)
    columns[0].metric("Perguntas", len(questions), border=True)
    columns[1].metric("Do cache", f"{questions['from_cache'].mean():.0%}", border=True)
    columns[2].metric("Erros", f"{(frame['outcome'] == 'error').mean():.0%}", border=True)
    if from_model.empty:
        columns[3].metric("Latência p50", "–", border=True)
        columns[4].metric("Latência p95", "–", border=True)
        columns[5].metric("Requisições/pergunta", "–", border=True)
    else:
        columns[3].metric("Latência p50", f"{from_model['seconds'].median():.1f} s", border=True)
        columns[4].metric(
            "Latência p95", f"{from_model['seconds'].quantile(0.95):.1f} s", border=True
        )
        columns[5].metric(
            "Requisições/pergunta", f"{from_model['requests'].mean():.1f}", border=True
        )
    st.caption(f"Custo equivalente no nível pago: US$ {cost:.4f}")


def show_charts(frame: pd.DataFrame) -> None:
    left, right = st.columns(2)
    with left:
        from_model = model_runs(frame)
        if not from_model.empty:
            figure = px.scatter(
                from_model,
                x="at",
                y="seconds",
                color="desfecho",
                hover_data=["question", "model", "requests"],
                title="Latência por pergunta (sem cache)",
                labels={"at": "quando", "seconds": "segundos"},
                template="plotly_white",
            )
            st.plotly_chart(figure, key="ops-latency")
    with right:
        counts = frame["desfecho"].value_counts().rename_axis("desfecho").reset_index()
        figure = px.bar(counts, x="desfecho", y="count", title="Desfechos", template="plotly_white")
        st.plotly_chart(figure, key="ops-outcomes")


def show_recent(frame: pd.DataFrame) -> None:
    st.subheader("Execuções recentes")
    recent = frame.sort_values("at", ascending=False).head(RECENT_RUNS)
    columns = {
        "at": "quando",
        "origem": "origem",
        "question": "pergunta",
        "desfecho": "desfecho",
        "from_cache": "cache",
        "model": "modelo",
        "requests": "requisições",
        "input_tokens": "tokens entrada",
        "output_tokens": "tokens saída",
        "seconds": "segundos",
        "cost_usd": "custo US$",
        "error": "erro",
    }
    st.dataframe(recent[list(columns)].rename(columns=columns), hide_index=True)


def show_trace(records: list[RunRecord], settings: Settings) -> None:
    st.subheader("Passo a passo de uma pergunta")
    traced = sorted((r for r in records if r.trace_id), key=lambda r: r.at, reverse=True)
    if not traced:
        st.caption("Sem traces: OLHEIRO_TRACING está desligado ou enviando para um backend OTLP.")
        return
    record = st.selectbox(
        "Pergunta",
        traced[:RECENT_RUNS],
        format_func=lambda r: f"{r.at:%d/%m %H:%M:%S} · {r.question[:70]}",
        key="ops-trace",
    )
    if record is None or record.trace_id is None:
        return
    spans = read_trace(settings.traces_path, record.trace_id)
    if not spans:
        st.caption("Trace ainda não gravado (os spans saem em lote) ou fora deste arquivo.")
        return
    st.plotly_chart(waterfall(spans), key="ops-waterfall")


def span_label(span: SpanView) -> str:
    attributes = span.attributes
    tokens_in = attributes.get("gen_ai.usage.input_tokens")
    tokens_out = attributes.get("gen_ai.usage.output_tokens")
    tokens = f" · {tokens_in}+{tokens_out} tokens" if tokens_in is not None else ""
    return f"{span.name}{tokens}"


def waterfall(spans: list[SpanView]) -> go.Figure:
    """Cascata: cada barra é um span, posicionada no tempo; a indentação mostra o aninhamento."""
    origin = spans[0].start
    labels = [f"{i + 1}. {'  ' * s.depth}{span_label(s)}" for i, s in enumerate(spans)]
    figure = go.Figure(
        go.Bar(
            y=labels,
            x=[span.seconds for span in spans],
            base=[(span.start - origin).total_seconds() for span in spans],
            orientation="h",
            hovertemplate="%{y}<br>início %{base:.2f} s · duração %{x:.2f} s<extra></extra>",
        )
    )
    figure.update_yaxes(autorange="reversed")
    figure.update_layout(
        xaxis_title="segundos desde o início",
        template="plotly_white",
        height=120 + 32 * len(spans),
        margin={"l": 10},
    )
    return figure
