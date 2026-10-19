# Olheiro

Agente de IA analista de dados: recebe perguntas em português sobre dados tabulares, escreve e executa SQL e responde com evidências (SQL + tabela + gráfico).

> 🚧 Em construção. Este README será finalizado na Fase 8.

## Rodando localmente

```bash
uv sync
cp .env.example .env   # e preencha sua chave
uv run olheiro-load    # carrega data/raw/*.csv no DuckDB
uv run olheiro-check   # confere se está tudo ok
```
