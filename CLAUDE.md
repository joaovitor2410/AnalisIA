# CLAUDE.md: memória do projeto Olheiro

## Resumo
Olheiro é um agente de IA analista de dados. Recebe perguntas em português sobre dados tabulares,
decide quais ferramentas usar, escreve e executa SQL (DuckDB), gera gráficos e responde **com
evidência** (SQL + tabela + gráfico + insight). Recusa com honestidade quando os dados não permitem
responder. Dataset de demonstração: Campeonato Brasileiro 2003–2024 (`data/raw/brasileirao.csv`,
`data/raw/teams.csv`). Projeto de portfólio de João Victor (CC, foco em Dados/BI), construído
em fases com mentoria. **Primeiro projeto de agentes do autor: explicar conceitos antes de codar.**

## Visão do produto (definida em 2026-10-22)
Destino: integrar ao portfólio do autor como ferramenta de consultas, buscas, gráficos e
dashboards. **Onde hospedar ainda não foi decidido** (opções: app Streamlit publicado + link,
API + frontend no site do portfólio, ou só local + vídeo). Por isso: núcleo independente de
interface (agent, cache, dashboard, semantic, storage); Streamlit é só uma camada fina.
- Funções: chat analítico com evidência e passos do agente; dashboard (fixar respostas, KPIs);
  explorador de dados; perguntas prontas via cache. Upload de CSV do visitante: fora por ora.
- Ideia central: o LLM **cria** a análise uma vez; dashboard e cache **reexecutam** o SQL
  validado, sem o modelo (custo zero, sempre com os dados atuais).
- Demo pública (quando publicar): cache + limite de perguntas por sessão (escolha do autor).

## Regras de trabalho (do autor)
- Trabalhar em fases. Ao fim de cada fase: parar, resumir, **fazer o commit** (Conventional
  Commits), fazer 3 perguntas de entrevista e esperar "ok".
- **Push só depois que o autor rodar os testes e liberar.** Nunca fazer push junto com o commit.
- Antes de codar uma fase: explicar o conceito e o plano em até 15 linhas.
- Conferir documentação e versão atuais antes de usar bibliotecas/APIs. Não inventar parâmetros.
- Sempre passar os comandos exatos para rodar e testar.
- Testes com o Gemini real: o mínimo possível (cota de 20 req/dia). Validar tudo offline
  (FunctionModel, AppTest) e usar o modelo só para 1 verificação final por fase.
- Atualizar este arquivo ao fim de cada fase.

## Convenções
- Código (nomes) em inglês; comentários, docstrings e docs em português.
- Type hints em tudo, funções pequenas, sem "mágica".
- Layout `src/` (pacote `olheiro`), gerenciado com **uv**. Lint/format: `ruff`. Tipos: `mypy`
  (`uv run mypy`, zero erros; só `plotly`/`pandas` sem stubs são ignorados). Testes: `pytest`.
- Consulta de valor único: `db.scalar()` (nunca `fetchone()[0]`, que esconde o caso `None`).
- Configuração só via `olheiro.config.Settings` (pydantic-settings). Nenhum módulo lê `os.environ`.
- Segredos só no `.env` (no `.gitignore`); `.env.example` documenta as variáveis.
- Dependências entram na fase em que são usadas (não adicionar tudo de uma vez).

## Ambiente
- macOS (Apple Silicon), zsh. Projeto em `~/Desktop/AnalisIA`.
- Python **3.13** fixado em `.python-version`. O sistema tem 3.15, mas o duckdb 1.5.6 ainda não
  publica wheels para 3.15. O uv baixa o 3.13 automaticamente.
- Provedor de desenvolvimento: **Gemini Flash (nível gratuito)**. Evals (F5): `gemini-3.8-flash` ×
  `gemini-3.5-flash-lite`, no **nível pago com teto** (escolha do autor em 2026-10-22; Claude Haiku
  ficou de fora). Ativar faturamento vale para o projeto inteiro da chave: sugestão registrada de
  usar uma chave paga só para evals (`GOOGLE_API_KEY=... uv run olheiro-eval`).

## Decisões técnicas
| Decisão | Motivo |
|---|---|
| `raw` em `data/olheiro.duckdb`; `workspace` em `data/workspace.duckdb` (F3) | `raw` = dados brutos, recriado a cada `olheiro-load`. `workspace` = banco à parte, único lugar onde o agente grava. Um schema `workspace` dentro do banco principal colidia com o catálogo anexado (referência ambígua); o `olheiro-load` agora o remove. |
| `load_raw_dir` dentro de transação | Se um CSV falhar, o banco não fica pela metade. |
| `read_csv` com auto-detecção | DuckDB detecta separador (`,`/`;`), cabeçalho e tipos. Testado com `;` e acentos. |
| Nome da tabela = nome do arquivo normalizado | `Brasileirão 2024.csv` → `raw.brasileirao_2024` (sem acento/espaço; prefixo `t_` se começar com dígito). |
| Modelo em `OLHEIRO_MODEL` no formato `provedor:modelo` | Formato nativo do Pydantic AI; trocar de provedor = mudar o `.env`. |
| `.duckdb` fora do Git | É derivado dos CSVs; recriado com `uv run olheiro-load`. |
| F1 usa `generate_content`, não a Interactions API | A Interactions API (destaque na doc atual do Gemini) guarda o histórico no servidor e esconderia o loop que a fase quer ensinar. |
| Resposta de ferramenta com papel `user` no Gemini | A API só aceita `user`/`model`; `role="tool"` (exemplo da referência do SDK) dá 400. |
| Mensagem do modelo entra no histórico sem recriar | Preserva as *thought signatures* que o Gemini exige entre passos. |
| `run_sql` devolve `{"result"}` ou `{"error"}`, nunca levanta | O modelo lê o erro e corrige o SQL. Tabela markdown, máx. 50 linhas. |
| Loop recebe `generate` injetado | Testes com modelo falso roteirizado, sem rede nem cota. |
| F2: 2 ferramentas (`run_sql`, `profile_column`) + schema nas instruções | Com 2 tabelas, `list_tables` só gastaria passos. `profile_column` mostra como os valores estão escritos antes de filtrar. |
| Saída estruturada `AnalysisAnswer` (answerable, answer, sql, insights, chart) | Recusa honesta vira campo (`answerable=false`), não texto solto. |
| Evidência reexecutada pelo código | O validador roda o `sql` citado (falhou → `ModelRetry`); `ask()` reexecuta para a tabela. Números exibidos vêm do banco, nunca do texto do LLM. |
| Gráfico = `ChartSpec` na saída, renderizado pelo código (Plotly → HTML em `data/exports/`) | O modelo escolhe tipo/colunas; os dados vêm da evidência. Validador exige colunas existentes e Y numérico. Streamlit (F4) reaproveita a mesma figura. |
| Insights só podem afirmar o que está no resultado do `sql` | Teste real: o modelo inventou "3º melhor ataque"/"2ª melhor defesa" a partir de um `LIMIT 5` (ambos errados). Regra nas instruções → passou a calcular `RANK() OVER` no SQL. |
| `FallbackModel` (`OLHEIRO_FALLBACK_MODEL`) + `request_timeout=60s` | 503, cota esgotada ou requisição pendurada caem para o modelo reserva. Sem timeout, uma chamada travou >5 min. |
| Retentativas do SDK (`max_retries=2`) só no último modelo da cadeia | Principal falha na hora para o fallback entrar sem atraso; o reserva insiste em 429/5xx com espera crescente (recomendação da doc do Pydantic AI). |
| `olheiro.errors.explain_model_failure` | Sem isso, a falha total mostrava só "All models from FallbackModel failed (2 sub-exceptions)". Agora: uma linha por modelo com HTTP, motivo, limite e quando liberar. Reaproveitável no Streamlit. |
| F4: `ChartSpec` em `charts.py` com `kind="metric"` (KPI) | Visualização é do domínio de gráficos e o dashboard também a usa. `check_chart` levanta `ChartError` neutro; o agente converte em `ModelRetry`. KPI: `go.Indicator` na CLI, `st.metric` no app. |
| Cache de respostas (`cache.py`) guarda `AnalysisAnswer`, não a tabela | No acerto, valida e reexecuta o SQL (números atuais, 0 requisições). Chave = pergunta normalizada. Pausas para aprovação não entram no cache (repetir não regravaria). `AgentReport.from_cache` informa a origem. |
| Dashboard (`dashboard.py`) = SQL + `ChartSpec` em JSON | Redesenhado sem o modelo; SQL revalidado ao renderizar (o arquivo pode ser editado). Só respostas com evidência podem ser fixadas. |
| `storage.JsonFile` (lock + escrita atômica) | Compartilhado por cache e dashboard; é o ponto a trocar por um banco num deploy multiusuário. |
| Uma conexão blindada por processo + `session_cursor` por sessão | DuckDB pede um cursor por thread e não anexa o mesmo arquivo duas vezes no processo. Testado: o cursor herda a blindagem (global) mas **não** o `USE lake` (por conexão), então `session_cursor` repete o `USE`. |
| Streamlit (`ui/`, `app.py`) com `st.navigation` e páginas-função | Perguntar (chat, exemplos do cache via `st.pills`, aprovação por botões, fixar), Dashboard (KPIs em linha, cartões 2 colunas) e Dados (glossário, prévia, perfil). `width="stretch"` substituiu `use_container_width`. |
| Testes de UI com `AppTest` | `from_function` por página (o `switch_page` exige arquivo); modelo bloqueado ou `FunctionModel` via `monkeypatch` em `ui.resources.build_model`; arquivos do app apontados para `tmp_path` por variáveis de ambiente. |
| F5: evals com `pydantic-evals` e avaliadores **determinísticos** (sem LLM-juiz) | Juiz gastaria cota e teria erro próprio. `comportamento` (responde/recusa/protege), `evidencia` (resultado = SQL de gabarito: mesmas linhas, cada coluna do gabarito presente em qualquer ordem/nome, tolera escala % e arredondamento), `mencoes` (termos esperados, "a\|b"), `ancoragem` (números da resposta presentes na evidência; anos 2003–2024 são contexto). |
| Eval roda sem cache e sem fallback, workspace temporário, gravações recusadas | Mede o modelo puro; pedido de `save_result` num caso de segurança reprova. Custo medido por caso (`PRICES_PER_MILLION`, conferido em 2026-10-22). O comando mostra estimativa e pede confirmação. |
| Resultados em `evals/results/` (JSON por modelo + README comparativo) versionados | Evidência para o portfólio; regerado a cada rodada. |
| Modelo construído com chave explícita (`GoogleProvider(api_key=...)`) | Sem a chave, o provider leria `os.environ`; mantém a regra "só Settings". |
| F3: defesa em profundidade, 3 camadas independentes | Cada uma bloqueia sozinha: (1) `sql_guard` (sqlglot), (2) motor DuckDB blindado, (3) aprovação humana para gravar. |
| Camada 1, `sql_guard.check_query` | Uma única consulta (`exp.Query`); toda tabela é um nome (não função/arquivo) em `raw`/`workspace` ou um CTE. Bloqueia `read_csv(...)`, `FROM 'arquivo'`, DDL/DML, `COPY`, `ATTACH`, `SET`, catálogo explícito. Erros sem códigos de cor (campos de `ParseError.errors`). |
| Camada 2, `db.connect_agent` | Conexão `:memory:` com `ATTACH olheiro.duckdb (READ_ONLY)` + `USE lake`, `ATTACH workspace.duckdb`, `enable_external_access=false`, autoload/autoinstall de extensões desligados, `memory_limit=1GB`, `lock_configuration=true` (por último). Testado: escrever em raw, ler/gravar arquivo, ATTACH, INSTALL e destravar config falham no motor. |
| Timeout de consulta pela aplicação (`threading.Timer` + `con.interrupt()`, 10 s) | O DuckDB não tem timeout próprio (a doc de segurança manda fazer na aplicação). A conexão continua usável depois. |
| Camada 3, `save_result` com `ApprovalRequired` | 1ª passagem valida nome/SQL e só então pausa (`DeferredToolRequests` → `PendingApproval`); recusa inválidos sem incomodar o usuário. `resume()` retoma com `DeferredToolResults` (aprovado ou `ToolDenied`). Pausa/retomada (e não `input()` dentro da ferramenta) serve também ao Streamlit. Grava com `CREATE TABLE` (sem sobrescrever) usando o SQL regenerado pelo sqlglot. |
| Contexto = glossário TOML + catálogo + valores reais (`olheiro.semantic`) | `semantic/glossary.toml` (stdlib `tomllib`, sem dependência) descreve colunas e regras; tipos vêm do banco; `list_values` injeta os valores exatos (times, estados, regiões). ~750 tokens. Instrução dinâmica a cada passo: tabelas recém-salvas aparecem. Teste com os CSVs reais garante sincronia nos dois sentidos. |

Versões verificadas em 2026-10-19: duckdb 1.5.6, pydantic-settings 2.16.0, pytest 9.1.1,
ruff 0.17.1, uv 0.13.1, google-genai 2.31.0 (F1). Em 2026-10-21: pydantic-ai-slim 2.59.0,
plotly 7.1.0 (F2). Em 2026-10-22: sqlglot 30.24.0 (F3); duckdb 2.0.0 saiu, mantido 1.5.6 (atualizar na F8);
streamlit 1.66.1 e pandas 3.1.0 (F4); pydantic-evals 2.59.0 (extra `evals`) e mypy 2.4.0 (F5).
Preços pagos (2026-10-22, por 1M tokens): 3.8 Flash US$ 0,75 entrada / 3,75 saída (dobra em 2027);
3.5 Flash-Lite US$ 0,30 / 2,50. Thinking é cobrado como saída. Na 2.59, `result.usage` é propriedade (não método); o banner some com
`pydantic_ai.BANNER_ENABLED = False`.
Pydantic AI + Gemini: extra `pydantic-ai-slim[google]`, prefixo `google:`, chave em
`GOOGLE_API_KEY` (docs: https://pydantic.dev/docs/ai/models/google/). Modelo Flash estável
atual: `gemini-3.8-flash` (a chave tem acesso; em 2026-10-20 deu 503 "high demand" repetidas
vezes, assim como o 3.7; em 2026-10-21 respondeu normalmente). Reserva:
`gemini-3.5-flash-lite` em `OLHEIRO_FALLBACK_MODEL` (o `.env` do autor já tem).

**Cotas do nível gratuito (verificadas em 2026-10-21 pelos erros 429):** `gemini-3.8-flash` e
`gemini-3.5-flash` têm **20 requisições/dia cada**, contadas por modelo e por projeto (não por
chave). Reiniciam à meia-noite do Pacífico (~04:00 de Brasília). Uma pergunta ao agente gasta
2–7 requisições → ~3–10 perguntas/dia por modelo. Os números exatos só aparecem em
https://aistudio.google.com/rate-limit. Outros fatos: `gemini-3.5-flash` é servido como
`gemini-3.6-flash` (`model_version`); `gemini-2.5-flash` dá 404 para contas novas;
`gemini-3.5-flash-lite` e `gemini-3.1-flash-lite` respondem, e o lite resolveu uma pergunta em 2
requisições. O 429 de cota diária chega como `ModelRateLimitError` (mesma classe do limite por
minuto); só o texto ("limit: 20", "retry in 6h...") diferencia os dois.

Rede/sandbox (2026-10-20): o IPv6 do Wi-Fi do autor está quebrado e o `uv` não cai para IPv4.
Para instalar pacotes: `networksetup -setv6off Wi-Fi`, depois `uv add ...`, depois
`networksetup -setv6automatic Wi-Fi`. Chamadas ao Gemini precisam rodar fora do sandbox do
Claude Code.

## Estrutura
```
src/olheiro/config.py       configurações (Settings)
src/olheiro/db.py           carga de CSVs (olheiro-load) e conexão blindada do agente
src/olheiro/check_setup.py  diagnóstico do ambiente (comando olheiro-check)
src/olheiro/tools.py        execução de SQL (query_rows, com timeout) e ferramentas: run_sql,
                            profile_column, save_result
src/olheiro/sql_guard.py    validador de SQL (camada 1 da defesa)
src/olheiro/semantic.py     glossário -> contexto do agente (camada de contexto)
src/olheiro/agent.py        agente Pydantic AI: saída estruturada, validador, ask()/resume()
src/olheiro/charts.py       ChartSpec (bar/line/metric), check_chart, figura Plotly
src/olheiro/cli.py          comando olheiro-ask (--verbose, --no-cache)
src/olheiro/cache.py        cache de respostas + ask_with_cache
src/olheiro/dashboard.py    itens fixados (SQL + ChartSpec) e render_item
src/olheiro/storage.py      JsonFile: modelo Pydantic em JSON com lock e escrita atômica
src/olheiro/app.py          entrada do Streamlit (navegação + barra lateral)
src/olheiro/ui/             páginas Perguntar, Dashboard, Dados + recursos e componentes
src/olheiro/errors.py       explica falhas do modelo (cota, 503, prazo) em português
src/olheiro/evaluation.py   evals: tarefa, avaliadores, resumo (comando olheiro-eval)
evals/cases.yaml            39 casos com gabarito em 7 categorias
evals/results/              resultados por modelo + README comparativo
learning/manual_loop.py     F1: loop do agente à mão com google-genai (material de estudo)
tests/                      pytest (pythonpath inclui learning/)
semantic/glossary.toml      significado das colunas e regras de negócio
data/raw/                   CSVs de entrada
data/exports/               exportações do agente (ignorado no Git)
```

## Dados (inspecionados em 2026-10-20)
- `raw.brasileirao` (450 linhas): **classificação final** por temporada, não jogos. Colunas:
  season, place, team, points, played, won, draw, loss, goals, goals_taken, goals_diff (BIGINT,
  exceto team). 2003–2024; 2003–2005 têm mais times/jogos (46/42 rodadas).
- `raw.teams` (45 linhas): team, acronym, full_name, founded, stadium, city, state, region.
  `region` em inglês (Southeast, Northeast...). Junta com `brasileirao` por `team`.
- CSV com `,`, UTF-8, acentos ok. Não há artilharia nem dados por jogo: perguntas assim devem
  ser recusadas.
- Armadilhas (achadas no perfil dos dados, registradas no glossário): `Grêmio Barueri` (2009 e
  2010) não está em `raw.teams` (JOIN interno o perde); `points` ≠ `3*won + draw` em 11 linhas
  (2003, 2004, 2010, 2013), por punições **ou inconsistências da fonte** (em 2003 há pontos
  acima do calculado; corrigido na F5); `region = 'Central'` é Centro-Oeste; `state` sem acento
  ("Sao Paulo"); 44 times distintos em `brasileirao`.

## Status das fases
- [x] **Fase 0: Fundação.** Estrutura, uv, config, carga no DuckDB, `olheiro-check`, 6 testes.
  Dataset real carregado e conferido na F1.
- [x] **Fase 1: loop "na mão".** `learning/manual_loop.py` + `olheiro.tools.run_sql`, 16 testes.
  Testado com o Gemini real: pergunta simples ok; pergunta com JOIN fez 2 passos (explorou e
  depois cruzou tabelas). Rodar: `uv run python learning/manual_loop.py "pergunta"`.
- [x] **Fase 2: agente Pydantic AI.** 2 ferramentas, saída estruturada validada, evidência
  reexecutada, gráfico Plotly, fallback + timeout, CLI `olheiro-ask`. 36 testes (FunctionModel).
  Testado com o Gemini real: pergunta simples, ranking (RANK/QUALIFY), série com gráfico (7
  requisições) e recusa (artilheiro → `answerable=false`).
  Rodar: `uv run olheiro-ask [--verbose] "pergunta"`.
- [x] **Fase 3: segurança e contexto.** 3 camadas (sqlglot, motor blindado, aprovação humana),
  timeout de consulta, glossário + valores reais no contexto, `olheiro-check` verifica blindagem
  e glossário. 75 testes. Teste real único (4 requisições): aproveitamento dos campeões (regra
  do glossário aplicada: Cruzeiro 2003 em 3º, não 1º) + `save_result` aprovado → tabela gravada.
- [x] **Fase 4: produto no Streamlit.** Chat com evidência e passos, aprovação por botões,
  KPIs, dashboard reexecutado sem LLM, explorador de dados, cache de respostas (exemplos) e
  limite por sessão. 97 testes (inclui AppTest). Teste real único: KPI "títulos do Flamengo"
  = 3 (4 requisições) e a repetição veio do cache (0 requisições).
  Rodar: `uv run streamlit run src/olheiro/app.py`.
- [~] **Fase 5: evals.** Pronto e testado offline: 39 casos (gabaritos conferidos no banco e
  reexecutados por teste), 4 avaliadores, resumo comparativo, estimativa de custo. 106 testes.
  **Falta a rodada real** (~US$ 0,90 os dois modelos): espera o autor ativar o faturamento.
  Rodar: `uv run olheiro-eval --model google:gemini-3.8-flash` e `--model google:gemini-3.5-flash-lite`.
  Os gabaritos acharam 2 erros no glossário da F3 (Barueri em 2009 também; pontos ≠ 3V+E nem
  sempre é punição), corrigidos.
- [ ] Fase 6: observabilidade
- [ ] Fase 7: servidor MCP
- [ ] Fase 8: Docker, CI, deploy, README

## Pendências / em aberto
- **Segurança residual:** as camadas são defesa em profundidade, não sandbox (a doc do DuckDB
  recomenda isolamento de SO/contêiner). Para deploy (F8): rodar em contêiner sem rede de saída
  além da API do modelo.
- **Ancoragem é heurística:** confere números, não afirmações qualitativas ("melhor", "pior").
  Um LLM-juiz poderia cobrir isso depois, com custo.
- **Latência/custo (Fase 6):** pergunta com gráfico levou 7 requisições (~19k tokens); recusa
  levou ~55 s. Observar por passo.
- **Para a publicação (F8):** decidir a hospedagem; cache curado de exemplos versionado (hoje
  `data/answer_cache.json` é local e ignorado no Git); dashboard por visitante (hoje é um
  arquivo único, compartilhado); `OLHEIRO_SESSION_QUESTION_LIMIT` ligado.
- **Limitações conhecidas:** perguntas independentes (sem memória de conversa: "e em 2020?" não
  funciona); resposta do cache pode ficar com texto desatualizado se os dados mudarem (os
  números não, pois o SQL é reexecutado). Apagar `data/answer_cache.json` limpa o cache.
- Empates: Corinthians e Palmeiras têm 4 títulos cada. Um teste meu com `LIMIT 1` escondeu o
  empate; o agente agora recebe a regra "confira empates (RANK() = 1)".
- Aviso `DeprecationWarning: There is no current event loop` vem do `pydantic_graph` no
  `run_sync` (interno da biblioteca); filtrado no pytest (`filterwarnings`).
- Decidir se os CSVs do dataset vão para o Git (necessário para o deploy da Fase 8; checar licença
  da fonte).
