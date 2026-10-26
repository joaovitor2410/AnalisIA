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
Em 2026-10-26, o autor escolheu **preparar Docker e CI primeiro (F8A)**; publicação online
fica para a F8B. Autorizou e recebeu o push da F7 (`4f667ce`) em `origin/main`.
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
| F6: observabilidade em 2 camadas | **Traces** OpenTelemetry (padrão de mercado, sem fornecedor fixo) para o passo a passo; **registro de execuções** (`data/runs.jsonl`, um `RunRecord` por chamada) para métricas de produto. Ligados pelo `trace_id`. |
| Instrumentação nativa do Pydantic AI (`Agent.instrument_all(InstrumentationSettings(...))`) + span raiz `olheiro.pergunta` | Spans `invoke_agent olheiro` > `chat <modelo>` (tokens) e `execute_tool <nome>`. Destino em `OLHEIRO_TRACING`: `file` (JSONL local, padrão), `otlp` (Jaeger/Tempo/Phoenix/Logfire) ou `off`. `BatchSpanProcessor` + `atexit` (CLI grava os pendentes ao sair). |
| `OLHEIRO_TRACE_CONTENT` (`include_content`) | Privacidade: com `false`, perguntas, respostas e argumentos/resultados de ferramentas não vão para os traces (testado). Desligar numa demo pública. |
| `telemetry.tracked()` em app, CLI e eval | Mede, abre o span raiz e grava o registro; erros também (com `explain_model_failure`) e são relançados. Sem resultado (ex.: limite da sessão), não grava. O tempo de decisão do usuário na aprovação fica fora da medida. |
| `tracing.py` é o único módulo com estado global | O OpenTelemetry é global por processo; `setup_tracing` é idempotente e `reset_tracing` isola os testes (`tests/conftest.py` desliga o tracing e aponta os logs para `tmp_path` em todo teste). |
| Página Operação | KPIs (perguntas, % cache, % erro, latência p50/p95, requisições/pergunta, custo equivalente), latência no tempo, desfechos, execuções recentes e **cascata do trace** de cada pergunta. Lê só arquivos; não chama o modelo. |
| `pricing.py` compartilhado (evals e Operação) | Custo equivalente no nível pago; inclui `gemini-3.6-flash` (nome servido do 3.5 Flash). |
| Modelo construído com chave explícita (`GoogleProvider(api_key=...)`) | Sem a chave, o provider leria `os.environ`; mantém a regra "só Settings". |
| F7: SDK oficial `mcp` 2.x (`MCPServer`), transporte stdio local | Cliente inicia e encerra o processo; sem porta HTTP. `olheiro-mcp` e `python -m olheiro.mcp_server`. Banner do Pydantic AI desligado para preservar stdout do protocolo. Negociação atual e legada testadas em subprocesso. |
| MCP com dois caminhos de análise | `run_sql` e `profile_column`: o modelo do cliente conduz, sem Gemini no servidor. `ask_question`: delega ao núcleo `ask`, com cache opcional e `AnalysisAnswer` + evidência + consumo. Modelo construído só na falta do cache: SQL, recurso e cache funcionam sem chave. |
| MCP somente leitura nesta fase | Não expõe `save_result` nem retomada/aprovação por booleano. `PendingApproval` do agente interno termina com erro de ferramenta explicativo, sem gravar tabela/cache; usuário pode salvar via CLI/app com aprovação humana. Workspace continua anexado pelo núcleo existente. |
| MCP: lifespan + um cursor por chamada | Fábrica não abre banco nem exige chave; lifespan abre/fecha conexão blindada, glossário, cache e logs. Handlers síncronos rodam nos workers do SDK: `ask.run_sync` fica fora do loop assíncrono. Cada chamada cria/fecha `session_cursor`, inclusive em erro; concorrência testada. |
| MCP: recurso `olheiro://context`, prompt `analyze_data` e saída estruturada | Contexto relê o catálogo a cada acesso. SDK 2.3 não injeta `Context` em recurso estático: estado fica numa closure da fábrica, preenchida/limpa pelo lifespan, sem global. Tabelas JSON preservam ordem e colunas repetidas; datas/decimais viram strings, corte indicado por `truncated`. Gráfico enviado como `ChartSpec`, sem arquivo HTML. |
| MCP: erros de execução usam `ToolError` | SQL proibido, coluna inválida e falha do modelo chegam como `isError=true`; recusa por dados ausentes continua resultado normal (`answerable=false`). `tracked(..., source="mcp")` integra perguntas à Operação (origem MCP selecionada por padrão); SQL direto/perfis/recursos/prompts não contam como perguntas ao agente. |
| F8A: `olheiro-app` separa a entrada web do MCP | Inicia Streamlit por caminho absoluto, encaminha opções e usa `execv` para sinais chegarem ao servidor. Carga inicial só se a base faltar; valida tabelas e glossário. Publica arquivo completo por link atômico sem sobrescrever uma base criada simultaneamente; falhas não deixam banco parcial. |
| F8A: Docker em duas etapas + Compose local | Python 3.13.16 e uv 0.13.1; dependências pelo lock, sem dev no runtime. Instalação editável preserva a raiz dos recursos em `/app/src`, que fica em leitura. Base bruta preparada no build; estado em volume `/state`, temporários em tmpfs. Sem root, capabilities removidas, sem novos privilégios, limites de recursos e interface em loopback. `.dockerignore` por lista de inclusão exclui segredos, bancos e logs locais. |
| F8A: rede interna + proxy Squid | Aplicação só na rede `internal`; proxy alcança a rede externa e só permite CONNECT para `generativelanguage.googleapis.com:443`. Sem inspeção TLS; SDK Gemini usa `trust_env=True`. Configuração ainda precisa de build/smoke real em Docker; não confundir revisão estática com isolamento validado. |
| F8A: GitHub Actions de qualidade e contêiner | Ações por SHA, permissão contents:read, sem segredos nem chamadas ao Gemini. Ruff, format, mypy, pytest, wheel/sdist; depois build/health e smoke da base, AppTest, usuário, escrita e rede. Não publica imagem nem faz deploy. Só executará remotamente após push liberado pelo autor. |
| F8A: DuckDB segue `>=1.5.6,<2` | Reavaliada a atualização prevista: 2.0 muda o formato padrão dos arquivos. Separar a migração com cópias e retorno do empacotamento evita alterar os bancos do autor sem validação própria. Não houve mudança da versão instalada, 1.5.6. |
| F8A: limite de sessão 0 suportado no app completo | Antes a barra lateral dividia por zero. Agora mostra o limite esgotado e permite cache; configuração rejeita valores negativos. AppTest cobre ausência de limite, 0 e 5. |
| Correção pós-F8A: conflito de workspace tratado | Uma instância antiga do Streamlit mantinha o lock e outra falhava ao iniciar. `connect_agent` fecha conexões parciais em qualquer falha e converte o conflito em `WorkspaceInUseError`, com PID e orientação. `olheiro-app` verifica o workspace antes de subir o servidor; app direto mostra mensagem e botão de tentar novamente; CLI e diagnóstico também explicam o conflito. Sem apagar/substituir o workspace ou mudar silenciosamente para outro banco. **151 testes**, incluindo lock entre dois processos reais, liberação do raw após falha, recuperação no AppTest e recusa de startup duplicado; lint/format/mypy sem erros. |
| F3: defesa em profundidade, 3 camadas independentes | Cada uma bloqueia sozinha: (1) `sql_guard` (sqlglot), (2) motor DuckDB blindado, (3) aprovação humana para gravar. |
| Camada 1, `sql_guard.check_query` | Uma única consulta (`exp.Query`); toda tabela é um nome (não função/arquivo) em `raw`/`workspace` ou um CTE. Bloqueia `read_csv(...)`, `FROM 'arquivo'`, DDL/DML, `COPY`, `ATTACH`, `SET`, catálogo explícito. Erros sem códigos de cor (campos de `ParseError.errors`). |
| Camada 2, `db.connect_agent` | Conexão `:memory:` com `ATTACH olheiro.duckdb (READ_ONLY)` + `USE lake`, `ATTACH workspace.duckdb`, `enable_external_access=false`, autoload/autoinstall de extensões desligados, `memory_limit=1GB`, `lock_configuration=true` (por último). Testado: escrever em raw, ler/gravar arquivo, ATTACH, INSTALL e destravar config falham no motor. |
| Timeout de consulta pela aplicação (`threading.Timer` + `con.interrupt()`, 10 s) | O DuckDB não tem timeout próprio (a doc de segurança manda fazer na aplicação). A conexão continua usável depois. |
| Camada 3, `save_result` com `ApprovalRequired` | 1ª passagem valida nome/SQL e só então pausa (`DeferredToolRequests` → `PendingApproval`); recusa inválidos sem incomodar o usuário. `resume()` retoma com `DeferredToolResults` (aprovado ou `ToolDenied`). Pausa/retomada (e não `input()` dentro da ferramenta) serve também ao Streamlit. Grava com `CREATE TABLE` (sem sobrescrever) usando o SQL regenerado pelo sqlglot. |
| Contexto = glossário TOML + catálogo + valores reais (`olheiro.semantic`) | `semantic/glossary.toml` (stdlib `tomllib`, sem dependência) descreve colunas e regras; tipos vêm do banco; `list_values` injeta os valores exatos (times, estados, regiões). ~750 tokens. Instrução dinâmica a cada passo: tabelas recém-salvas aparecem. Teste com os CSVs reais garante sincronia nos dois sentidos. |

Versões verificadas em 2026-10-19: duckdb 1.5.6, pydantic-settings 2.16.0, pytest 9.1.1,
ruff 0.17.1, uv 0.13.1, google-genai 2.31.0 (F1). Em 2026-10-21: pydantic-ai-slim 2.59.0,
plotly 7.1.0 (F2). Em 2026-10-22: sqlglot 30.24.0 (F3); duckdb 2.0.0 saiu, mantido 1.5.6 (atualizar na F8);
streamlit 1.66.1 e pandas 3.1.0 (F4); pydantic-evals 2.59.0 (extra `evals`) e mypy 2.4.0 (F5);
opentelemetry-sdk e exporter-otlp-proto-http 1.45.1 (F6, mesma versão da API trazida pelo Pydantic AI).
Em 2026-10-26: `mcp` e `mcp-types` **2.3.0** (F7; requisito `mcp>=2.3,<3`, versão exata no
`uv.lock`). Documentação oficial atual usa `MCPServer`, não `FastMCP` da linha 1.x:
https://py.sdk.modelcontextprotocol.io/ (ferramentas, recursos, erros, lifespan, testes e hosts).
Referências e instruções de conexão em `docs/mcp.md`.
F8A (2026-10-26): uv 0.13.1 mantido no Docker/CI; Python 3.13.16 na imagem, mesmo ambiente
local. Referências de uv, Compose, Squid e migração DuckDB em `docs/deployment.md`.
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
src/olheiro/ui/             páginas Perguntar, Dashboard, Dados, Operação + recursos e componentes
src/olheiro/errors.py       explica falhas do modelo (cota, 503, prazo) em português
src/olheiro/evaluation.py   evals: tarefa, avaliadores, resumo (comando olheiro-eval)
src/olheiro/pricing.py      preço por modelo e custo equivalente
src/olheiro/tracing.py      OpenTelemetry: setup, exportador JSONL, leitura de um trace
src/olheiro/telemetry.py    RunRecord, RunLog e tracked() (registro de execuções)
src/olheiro/mcp_server.py   servidor MCP stdio: SQL, perfil, perguntas, contexto e prompt
src/olheiro/launcher.py     entrada web olheiro-app, validação/carga inicial sem sobrescrever
examples/mcp_client.py     cliente stdio de demonstração (SQL sem cota; --question para agente)
docs/mcp.md                contrato MCP, limites e conexão ao Claude Desktop/Code
Dockerfile / compose.yaml  imagem e execução local com volume e rede interna
deploy/                    Dockerfile/config Squid e smoke do runtime sem Gemini
.github/workflows/ci.yml   qualidade, build do pacote e verificação dos contêineres
docs/deployment.md          operação, validação e limites da entrega F8A
data/raw/SOURCE.md          fonte Kaggle, condições informadas e hashes dos CSVs
evals/cases.yaml            39 casos com gabarito em 7 categorias
evals/results/              resultados por modelo + README comparativo
learning/manual_loop.py     F1: loop do agente à mão com google-genai (material de estudo)
tests/                      pytest (pythonpath inclui learning/; conftest isola tracing e logs)
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
- [x] **Fase 6: observabilidade.** Traces OpenTelemetry (arquivo/OTLP/off, privacidade),
  registro de execuções, página Operação com KPIs e cascata do trace. 114 testes. Teste real
  único (1 requisição): recusa do artilheiro em **4,6 s e 1 requisição**, contra ~55 s e 3
  requisições na F2 (o glossário da F3 eliminou a exploração; agora medido).
- [x] **Fase 7: servidor MCP.** SDK oficial 2.3.0, stdio local, `run_sql`, `profile_column`,
  `ask_question` com evidência estruturada/cache, recurso de contexto e prompt de análise.
  Só leitura: pedidos de gravação não são retomados e viram erro explicativo. Origem MCP
  na Operação, cliente de demonstração e guia de conexão ao Claude. **138 testes** (23 de MCP
  + caso MCP no AppTest da Operação; antes: 114), ruff lint/format e mypy sem erros.
  Subprocessos com protocolo atual/legado e diretório inicial diferente, concorrência, erros,
  cache, tipos JSON e fechamento de conexões verificados offline. Demonstração SQL real:
  **22 temporadas**, sem Gemini. Teste real único via cliente MCP (sem cache): recusa de
  artilharia, **1 requisição em 5,1 s**, `gemini-3.8-flash`, registro ligado a 3 spans.
  Rodar: `uv run olheiro-mcp`; testar sem cota: `uv run python examples/mcp_client.py`.
- [~] **Fase 8: Docker, CI, deploy, README.** Dividida conforme escolha do autor:
  - **F8A preparada:** Dockerfile em duas etapas, Compose local com saída restrita via Squid,
    workflow CI de qualidade e contêiner, README refeito, origem dos dados e guia de operação.
    `olheiro-app` inicializa a base com segurança; limite zero da sessão corrigido.
    **147 testes offline**, lint/format/mypy; build wheel/sdist e conteúdo dos pacotes verificados
    (sem `.env`/bancos). Ambiente temporário com `uv sync --locked --no-dev`: app iniciou pelo
    AppTest **sem pytest e sem chave**. Compose validado contra schema oficial, CI validada
    com actionlint **1.7.12** e sintaxe shell conferida. Nenhuma chamada
    extra ao Gemini nesta etapa de infraestrutura.
    **Falta validar build/runtime Docker:** Docker não está instalado neste Mac. A CI inclui
    essa validação, mas só rodará remotamente após o próximo push aprovado. Não foi executada
    nem apresentada como aprovada. Comandos: `docker compose up --build --detach --wait` e
    `docker compose exec -T app python deploy/smoke.py`.
    Push autorizado em 2026-10-26: commits `3eed474` e `809f2bd` enviados. Primeira CI
    (`40363787090`) encontrou um teste de limite que dependia da chave local; corrigido
    com FunctionModel explícito, sem chamadas ao provedor. Nova validação em acompanhamento.
  - **F8B pendente:** hospedagem, isolamento por visitante, exemplos curados, condições de
    redistribuição dos dados, migração DuckDB 2.x e publicação online. Não autorizada nesta etapa.

## Pendências / em aberto
- **Segurança residual:** as camadas são defesa em profundidade, não sandbox (a doc do DuckDB
  recomenda isolamento de SO/contêiner). Para deploy (F8): rodar em contêiner sem rede de saída
  além da API do modelo.
- **Ancoragem é heurística:** confere números, não afirmações qualitativas ("melhor", "pior").
  Um LLM-juiz poderia cobrir isso depois, com custo.
- **Observabilidade local:** `data/traces.jsonl` e `data/runs.jsonl` crescem sem rotação (ok
  para uso local; num deploy, usar `otlp` e um backend com retenção).
- **MCP local (F7):** só stdio e leitura. HTTP remoto/autenticação e eventual aprovação humana
  por elicitation ficam para uma evolução futura; não há aprovação por argumento do modelo.
  `OLHEIRO_SESSION_QUESTION_LIMIT` limita só o app Streamlit, não o MCP local. Configuração de
  clientes documentada, sem alterar arquivos do Claude automaticamente.
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
- **Origem dos CSVs registrada (F8A):** os arquivos já estavam versionados. Fonte indicada pelo
  autor: Kaggle, Lucas Yukio Imafuko, Brazilian Football Dataset [2003 - 2024]. API pública
  consultada em 2026-10-26: `licenseName="Other (specified in description)"`; descrição atribui
  à CBF e informa finalidade educacional. Não foi identificada licença aberta específica;
  confirmar redistribuição antes de publicar demo/imagem. MIT do código não cobre essa decisão.
  Link, detalhes e SHA-256 em `data/raw/SOURCE.md`.
