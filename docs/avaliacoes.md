# Avaliações em múltiplos domínios — F5 complementar

Um benchmark reúne perguntas, dados fixos e critérios independentes para conferir as
respostas. Testes com modelo roteirizado verificam se a integração e os avaliadores detectam
erros conhecidos. Só a rodada com um modelo real mede sua capacidade de escolher ferramentas,
interpretar regras e produzir a análise. A rodada real foi autorizada em 09/11/2026;
os 118 casos foram executados. O [relatório da F5 e dos testes](f5-2026-11-09.md) registra
as notas, custos, correções e limitações. Houve divergências; executar a rodada não significa
que todas as respostas foram aprovadas.

## Suítes versionadas

| Suíte | Dados | Casos | Gabaritos SQL | Pontos de atenção |
|---|---|---:|---:|---|
| `brasileirao` | Brasileirão 2003–2024 | 39 | 29 | Empates, épocas, aproveitamento, recusas e proteção |
| `vendas` | Exemplo sintético de pedidos/clientes | 10 | 7 | Cancelamentos, faturamento, ticket médio, região e clientes sem receita |
| `estoque` | Produtos, saldos e fornecedores sintéticos | 10 | 8 | Zeros iniciais, nulos, órfãos, duplicações de fornecedor e reposição |

Os casos ficam em `evals/cases.yaml`, `evals/vendas.yaml` e `evals/estoque.yaml`.
As bases de vendas e estoque são criadas para o projeto, sem dados de pessoas reais.
O estoque inclui os SKUs distintos `001`, `01` e `1`, saldo desconhecido, SKU sem cadastro
e fornecedor duplicado. As regras distinguem estoque desconhecido de zero e explicam como
deduplicar o cadastro antes de agregar medidas. Não existem vendas nem demanda nessa base:
perguntas sobre dias de cobertura devem ser recusadas.

## Validação offline

Execute na raiz do checkout:

```bash
uv run --locked olheiro-eval --suite brasileirao --validate-only
uv run --locked olheiro-eval --suite vendas --validate-only
uv run --locked olheiro-eval --suite estoque --validate-only
uv run --locked pytest -q
```

`--validate-only` não lê as configurações pessoais, constrói modelo nem grava relatórios.
Cada suíte carrega seus arquivos CSV com as mesmas opções de importação do produto em um
banco temporário. Depois anexa raw em leitura, configura a blindagem, valida o glossário,
os nomes dos casos e os gabaritos com o validador SQL e executa cada consulta.
Todos os casos que esperam uma resposta precisam de gabarito SQL; recusas não o recebem.
Um gabarito com mais de 50 linhas é rejeitado, pois ultrapassa a evidência exibida pelo agente.
Resultados vazios são permitidos quando representarem a resposta correta.

A saída informa SHA-256 de perguntas, dados, regras e opções. Os testes também conferem
valores calculados independentemente dos SQLs: faturamento realizado de BRL 460,40,
saldo do SKU `001` de 12 unidades e valor conhecido de estoque de BRL 145,00, por exemplo.
Casos com modelo roteirizado verificam que incluir cancelamentos, converter códigos para
número ou duplicar medidas no JOIN reprova a evidência. Há cobertura para fechamento de
cursores em sucesso e falha do modelo, inclusive mantendo a conexão base utilizável.

## Rodada com modelo real

Com chave configurada e custos liberados, use um diretório específico por rodada:

```bash
uv run --locked olheiro-eval --suite vendas --model google:gemini-3.8-flash \
  --concurrency 1 --output-dir evals/results/minha-rodada
uv run --locked olheiro-eval --suite estoque --model google:gemini-3.8-flash \
  --concurrency 1 --output-dir evals/results/minha-rodada
```

Sem `--suite`, mantém-se o Brasileirão. A execução valida os gabaritos antes de apresentar
a estimativa e pedir confirmação. `--category`, `--limit` e `--concurrency` continuam
disponíveis; limite e concorrência precisam ser positivos. O padrão é **6 requisições e
12 chamadas de ferramenta por caso**, ajustáveis com `--request-limit` e
`--tool-calls-limit`. Ambos devem ser positivos. São limites de execução, não um teto
financeiro. O SDK não repete requisições em erro nesta avaliação. As suítes usam fixtures próprias
mesmo com `OLHEIRO_DATASET` definido. Não abrem nem modificam o banco/workspace pessoal;
logs e traces da rodada real continuam seguindo as configurações de observabilidade.
Não há cache nem fallback no benchmark. Solicitações de gravação são recusadas e afetam
a nota de segurança.

Sem `--output-dir`, resumos ficam em `evals/results/<suite>/<modelo>.json`, com
`suite_revision`; o comparativo fica em `evals/results/README.md`. O diretório explícito
substitui essa raiz. Cada arquivo guarda a última rodada daquele par
suíte/modelo. Portanto uma execução filtrada substitui a anterior desse par: preserve uma
cópia antes de testar filtros e compare sempre as mesmas perguntas e revisões. Relatórios
anteriores sem identificação de suíte são lidos como Brasileirão. Diretórios de rodadas
arquivadas não entram no comparativo da raiz. Cada caso novo preserva pergunta, saída
completa, SQL, tabela, insights e resultados dos avaliadores. O consumo das respostas já
recebidas é registrado mesmo se uma etapa posterior falhar; chamadas sem uso retornado
pelo provedor não permitem medir a cobrança. O relatório usa "Falhas de execução" porque
um limite do agente não é um erro da API.

## Interpretação e limites

- **Comportamento:** respondeu, recusou ou se protegeu conforme o caso.
- **Evidência:** linhas completas equivalentes ao gabarito, com correspondência entre colunas
  e preservação de multiplicidade. Tolera arredondamento; escala percentual só é aceita
  nas colunas indicadas em `metadata.percentage_columns` (índices do gabarito a partir de zero).
  Exemplo: `percentage_columns: [2]` para o percentual na terceira coluna. Valores monetários
  e contagens não recebem conversão automática 1↔100. Nomes não latinos são preservados.
- **Menções:** termos esperados quando especificados pelo caso.
- **Ancoragem:** números da resposta presentes nos dados retornados ou na pergunta;
  inclui datas, identificadores e detalhes textuais como `Central: 10, Loja: 2`. Conversão
  de escala só é considerada quando a afirmação usa `%` ou `por cento` explicitamente.

Anos não recebem mais uma dispensa fixa do domínio de futebol: `2019 unidades` precisa
estar ancorado como qualquer outra medida. A ancoragem continua heurística, com tolerâncias
numéricas; não comprova significado de negócio, sinal, unidade ou afirmações qualitativas.
Não há LLM-juiz. O hash identifica as fixtures,
não a versão do agente: registre também o commit e o `uv.lock` ao comparar rodadas reais.

A F9C, conversa com contexto, já está implementada. Estas suítes continuam avaliando
perguntas independentes; avaliação de conversas completas é uma ampliação própria.
Publicação e outras pendências estão em [pendencias-projeto.md](pendencias-projeto.md).

## Corrigir a avaliação sem repetir chamadas ao modelo

Quando a inspeção comprovar outra apresentação correta da resposta, declare seu SQL em
`metadata.alternative_sql`. O avaliador aceita uma das alternativas completas, validando
segurança, limite de linhas e colunas percentuais de todas elas. Ele não aceita um subconjunto
arbitrário da tabela: erros de medida, duplicação ou filtros continuam reprovados.

Reavalie uma saída já salva em outro diretório:

```bash
uv run --locked olheiro-eval \
  --regrade evals/results/minha-rodada/vendas/google_gemini-3.8-flash.json \
  --output-dir evals/results/minha-rodada-reavaliada
```

Esse modo não lê `Settings`, constrói modelo nem chama API. Confere a identidade das
perguntas e reexecuta o SQL salvo para verificar se a tabela ainda é a mesma nas fixtures.
Depois reaplica os quatro avaliadores, preservando consumo, duração, data e `suite_revision`
da execução. `grading_revision` identifica a versão atual dos gabaritos. Saídas antigas
sem conteúdo completo, perguntas diferentes ou evidência alterada exigem outra execução.
O diretório da execução original é recusado como destino para evitar sobrescrita.

Referências: [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) e
[cliente Python do DuckDB](https://duckdb.org/docs/stable/clients/python/overview).
Contratos também conferidos com as versões instaladas, sem atualização de dependências.

Perguntas para revisar os conceitos:

1. Por que um teste com modelo roteirizado não mede a acurácia do Gemini?
2. Como fornecedores duplicados podem inflar o valor do estoque em um JOIN?
3. Por que duas rodadas só são comparáveis com as mesmas perguntas, dados e regras?
