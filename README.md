# Olheiro

Agente de IA analista de dados: recebe perguntas em português sobre dados tabulares, escreve e executa SQL e responde com evidências (SQL + tabela + gráfico).

> 🚧 Em construção. Este README será finalizado na Fase 8.

## Rodando localmente

```bash
uv sync
cp .env.example .env   # e preencha GOOGLE_API_KEY (Google AI Studio)
uv run olheiro-load    # carrega data/raw/*.csv no DuckDB
uv run olheiro-check   # confere se está tudo ok
```

## Usando

```bash
uv run streamlit run src/olheiro/app.py                 # app: Perguntar, Dashboard, Dados
uv run olheiro-ask --verbose "Qual região tem mais títulos?"   # pelo terminal
```

Cada pergunta gera um trace OpenTelemetry e um registro de execução, visíveis na página
**Operação** do app (latência, custo, erros e o passo a passo do agente). Para enviar os traces a
um backend (Jaeger, Grafana Tempo, Phoenix, Logfire): `OLHEIRO_TRACING=otlp` no `.env`.

## Qualidade

```bash
uv run pytest       # testes offline (modelo falso; não gasta cota)
uv run ruff check . # lint
uv run mypy         # tipos
uv run olheiro-eval --model google:gemini-3.8-flash      # avaliação com o modelo real (pede confirmação de custo)
```
