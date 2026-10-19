# CLAUDE.md: memória do projeto Olheiro

## Resumo
Olheiro é um agente de IA analista de dados. Recebe perguntas em português sobre dados tabulares,
decide quais ferramentas usar, escreve e executa SQL (DuckDB), gera gráficos e responde **com
evidência** (SQL + tabela + gráfico + insight). Recusa com honestidade quando os dados não permitem
responder. Dataset de demonstração: Campeonato Brasileiro 2003–2024 (`data/raw/brasileirao.csv`,
`data/raw/teams.csv`). Projeto de portfólio de João Victor (CC, foco em Dados/BI), construído
em fases com mentoria. **Primeiro projeto de agentes do autor: explicar conceitos antes de codar.**

## Regras de trabalho (do autor)
- Trabalhar em fases. Ao fim de cada fase: parar, resumir, sugerir commit (Conventional Commits),
  fazer 3 perguntas de entrevista e esperar "ok".
- Antes de codar uma fase: explicar o conceito e o plano em até 15 linhas.
- Conferir documentação e versão atuais antes de usar bibliotecas/APIs. Não inventar parâmetros.
- Sempre passar os comandos exatos para rodar e testar.
- Atualizar este arquivo ao fim de cada fase.

## Convenções
- Código (nomes) em inglês; comentários, docstrings e docs em português.
- Type hints em tudo, funções pequenas, sem "mágica".
- Layout `src/` (pacote `olheiro`), gerenciado com **uv**. Lint/format: `ruff`. Testes: `pytest`.
- Configuração só via `olheiro.config.Settings` (pydantic-settings). Nenhum módulo lê `os.environ`.
- Segredos só no `.env` (no `.gitignore`); `.env.example` documenta as variáveis.
- Dependências entram na fase em que são usadas (não adicionar tudo de uma vez).

## Ambiente
- macOS (Apple Silicon), zsh. Projeto em `~/Desktop/AnalisIA`.
- Python **3.13** fixado em `.python-version`. O sistema tem 3.15, mas o duckdb 1.5.6 ainda não
  publica wheels para 3.15. O uv baixa o 3.13 automaticamente.
- Provedor de desenvolvimento: **Gemini Flash (nível gratuito)**. Claude Haiku 5.5 como 2º modelo
  para comparação nas evals (Fase 5).

## Decisões técnicas
| Decisão | Motivo |
|---|---|
| DuckDB com schemas `raw` e `workspace` | `raw` = dados brutos, recriado do zero a cada `olheiro-load`, nunca alterado pelo agente. `workspace` = único lugar onde o agente poderá escrever (Fase 3). |
| `load_raw_dir` dentro de transação | Se um CSV falhar, o banco não fica pela metade. |
| `read_csv` com auto-detecção | DuckDB detecta separador (`,`/`;`), cabeçalho e tipos. Testado com `;` e acentos. |
| Nome da tabela = nome do arquivo normalizado | `Brasileirão 2024.csv` → `raw.brasileirao_2024` (sem acento/espaço; prefixo `t_` se começar com dígito). |
| Modelo em `OLHEIRO_MODEL` no formato `provedor:modelo` | Formato nativo do Pydantic AI; trocar de provedor = mudar o `.env`. |
| `.duckdb` fora do Git | É derivado dos CSVs; recriado com `uv run olheiro-load`. |

Versões verificadas em 2026-10-19: duckdb 1.5.6, pydantic-settings 2.16.0, pytest 9.1.1,
ruff 0.17.1, uv 0.13.1, pydantic-ai-slim 2.57.0 (Fase 2), google-genai 2.31.0.
Pydantic AI + Gemini: extra `pydantic-ai-slim[google]`, prefixo `google:`, chave em
`GOOGLE_API_KEY` (docs: https://pydantic.dev/docs/ai/models/google/). Modelo Flash estável
atual: `gemini-3.8-flash`. **Não confirmado** se está no nível gratuito: checar em
https://aistudio.google.com/rate-limit.

## Estrutura
```
src/olheiro/config.py       configurações (Settings)
src/olheiro/db.py           conexão DuckDB + carga de CSVs (comando olheiro-load)
src/olheiro/check_setup.py  diagnóstico do ambiente (comando olheiro-check)
tests/                      pytest
data/raw/                   CSVs de entrada
data/exports/               exportações do agente (ignorado no Git)
```
Pastas futuras: `learning/` (F1), `semantic/` (F3), `evals/` (F5).

## Status das fases
- [x] **Fase 0: Fundação.** Estrutura, uv, config, carga no DuckDB, `olheiro-check`, 6 testes.
  Testado com CSVs fake; **falta rodar com o dataset real** (o autor vai colocar os CSVs).
- [ ] Fase 1: loop "na mão" (learning/, SDK do provedor, 1 ferramenta run_sql)
- [ ] Fase 2: agente Pydantic AI (ferramentas 1–4, saída estruturada, CLI)
- [ ] Fase 3: segurança e contexto (sqlglot, read-only, glossário, save_result com confirmação)
- [ ] Fase 4: Streamlit
- [ ] Fase 5: evals (30+ perguntas, 2 modelos)
- [ ] Fase 6: observabilidade
- [ ] Fase 7: servidor MCP
- [ ] Fase 8: Docker, CI, deploy, README

## Pendências / em aberto
- Inspecionar colunas reais de `brasileirao.csv` e `teams.csv` após a carga (encoding, separador,
  tipos de data) e registrar aqui.
- Decidir se os CSVs do dataset vão para o Git (necessário para o deploy da Fase 8; checar licença
  da fonte).
