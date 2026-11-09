# Resultados das avaliações

Gerado por `olheiro-eval`. Suítes e casos em `evals/`; avaliadores determinísticos em
`src/olheiro/evaluation.py` (sem LLM-juiz).

| Métrica | `google:gemini-3.8-flash` (2026-11-09) | `google:gemini-3.8-flash` (2026-11-09) | `google:gemini-3.8-flash` (2026-11-09) |
|---|---|---|---|
| Suíte | brasileirao | estoque | vendas |
| Casos | 15 | 10 | 10 |
| Comportamento correto | 100% | 80% | 90% |
| Evidência = gabarito | 87% | 75% | 86% |
| Cita o esperado | 100% | – | 100% |
| Números ancorados (média) | 90% | 96% | 85% |
| Requisições por caso | 2.9 | 3.5 | 3.4 |
| Tokens por caso | 10,030 | 10,474 | 8,590 |
| Tempo por caso | 14.7 s | 23.4 s | 15.9 s |
| Custo total | US$ 0.1650 | US$ 0.1157 | US$ 0.0923 |
| Erros de API | 0 | 2 | 1 |

## Comportamento correto por categoria

| Categoria | `google:gemini-3.8-flash` | `google:gemini-3.8-flash` | `google:gemini-3.8-flash` |
|---|---|---|---|
| agregacao | 100% | 50% | 100% |
| join | – | 50% | 100% |
| proporcao | – | – | 100% |
| qualidade | – | 100% | – |
| ranking | 100% | – | 100% |
| recusa | – | 100% | 50% |
| seguranca | – | 100% | 100% |
| simples | 100% | – | – |
| temporal | – | – | 100% |
| tipos | – | 100% | – |
