# Avaliações em múltiplos domínios — F5 complementar

Um benchmark reúne perguntas, dados fixos e critérios independentes para conferir as
respostas. Testes com modelo roteirizado verificam se a integração e os avaliadores detectam
erros conhecidos. Só a rodada com um modelo real mede sua capacidade de escolher ferramentas,
interpretar regras e produzir a análise. Esta fase conclui a preparação offline do benchmark;
a comparação real permanece pendente de faturamento e liberação do autor.

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

Após o autor habilitar e liberar os custos:

```bash
uv run --locked olheiro-eval --suite vendas --model google:gemini-3.8-flash
uv run --locked olheiro-eval --suite estoque --model google:gemini-3.8-flash
```

Sem `--suite`, mantém-se o Brasileirão. A execução valida os gabaritos antes de apresentar
a estimativa e pedir confirmação. `--category`, `--limit` e `--concurrency` continuam
disponíveis; limite e concorrência precisam ser positivos. As suítes usam fixtures próprias
mesmo com `OLHEIRO_DATASET` definido. Não abrem nem modificam o banco/workspace pessoal;
logs e traces da rodada real continuam seguindo as configurações de observabilidade.
Não há cache nem fallback no benchmark. Solicitações de gravação são recusadas e afetam
a nota de segurança.

Resumos ficam em `evals/results/<suite>/<modelo>.json`, com `suite_revision`; o comparativo
fica em `evals/results/README.md`. Cada arquivo guarda a última rodada daquele par
suíte/modelo. Portanto uma execução filtrada substitui a anterior desse par: preserve uma
cópia antes de testar filtros e compare sempre as mesmas perguntas e revisões. Relatórios
anteriores sem identificação de suíte são lidos como Brasileirão.

## Interpretação e limites

- **Comportamento:** respondeu, recusou ou se protegeu conforme o caso.
- **Evidência:** linhas completas equivalentes ao gabarito, com correspondência entre colunas
  e preservação de multiplicidade. Tolera arredondamento; escala percentual só é aceita
  nas colunas indicadas em `metadata.percentage_columns` (índices do gabarito a partir de zero).
  Exemplo: `percentage_columns: [2]` para o percentual na terceira coluna. Valores monetários
  e contagens não recebem conversão automática 1↔100. Nomes não latinos são preservados.
- **Menções:** termos esperados quando especificados pelo caso.
- **Ancoragem:** números da resposta presentes nos dados retornados ou na pergunta;
  datas ISO e identificadores numéricos textuais também entram na conferência.

Anos não recebem mais uma dispensa fixa do domínio de futebol: `2019 unidades` precisa
estar ancorado como qualquer outra medida. A ancoragem continua heurística, com tolerâncias
numéricas; não comprova significado de negócio, sinal, unidade ou afirmações qualitativas.
Não há LLM-juiz nem estimativa de acurácia real nesta entrega. O hash identifica as fixtures,
não a versão do agente: registre também o commit e o `uv.lock` ao comparar rodadas reais.

Próxima fase funcional: **F9C, conversa com contexto**, após revisão do autor. A comparação
paga e a publicação F8C continuam pendentes próprias.

Referências: [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) e
[cliente Python do DuckDB](https://duckdb.org/docs/stable/clients/python/overview).
Contratos também conferidos com as versões instaladas, sem atualização de dependências.

Perguntas para revisar os conceitos:

1. Por que um teste com modelo roteirizado não mede a acurácia do Gemini?
2. Como fornecedores duplicados podem inflar o valor do estoque em um JOIN?
3. Por que duas rodadas só são comparáveis com as mesmas perguntas, dados e regras?
