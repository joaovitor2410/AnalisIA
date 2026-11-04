# CLAUDE.md: memória do projeto AnalisIA (antes Olheiro)

## Resumo
AnalisIA é um agente de IA analista de dados. Recebe perguntas em português sobre dados tabulares,
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
Depois autorizou o push da F8A/correção de lock e escolheu **preparar a demo antes de publicar**:
F8B = demonstração local; hospedagem e publicação passam à F8C. F8A validada no runner Linux.
Em **2026-10-27**, o autor pediu uma varredura completa e autorizou mudanças para analisar
outras bases. Escolheu **CSV e Parquet** como primeiras fontes. **F9A** prioriza esse núcleo
flexível antes da publicação; a auditoria e o próximo roteiro estão em
`docs/auditoria-2026-10-27.md`.
Ainda em 27/10, o autor pediu uma renovação visual e definiu o nome **AnalisIA**. A F9A.1
entrega identidade, navegação e interações; F9B continua reservada a qualidade/semântica.
Em **04/11/2026**, nova varredura confirmou a F9B e sua CI verde (`0e20330`, execução
`41637039752`). O autor autorizou avançar se o projeto estivesse apto. Entregue a preparação
offline da **F5 complementar**, com suítes de futebol, vendas e estoque (59 casos/44
gabaritos SQL). A rodada paga permanece pendente; **F9C (contexto de conversa)** é a próxima
fase funcional, após a revisão de fim de fase. Relatório: `docs/auditoria-2026-11-04.md`.
Ainda em **04/11**, o autor autorizou o push e a próxima fase: `94f5cca` enviado a
`origin/main`, CI `41843227764` aprovada (qualidade + contêiner pessoal/demo).
**F9C entregue:** contexto curto por sessão no app e na CLI `--chat`, cache contextual e
aprovações vinculadas à sessão/regras e de uso único. Guia: `docs/conversa.md`.
- Funções: chat analítico com evidência e passos do agente; dashboard (fixar respostas, KPIs);
  explorador de dados; perguntas prontas via cache; importação/seleção de bases pessoais
  CSV/Parquet (F9A). Upload do visitante da demo continua fora do escopo.
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
| F8B: demo do Streamlit com estado por sessão | `OLHEIRO_DEMO_MODE=true`; `MemoryStore` (cópias profundas e atualização transacional) guarda cache e dashboard de cada visitante. Só base/glossário/exemplos e orçamento de instância são compartilhados. `connect_agent(..., None)` anexa workspace vazio em memória; o arquivo pessoal não é aberto. Modo pessoal preserva a persistência anterior. |
| F8B: exemplos em TOML, curadoria SQL sem LLM | `demo/examples.toml`, seis exemplos validados e executados ao iniciar; `AnalysisAnswer`/`ChartSpec` reutilizados. Cada sessão recebe cópia do cache; cada resposta reexecuta o SQL. Textos evitam números fixos, ranking inclui empates e aproveitamento usa pontos/(3*jogos). |
| F8B: chamadas ao Gemini exigem opt-in | `OLHEIRO_DEMO_MODEL_ENABLED=false` por padrão, mesmo com chave pessoal presente. Quando habilitado: cinco tentativas por sessão por padrão, dez por processo (`OLHEIRO_DEMO_TOTAL_QUESTION_LIMIT`, lock) e `UsageLimits(request_limit=6, tool_calls_limit=12)` por análise. Cache é livre. Orçamento de instância reinicia com o processo e não é controle financeiro do provedor. |
| F8B: somente leitura e privacidade | `AgentDeps.allow_saves=false` retira `save_result` via `prepare`; guarda na função também recusa. Operação sai da navegação e recusa invocação direta. `RunLog(include_content=False)` omite pergunta e texto de erro. Traces detalhados ficam obrigatoriamente off na demo, pois exceções de bibliotecas podem conter argumentos além do payload. |
| F9A: bases locais independentes | `olheiro-dataset import` ou upload pessoal cria cópias de CSV/Parquet e banco materializado; manifesto publicado depois da validação. Nomes duplicados/arquivos inválidos não substituem bases existentes. `OLHEIRO_DATASET` aplica o mesmo perfil a app, CLI, diagnóstico e MCP. |
| F9A: contexto de qualquer domínio | Glossário opcional/parcial; nomes e tipos vêm do catálogo. Instruções pedem exploração, unidade/granularidade explícitas e verificação de cardinalidade antes de JOINs. Valores de glossário têm limite, aviso de truncamento e timeout. Escape também em nomes do catálogo e caminhos. |
| F9A: estado e revisão | Cache por identidade/conteúdo de banco+glossário, com comparação da evidência e validação do gráfico; recusa antiga também invalida. Dashboard por identidade estável; painel legado do exemplo preservado. Troca de base fecha cursor e limpa histórico/aprovação, sem zerar a quota. Logs por base; traces UI no destino comum do processo OpenTelemetry. |
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

F9C (04/11/2026): contratos de `Agent.run_sync(message_history=..., usage=..., usage_limits=...)`,
`ModelRequest`, `UserPromptPart`, `ModelResponse` e `TextPart` conferidos no Pydantic AI
**2.59.0** instalado e na documentação oficial de histórico de mensagens. Streamlit **1.66.1**
mantido. Sem dependências novas. Referência e limites em `docs/conversa.md`.

## Estrutura
```
src/olheiro/config.py       configurações (Settings)
src/olheiro/db.py           carga de CSV/Parquet (olheiro-load) e conexão blindada do agente
src/olheiro/datasets.py     importação, descoberta, identidade e revisão de bases locais
src/olheiro/check_setup.py  diagnóstico do ambiente (comando olheiro-check)
src/olheiro/tools.py        execução de SQL (query_rows, com timeout) e ferramentas: run_sql,
                            profile_column, save_result
src/olheiro/sql_guard.py    validador de SQL (camada 1 da defesa)
src/olheiro/semantic.py     glossário -> contexto do agente (camada de contexto)
src/olheiro/agent.py        agente Pydantic AI: saída estruturada, validador, ask()/resume()
src/olheiro/charts.py       ChartSpec (bar/line/metric), check_chart, figura Plotly
src/olheiro/cli.py          comando olheiro-ask (--verbose, --no-cache)
src/olheiro/cache.py        cache de respostas + ask_with_cache
src/olheiro/conversation.py contexto limitado, pares completos e isolamento por sessão/revisão
src/olheiro/dashboard.py    itens fixados (SQL + ChartSpec) e render_item
src/olheiro/storage.py      JsonFile: modelo Pydantic em JSON com lock e escrita atômica
src/olheiro/app.py          entrada do Streamlit (navegação + barra lateral)
src/olheiro/ui/             páginas Perguntar, Dashboard, Dados, Operação + recursos e componentes
src/olheiro/ui/presentation.py identidade visual, SVG e composição decorativa da AnalisIA
.streamlit/config.toml      tema nativo (somente esse arquivo da pasta entra no Docker)
src/olheiro/errors.py       explica falhas do modelo (cota, 503, prazo) em português
src/olheiro/evaluation.py   evals: tarefa, avaliadores, resumo (comando olheiro-eval)
src/olheiro/eval_suites.py  fixtures por domínio, revisão e bancos temporários de avaliação
src/olheiro/pricing.py      preço por modelo e custo equivalente
src/olheiro/tracing.py      OpenTelemetry: setup, exportador JSONL, leitura de um trace
src/olheiro/telemetry.py    RunRecord, RunLog e tracked() (registro de execuções)
src/olheiro/mcp_server.py   servidor MCP stdio: SQL, perfil, perguntas, contexto e prompt
src/olheiro/launcher.py     entrada web olheiro-app, validação/carga inicial sem sobrescrever
src/olheiro/demo.py         exemplos curados e orçamento concorrente da demonstração
demo/examples.toml         seis exemplos sem LLM (SQL + ChartSpec + recusa)
examples/mcp_client.py     cliente stdio de demonstração (SQL sem cota; --question para agente)
docs/mcp.md                contrato MCP, limites e conexão ao Claude Desktop/Code
Dockerfile / compose.yaml  imagem e execução local com volume e rede interna
deploy/                    Dockerfile/config Squid e smoke do runtime sem Gemini
.github/workflows/ci.yml   qualidade, build do pacote e verificação dos contêineres
docs/deployment.md          operação, validação e limites da entrega F8A
docs/demo.md                modo demo, isolamento de sessões, limites e privacidade
docs/datasets.md            upload/importação, semântica opcional e estado por base (F9A)
docs/interface.md           identidade AnalisIA e fluxos interativos (F9A.1)
docs/auditoria-2026-10-27.md  achados, etapas concluídas e roteiro priorizado
examples/datasets/retail/   pedidos/clientes sintéticos e glossário parcial de demonstração
data/raw/SOURCE.md          fonte Kaggle, condições informadas e hashes dos CSVs
evals/cases.yaml            suíte Brasileirão (39 casos, 29 gabaritos SQL)
evals/vendas.yaml           suíte de vendas (10 casos, 7 gabaritos SQL)
evals/estoque.yaml          suíte de estoque (10 casos, 8 gabaritos SQL)
evals/fixtures/inventory/   produtos, saldos, fornecedores, opções e regras sintéticos
docs/avaliacoes.md         execução offline/real, critérios e limites do benchmark
docs/conversa.md           contexto no app/CLI, cache por contexto e aprovações da F9C
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
  - **F8A concluída e validada:** Dockerfile em duas etapas, Compose local com saída restrita via Squid,
    workflow CI de qualidade e contêiner, README refeito, origem dos dados e guia de operação.
    `olheiro-app` inicializa a base com segurança; limite zero da sessão corrigido.
    **147 testes offline**, lint/format/mypy; build wheel/sdist e conteúdo dos pacotes verificados
    (sem `.env`/bancos). Ambiente temporário com `uv sync --locked --no-dev`: app iniciou pelo
    AppTest **sem pytest e sem chave**. Compose validado contra schema oficial, CI validada
    com actionlint **1.7.12** e sintaxe shell conferida. Nenhuma chamada
    extra ao Gemini nesta etapa de infraestrutura.
    Push autorizado em 2026-10-26: commits `3eed474` e `809f2bd` enviados, seguidos pelos reparos
    necessários da CI `5b1406b` (teste sem chave) e `dc48922` (entrada NGINX sem retirar o app
    da rede interna). **CI verde no runner Ubuntu**, execução `40365502597`:
    https://github.com/joaovitor2410/AnalisIA/actions/runs/40365502597 . Qualidade, build do
    pacote, build/inicialização Docker, smoke de base/blindagem/usuário/filesystem/AppTest/rede
    e acesso HTTP pelo host passaram. Docker segue ausente neste Mac; a validação real veio
    do runner Linux. NGINX unprivileged **1.30.6-alpine** no serviço `web`.
  - **F8B: demo preparada antes de publicar.** Seis exemplos curados, cache/dashboard/histórico
    por sessão, workspace em memória, gravações desabilitadas no agente, Operação privada,
    logs sem conteúdo e traces detalhados desligados. Modelo só por opt-in, com três limites.
    **167 testes offline**, inclusive cópia limpa sem `.env`; lint/format/mypy e build aprovados.
    Verificação real única via AppTest da demo: recusa do artilheiro de 2024, **1 requisição
    em 4,67 s**, `gemini-3.8-flash`; pergunta omitida do registro e nenhum arquivo de trace.
    Prévia local na porta 8503, funcionando ao lado do app pessoal na 8501 sem disputa de workspace.
    CI estendida para matriz pessoal/demo e smoke de isolamento de visitantes; essa ampliação
    **passou após o push autorizado de `845767d` em 2026-10-27**, execução `40502502772`:
    https://github.com/joaovitor2410/AnalisIA/actions/runs/40502502772 .
    Rodar: `OLHEIRO_DEMO_MODE=true uv run olheiro-app --server.port=8503`.
  - **F8C pendente:** hospedagem, acesso, condições de redistribuição dos dados e publicação.
    Migração DuckDB 2.x continua separada, com cópias e estratégia de retorno.
- [x] **Fase 9A: núcleo flexível para CSV/Parquet (2026-10-27).** Escolha explícita do autor.
  Auditoria do código, interfaces, dados, testes, evals, observabilidade, infraestrutura e roteiro.
  Importação por `olheiro-dataset import` e upload na página Dados (modo pessoal), seleção na
  barra lateral, catálogo automático e glossário opcional/parcial. Bases próprias, misturando
  CSV e Parquet, sem acoplamento ao futebol no motor. Exemplo sintético de varejo.
  Cópias de entrada + banco/estado por base, ignorados pelo Git; falhas não publicam nem
  substituem a base existente. Proteção contra cache de outra revisão/domínio, escape de
  nomes/caminhos, contexto limitado e tabelas vazias aceitas. Recusas novas não são cacheadas,
  pois novas tabelas de workspace podem torná-las respondíveis; a recusa curada da demo permanece.
  Demo preserva base fixa e isolamento.
  `DATASETS_DIR=/state/datasets` no Docker; proxy aceita 64 MB para o limite pessoal de 50 MB;
  smoke ampliado com CSV/Parquet e teste de escrita no volume.
  **194 testes offline**, também numa cópia limpa sem `.env`; Ruff lint/format, mypy e build
  wheel/sdist. Comandos instalados de
  importação/listagem e diagnóstico verificados em diretório temporário; etapa de ingestão
  do smoke executada localmente. Wheel confere módulo/entrypoint sem dados/segredos.
  Sem chamadas adicionais ao Gemini nesta fase; testes com modelo falso não substituem
  benchmark real. Docker completo da versão nova depende de CI após push autorizado.
  Rodar: `uv sync --locked && uv run olheiro-app`; Dados → Importar outra base.
  Testar: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy`, `uv build`. Importação reproduzível em `docs/datasets.md`.
  **Próxima fase sugerida: F9B, qualidade e semântica dos dados** (prévia/tipos, duplicidades,
  chaves/relacionamentos e editor de regras). Não iniciar sem o ok do autor ao fim da F9A.

- [x] **Fase 9A.1: AnalisIA — identidade e experiência (27/10/2026).** Pedido explícito do autor.
  Nome público AnalisIA no app, agente e MCP; comando `uv run analisia` para abrir o navegador.
  Pacote/caminhos/comandos `olheiro-*` e URI MCP preservados para as integrações existentes.
  Tema nativo claro com navegação escura, violeta/verde, logo SVG e composição responsiva.
  Perguntas sugeridas viram rascunhos editáveis, sem requisição até envio explícito; Nova
  exploração preserva quota e dashboard. Busca/filtro no painel, prévia de dados ajustável,
  métricas do perfil, CSV da evidência e gráficos com identidade consistente. Aprovações e
  modo demo preservados; exemplos também ficam desabilitados enquanto há pedido de gravação.
  Textos dinâmicos escapados no HTML decorativo, sem JS; controles continuam nativos.
  **198 testes offline**, também em cópia limpa sem `.env`; lint/format/mypy e build;
  revisão no Chrome em desktop e 390 px,
  sem chamadas ao Gemini. Tema incluído no Docker por arquivo explícito, sem secrets.toml.
  Documentação em `docs/interface.md`. CI Docker da versão nova após push autorizado.
  Rodar: `uv sync --locked && uv run analisia`; testar: `uv run pytest -q`,
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv build`.
  Próxima etapa funcional sugerida continua **F9B: qualidade e semântica dos dados**.

- [x] **Revisão corretiva antes da F9B (03/11/2026).** Varredura solicitada pelo autor;
  baseline de 198 testes. Corrigidos cache que confundia filtros/códigos, SELECT com mutação
  de sequência sem aprovação, falso positivo dos avaliadores por comparação de colunas
  isoladas, erros de perfil que interrompiam ferramenta/página, CLI que exigia chave mesmo
  com cache e rejeição indevida de schemas/CTEs por caixa. Chaves conservam sinais, caixa,
  acentos e espaços internos; entradas antigas são reindexadas pela pergunta original.
  **228 testes offline**, também em cópia temporária sem `.env` e sem chaves; Ruff
  lint/format, mypy (31 módulos), diagnóstico local e build offline wheel/sdist aprovados.
  Sem chamadas ao Gemini ou push; Docker não instalado, validação do contêiner pela CI
  após liberação do autor. Relatório e critérios da próxima fase em
  `docs/auditoria-2026-11-03.md`. **F9B permanece a próxima fase funcional, não implementada
  nesta revisão, que priorizou os erros encontrados.**
  Rodar: `uv run --locked analisia`. Testar: `uv run --locked pytest -q`,
  `uv run --locked ruff check .`, `uv run --locked ruff format --check .`,
  `uv run --locked mypy`, `uv build --offline`, `uv run --locked olheiro-check`.

- [x] **Fase 9B: qualidade e semântica (03/11/2026).** Autor autorizou o push da auditoria
  e o avanço. `762c0cb` enviado a `origin/main` (inclui F9A e F9A.1); CI de qualidade e
  contêiner pessoal/demo aprovada em
  https://github.com/joaovitor2410/AnalisIA/actions/runs/41632724779.
  Prévia e importação compartilham a carga estrita, com opções por arquivo: cabeçalho,
  separador, decimal, codificação (UTF-8/BOM, Latin-1, Windows-1252, UTF-16) e tipos explícitos.
  Opções em `import.json` são usadas na recarga e no launcher; IDs preservados como VARCHAR.
  UI impede importar uma prévia desatualizada. CLI ganha `preview` e `--options`.
  Diagnósticos SQL de nulos/distintos/linhas repetidas e candidatas a chave; usuário propõe
  pares de colunas e o verificador mede unicidade, cobertura, nulos e cardinalidade. Escopo
  de chaves/relacionamentos é de uma coluna, sem supor o significado da relação.
  Editor de tabelas/colunas/unidades/regras só em bases pessoais importadas; exemplo e demo
  preservados. Publicação por glossário versionado + manifesto atômico, lock de arquivo
  no macOS/Linux e revisão esperada para evitar sobrescrever edição concorrente. Versões
  antigas são preservadas. UI/MCP leem a semântica nova e invalidam cache sem reabrir o
  banco; UI limpa histórico/pendência/rascunho anterior sem zerar quota nem dashboard.
  Contexto inicial de dados limitado a 12.000 caracteres/80 colunas; `discover_tables`,
  `describe_table` e `read_semantics` paginados no agente e no MCP mantêm descoberta e
  acesso integral às regras/descrições. O teto não inclui instruções/contratos de ferramentas.
  **251 testes offline**, também em cópia sem `.env`/chaves; Ruff lint/format, mypy (38
  módulos), diagnóstico e build wheel/sdist aprovados. Smoke de ingestão/qualidade/semântica
  rodou localmente nos dois modos. Conferência visual no Chrome desktop com base sintética
  em `/tmp`; instância temporária encerrada. Nenhuma chamada ao Gemini ou dependência nova.
  Nova imagem F9B precisa de CI após push liberado pelo autor; o push desta solicitação
  publicou a auditoria, antes da implementação da fase. Documentação em `docs/qualidade.md`,
  incluindo opções reproduzíveis e três perguntas de revisão. Rodar:
  `uv run --locked analisia`; testar: `uv run --locked pytest -q`,
  `uv run --locked ruff check .`, `uv run --locked ruff format --check .`,
  `uv run --locked mypy`, `uv build --offline`, `uv run --locked olheiro-check`.
  Próximas etapas: F5 complementar (benchmark em outros domínios, rodada paga separada)
  e F9C (contexto de conversa), respeitando a revisão de fim de fase pelo autor.

- [x] **Varredura e F5 complementar offline (04/11/2026).** Baseline de 251 testes,
  diagnóstico local, Ruff/formatação e mypy sem erros. CI da F9B confirmada no GitHub:
  https://github.com/joaovitor2410/AnalisIA/actions/runs/41637039752 (SHA `0e20330`, 03/11).
  README anterior e as notas de fim da F9B estavam desatualizados sobre essa validação.
  Avaliador agora oferece `--suite brasileirao|vendas|estoque` e `--validate-only` sem ler
  configurações pessoais/construir modelo. Materializa fixtures versionadas com as opções
  do produto em banco temporário blindado e workspace descartável. Não avalia os casos de
  futebol contra `OLHEIRO_DATASET`; logs/traces reais continuam configuráveis.
  Vinte casos novos: faturamento, cancelamentos, JOINs, IDs com zeros, nulos, órfãos,
  fornecedores duplicados, reposição, recusa e proteção. Gabaritos checados antes de pedir
  custo; SQL proibido, nomes inválidos e evidência >50 linhas recusados. Caso antigo de zero
  títulos do Nordeste ganha SQL. Ancoragem deixa de dispensar números de 2003–2024 e aceita
  números de datas/códigos presentes na evidência; continua heurística. Cursores fechados
  explicitamente também em falha. Resumos em `evals/results/<suite>/<modelo>.json`, com
  suíte e hash de dados/regras/opções/perguntas. Comparativo comum identifica cada suíte.
  **270 testes offline**, repetidos em cópia sem `.env`/chaves; Ruff lint/format, mypy (39
  módulos), diagnóstico, validação das três suítes e build offline wheel/sdist aprovados.
  Sem chamada ao Gemini, dependência nova ou push. Docker ausente no Mac; nova CI após
  push autorizado. Documentação em `docs/avaliacoes.md` e `docs/auditoria-2026-11-04.md`.
  Preparação offline concluída; benchmark real não foi executado e não há acurácia medida.
  Rodar: `uv run --locked analisia`. Testar: `uv run --locked pytest -q`,
  `uv run --locked ruff check .`, `uv run --locked ruff format --check .`,
  `uv run --locked mypy`, `uv build --offline`, `uv run --locked olheiro-check`,
  `uv run --locked olheiro-eval --suite vendas --validate-only` (também estoque/brasileirao).
  Próxima fase funcional: **F9C**, após revisão do autor. Rodada paga continua separada.

- [x] **Fase 9C: conversa com contexto (04/11/2026).** Autor autorizou push da F5 complementar
  e avanço. `94f5cca` enviado, com **270 testes** conferidos; CI remota aprovada:
  https://github.com/joaovitor2410/AnalisIA/actions/runs/41843227764 (qualidade e ambos os
  modos de contêiner). Esta autorização publica a fase anterior; a F9C fica em novo commit
  local, aguardando os testes/liberação de fim de fase antes de outro push.
  `Conversation` guarda até seis pares pergunta/AnalysisAnswer e 16.000 caracteres, com
  descarte dos pares mais antigos e aviso na interface. Reconstitui pares textuais para
  `message_history`; inclui SQL/insights/gráfico, não tabelas completas nem ferramentas,
  retentativas, assinaturas antigas ou aprovações. Funciona após respostas do cache.
  A nova análise continua obrigada a produzir e executar seu próprio SQL; na falta de
  referente, instrução pede esclarecimento. O histórico visual pode exceder a janela enviada.
  Memória em sessão, nunca em recursos globais; troca de conexão/base, semântica, namespace
  ou permissão limpa o contexto. Nova exploração preserva quota/dashboard. Perguntas prontas
  selecionadas ou digitadas reiniciam contexto e continuam gratuitas, mesmo após a quota.
  Cache inclui hash do contexto efetivo, sem timestamps; entradas de continuação não aparecem
  em perguntas prontas. Entradas antigas sem contexto continuam independentes; toda evidência
  continua revalidada/reexecutada. Contexto não é restaurado entre sessões; cache/logs/traces
  mantêm as políticas de persistência/conteúdo existentes. Demo preserva privacidade e limites.
  CLI `--chat` tem `/nova`, `/sair`, EOF, modelo construído só na falta do cache e leitura das
  regras a cada turno/decisão. `--no-cache` preserva o contexto. CLI simples e MCP seguem
  independentes (o host MCP administra sua conversa). Sem histórico global no servidor MCP.
  Aprovações vinculadas à conexão e ao glossário: outra sessão/regra/modo de leitura causa
  `ApprovalContextError`; consumo único protegido por lock. Falha após consumir exige novo
  pedido. Retomada preserva mensagens reais do provedor e consumo/limites acumulados da análise.
  Pausas/falhas não entram na janela; conclusão após decisão adiciona só a análise final.
  **290 testes offline**, também em cópia sem `.env` e sem chaves; Ruff lint/format e mypy
  (40 módulos), build wheel/sdist e diagnóstico com workspace temporário. O diagnóstico
  padrão identificou o workspace pessoal ocupado (PID 17232); a instância foi preservada.
  Verificação real única: resposta inicial de 2019 em cache → "E em 2020?";
  **Gemini 3.8 Flash, 2 requisições**, Flamengo/71 pontos, SQL próprio correto. Banco/cache
  temporários, somente leitura, teto de quatro requisições e sem retentativas do SDK. Não
  executa o benchmark real F5. Documentação em `docs/conversa.md`, README, interface/demo/MCP.
  Rodar: `uv run --locked analisia` ou `uv run --locked olheiro-ask --chat`.
  Testar: `uv run --locked pytest -q`, `uv run --locked ruff check .`,
  `uv run --locked ruff format --check .`, `uv run --locked mypy`, `uv build --offline`,
  `uv run --locked olheiro-check`. Docker ausente localmente; nova imagem depende de CI
  após push da F9C. Próximos itens: rodada real F5 após faturamento/liberação e preparação
  operacional/publicação F8C, com hospedagem e condições dos dados ainda por decidir.

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
- **Para a publicação (F8C):** decidir hospedagem/acesso e condições dos dados; validar a imagem
  F9C após novo push (F5 complementar já verde em `41843227764`); limites no provedor se
  habilitar perguntas. F5 real permanece pendente de faturamento/liberação, embora a
  preparação offline multidomínio esteja concluída.
  A F8B já prepara exemplos versionados e estado por sessão. O orçamento é por processo:
  reinícios/replicação precisam ser considerados na hospedagem.
- **Limitações conhecidas:** F9C mantém contexto limitado no app/CLI `--chat`; não persiste
  conversas nem recupera referências fora da janela automaticamente. CLI simples e MCP seguem
  independentes. F9A invalida caches de outra revisão; cache legado é regenerado. JSONs ainda
  usam locks por objeto/thread, sem coordenação entre processos/réplicas. UI mantém conexões
  das bases selecionadas no cache; medir ciclo de vida/memória com muitas bases. F9B adicionou
  prévia e tipos/codificações; significado de negócio, chaves compostas e acurácia real
  continuam exigindo validação. Retenção das versões do glossário pertence à operação.
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
