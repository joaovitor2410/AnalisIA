# Qualidade e semântica dos dados — F9B

A F9B acrescenta conferência antes da importação, diagnósticos SQL de qualidade e edição
das descrições e regras das bases pessoais. Não há dependências novas nem chamada automática
ao modelo nesses fluxos. A demo conserva a base fixa, sem importação nem editor.

## Conferir antes de importar

```bash
uv run --locked analisia
```

Abra **Dados → Importar outra base**. Informe nome/identificador e envie CSVs ou Parquets.
Em cada CSV, ajuste codificação, separador, cabeçalho e decimal quando necessário. São
suportados UTF-8, UTF-8 com BOM, Latin-1, Windows-1252 e UTF-16. A transcodificação usa uma
cópia temporária em UTF-8; os arquivos originais são preservados, sem instalar extensões.

1. Clique **Conferir prévia**. O arquivo inteiro é materializado para validar a leitura; a
   exibição mostra até vinte linhas. Confira quantidade de linhas, nomes e tipos.
2. Na tabela de tipos, escolha `VARCHAR` para códigos, CEPs e identificadores com zeros
   iniciais. Também é possível importar todas as colunas CSV como texto. Isso preserva
   representações, mas medidas precisarão de conversão antes de cálculos numéricos.
3. Tipos disponíveis: `VARCHAR`, `BIGINT`, `DOUBLE`, `DECIMAL(18,2)`, `BOOLEAN`, `DATE` e
   `TIMESTAMP`. Parquet mantém seus tipos de origem, com conversões explícitas opcionais.
4. Se alterar arquivos, leitura ou tipos, confira novamente. **Importar base** fica
   desabilitado enquanto a prévia não corresponder às opções e aos arquivos atuais.
5. Importe. As opções ficam em `import.json`, junto da base, e são usadas por
   `olheiro-load` e pela reconstrução de um banco ausente. Uma conversão inválida causa
   erro; linhas não são descartadas nem valores inválidos convertidos silenciosamente em nulos.

Prévia e importação chamam a mesma carga transacional. Inferência automática considera todas
as linhas. A inferência de um número não consegue decidir se ele representa uma medida ou
um código: a escolha de preservar identificadores continua explícita. A prévia não cria
uma base no catálogo e não sobrescreve bases existentes. Aplicam-se o limite de upload
(50 MB por padrão), memória DuckDB de 1 GB e interrupção de consultas demoradas.

## Terminal e opções reproduzíveis

```bash
uv run --locked olheiro-dataset preview examples/datasets/retail \
  --options examples/datasets/retail/import-options.json
uv run --locked olheiro-dataset import examples/datasets/retail \
  --name loja_f9b --title "Loja com tipos conferidos" \
  --options examples/datasets/retail/import-options.json \
  --glossary examples/datasets/retail/glossary.toml
OLHEIRO_DATASET=data/datasets/loja_f9b/dataset.toml uv run --locked analisia
```

O identificador precisa estar livre. O JSON usa nomes completos dos arquivos, não os nomes
das tabelas. Exemplo para um CSV com vírgula decimal e código com zeros:

```json
{
  "files": {
    "pedidos.csv": {
      "delimiter": ";",
      "header": true,
      "encoding": "cp1252",
      "decimal_separator": ",",
      "types": {"cliente_id": "VARCHAR", "valor": "DECIMAL(18,2)"}
    }
  }
}
```

Sem `--options`, mantém-se a detecção automática anterior. Opções para arquivos ou colunas
inexistentes são erros. As configurações de CSV não se aplicam a Parquet; tipos explícitos
se aplicam aos dois formatos. As opções são validadas antes da carga, sem aceitar SQL no
lugar de um tipo. Para reconstruir, feche os processos que usam a base e execute:

```bash
OLHEIRO_DATASET=data/datasets/loja_f9b/dataset.toml uv run --locked olheiro-load
```

## Diagnosticar qualidade e relacionamentos

Na aba de uma tabela, abra **Qualidade e possíveis relacionamentos → Analisar qualidade**.
O relatório mostra nulos e distintos por coluna, duplicações de linhas completas e
candidatas a chave. Uma candidata tem valores únicos, nenhum nulo e pertence a uma tabela
não vazia. Duplicações excedentes contam as ocorrências além da primeira; os dados não
são removidos. O SQL de cada diagnóstico fica disponível para inspeção.

Para testar um relacionamento, escolha coluna de origem e tabela/coluna de destino e
clique **Verificar relacionamento**. A verificação exige tipos iguais, mede nulos,
unicidade e cobertura e não multiplica medidas em um JOIN para calcular as contagens.
Um destino não vazio, único e sem nulos, que cubra todos os valores não nulos da origem,
é apresentado como compatível nos dados atuais. Nulos na origem ficam explícitos nas
contagens. Valores repetidos ou nulos no destino, ausência de cobertura e tabelas vazias
impedem a indicação de compatibilidade. Cardinalidade é informada como um para um ou
muitos para um quando os critérios passam.

Isso verifica uma hipótese de relacionamento escolhida pelo usuário, sem deduzi-la apenas
pelo nome das colunas. Chaves compostas e o significado de negócio precisam de análise
adicional. Unicidade na amostra atual não cria uma restrição de chave no banco.

## Editar a semântica

Em uma **base pessoal importada**, abra **Editar descrições e regras**. Escolha tabela e
coluna, descreva seu significado, informe unidade, opcionalmente inclua amostra de valores
e escreva regras, uma por linha. As descrições das demais colunas são preservadas.
O exemplo versionado do Brasileirão conserva sua semântica original; importe uma cópia
como base pessoal para editá-la. A demo não oferece esse fluxo.

O salvamento valida referências antes de escrever. Uma nova versão de glossário é escrita
por completo, e só depois o manifesto passa a apontá-la por troca atômica. Uma falha antes
da publicação preserva a versão ativa anterior. Edições concorrentes usam lock de arquivo
e revisão esperada: uma sessão desatualizada precisa recarregar. Esse lock é do editor de
semântica; a [F8C.1](operacao.md) acrescenta coordenação dos demais JSONs no mesmo disco local.

App e MCP consultam a versão atual das regras sem reiniciar ou reabrir o banco. Alterações
mudam o namespace do cache. Na próxima interação da interface, histórico, rascunho e
aprovação pendente da semântica anterior são limpos, preservando a quota e o dashboard.
CLI inicia com a versão atual. Glossários versionados anteriores são mantidos para leitores
que já abriram a base; limpeza e retenção dessas versões ficam para a etapa de operação.

## Catálogos grandes

O **contexto inicial de dados** tem teto de 12.000 caracteres e 80 colunas, com indicação
de resumo/truncamento. Esse teto não inclui as demais instruções e contratos das ferramentas.
O agente e o MCP têm três consultas de metadados, sem Gemini na execução da ferramenta:

| Ferramenta | Uso |
|---|---|
| `discover_tables(search, offset)` | Busca por tabela, coluna ou descrição; vinte tabelas por página |
| `describe_table(table, offset)` | Nomes, tipos e descrições resumidas; vinte colunas por página |
| `read_semantics(table, column, offset)` | Descrição/unidade integral de tabela ou coluna; sem tabela, duas regras por página |

O agente é instruído a pesquisar antes de recusar por ausência de tabela no contexto inicial.
Uma simulação com `FunctionModel` cobre descoberta, leitura de schema e análise de uma
tabela omitida. Isso verifica integração; a capacidade do Gemini de escolher essas
ferramentas ainda precisa de benchmark real. Paginação limita a saída ao modelo, mas a
busca ainda consulta o catálogo local completo.

## Validação e próximos passos

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked olheiro-check
```

Os testes cobrem vendas/estoque, CSV/Parquet, conversões, codificações, zeros iniciais,
recarga, falhas sem publicação, nulos/duplicidades, chaves, cobertura de relacionamentos,
edição concorrente e falha de publicação da semântica, atualização de cache/contexto em
AppTest/MCP e descoberta em catálogo grande. O smoke de contêiner também exercita prévia,
tipos, qualidade, relacionamentos e semântica; a nova imagem depende de CI após push.

A rodada real F5 continua separada, pois exige faturamento e custo aprovados. Permanecem
as próximas etapas: benchmark em outros domínios e F9C (contexto de conversa). A F8C depende
das decisões de hospedagem e dados; esta fase não publica a aplicação.

Para revisar os conceitos da fase:

1. Por que um identificador com zeros iniciais deve ser importado como texto?
2. Como uma duplicação na chave de destino pode inflar um total calculado por JOIN?
3. Por que mudar uma regra de negócio deve invalidar o cache mesmo com os mesmos dados?

Referências consultadas: [CSV no DuckDB](https://duckdb.org/docs/stable/data/csv/overview),
[detecção de CSV](https://duckdb.org/docs/stable/data/csv/auto_detection) e
[editor do Streamlit](https://docs.streamlit.io/develop/api-reference/data/st.data_editor).
As opções usadas também foram verificadas com o DuckDB 1.5 instalado, sem migrar bancos.
