# Olheiro por MCP — Fase 7

O MCP conecta um cliente de IA às capacidades do Olheiro. O servidor é uma camada fina sobre
o núcleo existente: validação SQL, conexão DuckDB blindada, prazo de 10 segundos por consulta,
limite de 50 linhas e glossário continuam valendo.

O transporte desta fase é **stdio local**. O cliente inicia um processo, conversa pelo stdin e
stdout e encerra o processo ao desconectar. Não há porta HTTP nem hospedagem remota nesta fase.
Logs vão para stderr; stdout é exclusivo do protocolo. A versão instalada é `mcp==2.3.0`,
registrada em `uv.lock`; o projeto usa a API `MCPServer` da linha 2.x.

## Preparar e verificar

Na raiz do projeto, com os CSVs em `data/raw/`:

```bash
uv sync --locked
uv run olheiro-load  # se o banco ainda não tiver sido carregado
uv run olheiro-check
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Teste de ponta a ponta, sem chave e sem consumir cota do Gemini:

```bash
uv run python examples/mcp_client.py
```

O cliente inicia o servidor real, descobre as ferramentas e conta as temporadas via SQL.
Com o dataset de demonstração completo, são 22 temporadas (2003–2024).

Para delegar ao agente completo, preencha `GOOGLE_API_KEY` no `.env`:

```bash
uv run python examples/mcp_client.py --question "Quem foi o campeão de 2019?"
```

Uma pergunta pode gastar várias requisições. Repetições usam o cache e reexecutam a evidência
sem chamar o Gemini; `--no-cache` força o modelo e não grava a resposta no cache.
O limite `OLHEIRO_SESSION_QUESTION_LIMIT` pertence às sessões do app Streamlit e não limita o MCP.

Para apenas iniciar o servidor:

```bash
uv run olheiro-mcp
# Alternativa equivalente:
uv run python -m olheiro.mcp_server
```

Ele aguarda mensagens MCP, sem abrir um prompt de terminal. Use o cliente de demonstração
ou um host MCP para conversar; `Ctrl-C` encerra a execução manual.

Para analisar outra base CSV/Parquet importada na F9A:

```bash
OLHEIRO_DATASET=data/datasets/loja/dataset.toml uv run olheiro-mcp
```

O contrato é o mesmo: leia `olheiro://context` para conhecer a base ativa. O cliente em
`examples/mcp_client.py` sem argumentos continua sendo uma demonstração do Brasileirão.
Na configuração de um host MCP, a variável pode ser passada em `env` junto de `command` e
`args`. Glossário é opcional. Importação e concorrência de processos estão em
[datasets.md](datasets.md).

## Contrato exposto

| Capacidade | Entrada | Resultado | Gemini no servidor |
|---|---|---|---|
| `run_sql` | `query`: um SELECT DuckDB | `columns`, `rows`, `truncated` | Não |
| `profile_column` | `table`, `column` | Tipo, nulos, distintos e valores frequentes de raw | Não |
| `ask_question` | `question`, `use_cache=true` | `output`, `evidence`, modelo, cache e tokens | Só se faltar cache |
| Recurso `olheiro://context` | URI fixa | Catálogo atual + glossário + valores + regras | Não |
| Prompt `analyze_data` | `question` | Mensagem de análise com evidências, pronta para o cliente | Não |

`run_sql` e `profile_column` permitem que o próprio modelo do cliente conduza a análise;
`ask_question` delega a análise ao agente do Olheiro. A recusa por dados ausentes é uma saída
normal (`output.answerable=false`, `evidence=null`). SQL proibido, coluna inválida ou falha do
modelo retornam erro de ferramenta MCP (`isError=true`), para o cliente tratar ou corrigir.

As saídas de ferramentas incluem texto e `structuredContent`, com JSON Schema para o cliente.
Em `ask_question`, `output` segue o contrato `AnalysisAnswer`, incluindo SQL, insights e
`ChartSpec` quando apropriado. `evidence` contém os dados reexecutados. O cliente decide como
renderizar o gráfico a partir de `ChartSpec` e da tabela; o MCP não gera arquivos HTML.
Datas e decimais são strings JSON; nulos viram `null`. A matriz de linhas preserva a ordem e
nomes repetidos de colunas. `truncated=true` indica que o cliente deve agregar ou filtrar mais.

As perguntas são independentes, sem histórico entre chamadas. Cada chamada usa e fecha seu
cursor sobre a conexão blindada do processo, inclusive em falhas e consultas concorrentes.
As perguntas de `ask_question` aparecem na página **Operação**, com origem **MCP**, e usam as
mesmas configurações `OLHEIRO_TRACING` e `OLHEIRO_TRACE_CONTENT` da CLI e do app.
SQL direto, perfis, recursos e prompts não entram nas métricas de perguntas ao agente.

## Conectar ao Claude

Primeiro rode `uv sync --locked`. Para evitar dependência do PATH e do diretório inicial do
cliente, use o Python da `.venv` por caminho absoluto. `Settings` resolve o `.env`, o banco e
o glossário a partir da raiz do projeto, mesmo quando o cliente inicia o processo em outra pasta.

Exemplo de entrada para Claude Desktop (`claude_desktop_config.json`, dentro de `mcpServers`):

```json
{
  "mcpServers": {
    "olheiro": {
      "command": "/Users/jayv/Desktop/AnalisIA/.venv/bin/python",
      "args": ["-m", "olheiro.mcp_server"]
    }
  }
}
```

No macOS, o arquivo fica em `~/Library/Application Support/Claude/claude_desktop_config.json`.
Mescle a entrada com as existentes e reinicie completamente o Claude Desktop.
Em outra máquina, substitua o caminho absoluto do Python. A chave fica no `.env` do projeto.

Alternativa para Claude Code, executada na pasta deste projeto:

```bash
claude mcp add --transport stdio --scope project olheiro -- /Users/jayv/Desktop/AnalisIA/.venv/bin/python -m olheiro.mcp_server
```

Confira a conexão com `/mcp`. Esses exemplos são instruções para configuração pelo autor;
esta fase não altera automaticamente configurações de aplicativos.

## Gravações e escopo

O MCP desta fase permite somente consultas. Não expõe `save_result`, aprovação por booleano
nem retomada de execuções. Se o agente interno pedir uma gravação, a execução termina com erro
explicando como salvar pela CLI ou pelo app; nenhuma tabela é criada e não há entrada no cache.
Assim, o cliente externo não pode substituir a aprovação humana existente.

O workspace continua anexado pela conexão compartilhada do núcleo, mas as entradas MCP passam
pelo validador de leitura e não recebem caminho de execução de gravações. As proteções do
DuckDB seguem sendo defesa em profundidade, com isolamento de SO/contêiner previsto na Fase 8.

Os testes cobrem descoberta e schemas, glossário, prompt, tipos JSON, limite de linhas, SQL
perigoso, cache, falhas, recusa de gravações, concorrência, fechamento de conexões e subprocesso
stdio com negociação atual e legada. Usam `FunctionModel`, sem rede e sem cota.

Referências oficiais consultadas em 2026-10-26:

- [SDK Python MCP: ferramentas](https://py.sdk.modelcontextprotocol.io/servers/tools/)
- [Ciclo de vida](https://py.sdk.modelcontextprotocol.io/handlers/lifespan/)
- [Recursos](https://py.sdk.modelcontextprotocol.io/servers/resources/)
- [Erros de ferramenta](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/)
- [Testes com cliente em memória](https://py.sdk.modelcontextprotocol.io/get-started/testing/)
- [Conexão com hosts MCP](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
