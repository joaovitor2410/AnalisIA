# Resultados das avaliações

Gerado por `olheiro-eval`. Suítes e casos em `evals/`; avaliadores determinísticos em
`src/olheiro/evaluation.py` (sem LLM-juiz).

| Métrica | `google:gemini-3.5-flash-lite` (2026-11-09) | `google:gemini-3.8-flash` (2026-11-09) | `google:gemini-3.5-flash-lite` (2026-11-09) | `google:gemini-3.8-flash` (2026-11-09) | `google:gemini-3.5-flash-lite` (2026-11-09) | `google:gemini-3.8-flash` (2026-11-09) |
|---|---|---|---|---|---|---|
| Suíte | brasileirao | brasileirao | estoque | estoque | vendas | vendas |
| Casos | 39 | 39 | 10 | 10 | 10 | 10 |
| Comportamento correto | 90% | 95% | 70% | 90% | 80% | 100% |
| Evidência = gabarito | 79% | 90% | 88% | 88% | 100% | 86% |
| Cita o esperado | 94% | 94% | – | – | 100% | 100% |
| Números ancorados (média) | 82% | 94% | 88% | 97% | 99% | 92% |
| Requisições por caso | 3.5 | 2.7 | 4.7 | 4.5 | 3.6 | 3.5 |
| Tokens por caso | 10,709 | 10,034 | 12,532 | 14,578 | 8,373 | 9,248 |
| Tempo por caso | 4.0 s | 15.4 s | 5.4 s | 22.8 s | 4.0 s | 13.6 s |
| Custo total | US$ 0.1524 | US$ 0.4376 | US$ 0.0484 | US$ 0.1602 | US$ 0.0317 | US$ 0.0957 |
| Falhas de execução | 4 | 2 | 2 | 1 | 2 | 0 |

## Comportamento correto por categoria

| Categoria | `google:gemini-3.5-flash-lite` | `google:gemini-3.8-flash` | `google:gemini-3.5-flash-lite` | `google:gemini-3.8-flash` | `google:gemini-3.5-flash-lite` | `google:gemini-3.8-flash` |
|---|---|---|---|---|---|---|
| agregacao | 83% | 83% | 100% | 100% | 100% | 100% |
| glossario | 100% | 100% | – | – | – | – |
| join | – | – | 50% | 50% | 100% | 100% |
| juncao | 80% | 80% | – | – | – | – |
| proporcao | – | – | – | – | 100% | 100% |
| qualidade | – | – | 100% | 100% | – | – |
| ranking | 100% | 100% | – | – | 100% | 100% |
| recusa | 60% | 100% | 0% | 100% | 0% | 100% |
| seguranca | 100% | 100% | 0% | 100% | 100% | 100% |
| simples | 100% | 100% | – | – | – | – |
| temporal | – | – | – | – | 100% | 100% |
| tipos | – | – | 100% | 100% | – | – |
