# Demo para visitantes — Fase 8B

O autor escolheu preparar a demonstração antes de publicar. Este modo permite revisar a
experiência de visitantes localmente. Hospedagem, domínio, acesso e publicação ficam para
uma próxima etapa; as condições da fonte de dados continuam em `data/raw/SOURCE.md`.

## Abrir

Na raiz do projeto:

```bash
uv sync --locked
OLHEIRO_DEMO_MODE=true uv run olheiro-app --server.port=8503
```

Abra http://localhost:8503. É possível manter o app pessoal em outra porta: a demo lê a base
bruta e usa um workspace vazio em memória, sem abrir `data/workspace.duckdb`.

Com Docker:

```bash
OLHEIRO_DEMO_MODE=true OLHEIRO_PORT=8503 docker compose up --build --detach --wait
docker compose exec -T app python deploy/smoke.py
```

O Compose lê esses valores também do `.env`. Ele mantém somente a porta local de entrada;
a configuração não publica o app na internet. A infraestrutura base foi validada na
[execução de CI 40365502597](https://github.com/joaovitor2410/AnalisIA/actions/runs/40365502597).
A matriz pessoal/demo passou na
[execução 40502502772](https://github.com/joaovitor2410/AnalisIA/actions/runs/40502502772).
A F9B e a ampliação das avaliações também passaram; a última CI antes da F9C é a
[execução 41843227764](https://github.com/joaovitor2410/AnalisIA/actions/runs/41843227764).
A [CI da F9C](https://github.com/joaovitor2410/AnalisIA/actions/runs/41865983452) passou após
o push de `071dd2d`. A F8C.1 também passou na
[CI 42211982307](https://github.com/joaovitor2410/AnalisIA/actions/runs/42211982307).
As correções de 06/11 aguardam novo push/CI. O autor manteve a demo pública e pediu uma
[comparação de hospedagens](hospedagem.md) antes de escolher; não houve publicação.

## O que fica disponível

As páginas são Perguntar, Dashboard e Dados. O visitante pode escolher os seis exemplos,
ver SQL, tabela e gráfico, fixar análises no próprio dashboard e explorar o dataset.
Recusas por dados ausentes também são demonstradas.

Os exemplos estão em `demo/examples.toml`. Foram curados com SQL, sem geração por modelo:

1. Total de temporadas.
2. Maiores campeões, incluindo todos os empatados.
3. Pontuação dos campeões por temporada, com os jogos disputados na evidência.
4. Aproveitamento dos campeões: pontos informados divididos por três vezes os jogos.
5. Distribuição dos títulos por região, com LEFT JOIN no cadastro.
6. Recusa de artilharia por ausência de estatísticas individuais.

Ao iniciar, o código valida e executa o SQL e confere o gráfico de cada exemplo. A cada
resposta do cache, o SQL é validado e reexecutado; as tabelas não são snapshots embutidos.
Os textos orientam a leitura e evitam números fixos que poderiam ficar antigos.
Na F9C, exemplos prontos iniciam novo contexto. Com modelo habilitado, o visitante pode
continuar uma análise; a janela de contexto pertence somente à sessão e mantém até seis
análises/16.000 caracteres. Novas continuações respeitam as quotas e exigem evidência própria.
Veja [conversa com contexto](conversa.md).

## Isolamento e duração

| Recurso | Escopo na demo |
|---|---|
| Base bruta e glossário | Compartilhados, dados públicos em leitura |
| Exemplos curados | Compartilhados como origem, copiados para cada sessão |
| Histórico, cache adicional e dashboard | Memória da sessão do visitante |
| Cursor DuckDB | Um por sessão/thread |
| Workspace | Vazio, em memória; o agente não recebe ferramenta de gravação |
| Orçamento diário de novas perguntas | Arquivo persistente, compartilhado no mesmo disco |
| Registro de execuções | Métricas locais, com pergunta omitida e sem texto de erro |

Recuperar ou remover itens numa sessão não altera o dashboard de outro visitante. O estado
pode ser perdido ao abrir uma nova sessão ou reiniciar o app. A demo não oferece conta,
sincronização de dispositivos ou persistência do dashboard entre visitas.

No modo pessoal, os arquivos e a aprovação humana continuam funcionando como antes.
Na F9A, o modo pessoal permite importar e selecionar CSV/Parquet; a demo continua sem upload
e sem seleção de bases particulares. `OLHEIRO_DATASET` não pode ser combinado com o modo demo.
`OLHEIRO_DEMO_MODE` controla a interface Streamlit; CLI e MCP locais têm seus fluxos próprios.

## Modelo e limites

O padrão é funcionar apenas com os exemplos, mesmo se o `.env` pessoal já contiver uma chave.
Para permitir novas perguntas, ative explicitamente `OLHEIRO_DEMO_MODEL_ENABLED=true` e
configure a chave. Isso pode consumir cota e gerar cobrança conforme o provedor.

```bash
OLHEIRO_DEMO_MODE=true OLHEIRO_DEMO_MODEL_ENABLED=true \
  uv run olheiro-app --server.port=8503
```

Há três limites:

- **Sessão:** `OLHEIRO_SESSION_QUESTION_LIMIT`, com padrão 5 na demo; 0 mantém só o cache.
- **Dia UTC:** `OLHEIRO_DEMO_TOTAL_QUESTION_LIMIT`, padrão 10 tentativas compartilhadas entre
  visitantes/processos no mesmo disco. `OLHEIRO_DEMO_BUDGET_PATH` guarda o contador persistente;
  no Docker, fica em `/state/demo-budget.json`. Falhas do modelo também consomem a tentativa.
- **Execução:** até 6 requisições contabilizadas pelo Pydantic AI e 12 chamadas de ferramenta
  por análise, para um loop do agente não continuar indefinidamente.

Respostas do cache não consomem esses orçamentos. Abrir uma aba ou reiniciar a instância
não renova a quota diária persistida. Ela renova no próximo dia UTC; processos com discos
diferentes têm contadores próprios. Todos os escritores devem usar o mesmo limite. Arquivo
indisponível/incompatível bloqueia novas chamadas, preservando exemplos. A quota é reservada
antes da chamada e não é devolvida em erro. Retentativas do SDK/provedor têm sua contagem;
configure também limites no provedor antes de disponibilizar novas perguntas numa hospedagem.
Veja [preparação operacional](operacao.md) para retenção de logs e limites da coordenação local.

## Gravação e privacidade

O agente recebe `allow_saves=false`. `save_result` é retirado das ferramentas expostas ao
modelo e a própria função também recusa gravação nesse contexto. Fixar no dashboard atualiza
apenas o estado em memória da sessão, mantendo a ideia de SQL reexecutável sem LLM.

Operação não aparece na navegação da demo. A função da página também recusa acesso caso seja
invocada diretamente. Os registros mantêm desfecho, duração, modelo e consumo, mas substituem
a pergunta por `(conteúdo omitido)` e removem o texto dos erros. Traces detalhados ficam
desligados na demo, mesmo se o `.env` pessoal os habilitar: exceções em bibliotecas podem
conter argumentos além dos payloads controlados pela opção `include_content`.

Arquivos pessoais antigos não são apagados. O isolamento da demo impede que sejam carregados
como cache, dashboard ou workspace do visitante; eles continuam privados à instalação.

## Validar

```bash
OLHEIRO_DEMO_MODE=true uv run olheiro-check
uv run pytest tests/test_demo.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Os testes exercitam duas sessões, cache privado, dashboards independentes, preservação de
arquivos pessoais, orçamento concorrente, limites por sessão/instância/execução, ausência de
gravações, recusa de Operação, omissão de conteúdo em sucesso/erro e validação dos exemplos.
O smoke Docker passa a verificar tanto o modo pessoal quanto a demo na matriz da CI.
O diagnóstico aceita configuração pelo ambiente e exemplos sem chave quando novas perguntas
estão desabilitadas; o arquivo `.env` é opcional.

Referências oficiais consultadas em 2026-10-26:

- [Estado por sessão no Streamlit](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
- [Recursos compartilhados e sessões](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource)
- [Preparação dinâmica das ferramentas no Pydantic AI](https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/)
