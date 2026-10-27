# Analisar outras bases — Fase 9A

O motor do Olheiro analisa dados tabulares de diferentes domínios. Nesta etapa, as fontes
suportadas são **arquivos locais CSV e Parquet**: um arquivo vira uma tabela no schema `raw`.
O Brasileirão permanece como exemplo. Bancos externos, Excel e APIs ainda não são conectores.

## Pelo navegador

```bash
uv sync --locked
uv run olheiro-app
```

Abra http://localhost:8501, entre em **Dados → Importar outra base (CSV ou Parquet)** e envie
um ou mais arquivos. Informe um nome e um identificador único, como `vendas_loja`. Ao concluir,
o app seleciona a base importada. A barra lateral permite voltar ao exemplo ou trocar de base.
Esse fluxo fica disponível no modo pessoal. A demo mantém sua base fixa e não oferece upload.

O limite padrão é **50 MB no total por importação**, configurável por `OLHEIRO_IMPORT_MAX_MB`.
O proxy Docker aceita corpos HTTP de até 64 MB; se aumentar o limite do app, ajuste também
`deploy/nginx.conf`. Parquet comprimido pode exigir mais memória do que o tamanho do arquivo;
o importador limita a memória DuckDB a 1 GB e reporta falhas sem publicar uma base parcial.

Trocar de base limpa histórico e aprovações pendentes da sessão, fecha o cursor anterior e
abre um cursor sobre a base escolhida. O contador de perguntas da sessão não é reiniciado.

## Pelo terminal

Exemplo reproduzível com dados sintéticos criados neste projeto:

```bash
uv run olheiro-dataset import examples/datasets/retail \
  --name loja --title "Loja (dados sintéticos)" \
  --glossary examples/datasets/retail/glossary.toml
uv run olheiro-dataset list
OLHEIRO_DATASET=data/datasets/loja/dataset.toml uv run olheiro-app
```

Pergunta sugerida: “Qual o faturamento realizado por região?”. Há quatro pedidos e três
clientes; o glossário define o status que participa do cálculo e a unidade monetária.

Para seus próprios dados, substitua a origem por uma pasta ou um arquivo:

```bash
uv run olheiro-dataset import /caminho/dos/arquivos --name minha_base --title "Minha base"
OLHEIRO_DATASET=data/datasets/minha_base/dataset.toml uv run olheiro-check
OLHEIRO_DATASET=data/datasets/minha_base/dataset.toml \
  uv run olheiro-ask "Quais tabelas permitem calcular o total por categoria?"
OLHEIRO_DATASET=data/datasets/minha_base/dataset.toml uv run olheiro-mcp
```

`OLHEIRO_DATASET` também pode ser definido no `.env`. A configuração é compartilhada pela
interface, CLI, diagnóstico e MCP. A integração MCP preserva `olheiro://context`, `run_sql`,
`profile_column` e `ask_question`; o cliente deve consultar o contexto da base escolhida.

O comando de importação não sobrescreve identificadores existentes. Use outro identificador
para uma nova versão. Para reconstruir explicitamente uma base já importada, feche os
processos que a usam, altere as cópias em `data/datasets/<id>/raw` e execute:

```bash
OLHEIRO_DATASET=data/datasets/minha_base/dataset.toml uv run olheiro-load
```

A carga substitui `raw` numa transação. Um arquivo inválido, ausência de arquivos ou colisão
de nomes preserva as tabelas anteriores. O workspace não é recriado.

## Tipos, nomes e semântica

- CSV: detecção de separador, cabeçalho e tipos; a inferência considera todo o arquivo
  (`sample_size=-1`). UTF-8 é o caminho testado. Formatos monetários, cabeçalhos ambíguos,
  identificadores com zeros e outras codificações podem exigir preparação prévia.
- Parquet: usa os tipos registrados no arquivo. Formatos misturados podem participar da mesma
  base e ser cruzados com SQL, depois de verificar chaves e cardinalidade.
- Nome da tabela: nome do arquivo normalizado; `Vendas 2026.CSV` vira `raw.vendas_2026`.
  Colisões entre nomes normalizados são recusadas com os dois arquivos envolvidos.
- Colunas preservam os nomes disponibilizados pelo DuckDB. Espaços, acentos e aspas funcionam
  no explorador e nos perfis; o SQL precisa citar esses identificadores corretamente.
- Tabelas vazias são válidas. Uma consulta deve informar a ausência de linhas em vez de
  impedir a inicialização da base inteira.

O glossário é **opcional**. Sem ele, o agente recebe nomes e tipos reais, e a orientação de
explorar os dados sem inventar significados, unidades ou relacionamentos. Descrições parciais
são aceitas. Referências a colunas ou tabelas inexistentes são erros de validação.

Para incluir regras, passe `--glossary /caminho/glossary.toml` na importação pelo terminal.
O arquivo é copiado para a base. O upload na interface importa os dados sem glossário;
edição assistida da semântica fica para a próxima etapa. Exemplo:

```toml
rules = ["Cada linha de pedidos representa um pedido; valor está em reais."]
[tables.pedidos]
description = "Pedidos da loja."
[tables.pedidos.columns]
valor = "Valor total do pedido, em BRL."
```

## Persistência e limites

Cada base fica em `data/datasets/<id>/`, ignorada pelo Git. `DATASETS_DIR` muda esse diretório.
No Docker, o padrão é `/state/datasets`, dentro do volume persistente.

| Arquivo/pasta | Conteúdo |
|---|---|
| `dataset.toml` | Versão do manifesto, nome visível e presença de glossário |
| `raw/` e `source.duckdb` | Cópias das entradas e tabelas materializadas |
| `glossary.toml` | Semântica opcional |
| `workspace.duckdb` | Resultados salvos com aprovação humana |
| `answer_cache.json` e `dashboard.json` | Estado da base |
| `runs.jsonl` e `exports/` | Registro de execuções e gráficos da base |

O manifesto só aparece após a validação; erros normais removem a importação incompleta.
Uma interrupção forçada pelo sistema pode deixar uma pasta sem manifesto: ela não é listada
e deve ser inspecionada antes de tentar reutilizar o identificador.

O cache confere a identidade da base, o conteúdo do banco e do glossário, e a evidência
reexecutada. Mudanças invalidam respostas antigas, inclusive recusas. Caches anteriores à
Fase 9A ficam fora da leitura até serem regenerados; o arquivo não é apagado pela verificação.
O dashboard mantém SQL atualizável. O painel legado da base original é preservado.
Novas recusas do agente não entram no cache: uma tabela salva depois pode tornar a pergunta
respondível. A recusa curada da demo continua sendo um exemplo explícito da sua base fixa.

Na interface pessoal, sessões que escolhem a mesma base compartilham seu cache e painel.
Isso não implementa contas ou isolamento entre usuários de uma aplicação pública. A demo
continua com estado por visitante. Registros `runs.jsonl` são separados por base; traces da
interface usam o destino comum do processo OpenTelemetry. CLI e MCP em processos próprios
usam o destino da base configurada. `OLHEIRO_TRACE_CONTENT=false` omite payloads dos traces;
o modo pessoal ainda mantém perguntas nos registros locais. As ferramentas podem enviar
resultados ao provedor de IA configurado.

O DuckDB permite um escritor por workspace. Para app e MCP simultâneos sobre uma base
importada, configure um workspace diferente para o segundo processo:

```bash
OLHEIRO_DATASET=data/datasets/loja/dataset.toml \
  OLHEIRO_WORKSPACE_OVERRIDE=data/datasets/loja/mcp-workspace.duckdb uv run olheiro-mcp
```

Os JSONs ainda não têm coordenação entre processos. Prefira um processo ativo escrevendo o
cache por base; chamadas MCP podem usar `use_cache=false` ao lado do app. Persistência com
concorrência entre processos e réplicas pertence à etapa de operação.

## Verificar

```bash
uv run pytest tests/test_datasets.py tests/test_app.py tests/test_launcher.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
```

Referências oficiais consultadas em 2026-10-27:

- [Importação CSV no DuckDB](https://duckdb.org/docs/stable/data/csv/overview)
- [Parquet no DuckDB](https://duckdb.org/docs/stable/data/parquet/overview)
- [Upload no Streamlit](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader)
