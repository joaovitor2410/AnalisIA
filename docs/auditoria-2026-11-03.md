# Auditoria da AnalisIA — 03/11/2026

Revisão do checkout `97dce27`, a pedido do autor. Foram encontrados problemas que não eram
cobertos pelos 198 testes existentes. Esta entrega corrige esses problemas antes de iniciar
a próxima fase funcional, F9B.

## Escopo e resultado

Revisados os módulos do agente, ferramentas e validação SQL, bancos e importação CSV/Parquet,
semântica, cache, dashboard, configuração, CLI, Streamlit, MCP, avaliações, observabilidade,
launcher, testes, Docker/Compose, smoke e CI. O diagnóstico abriu a base local e confirmou
450 classificações, 45 clubes, glossário em sincronia e bloqueio de leitores externos.

A suíte inicial passou: **198 testes**. A suíte ampliada passou: **228 testes**, tanto no
checkout quanto em uma cópia temporária sem `.env` e sem as chaves dos provedores.
Não houve chamada ao Gemini, atualização de dependências, publicação ou push.

## Problemas corrigidos

| Prioridade | Problema confirmado | Correção e verificação |
|---|---|---|
| Alta | A normalização do cache confundia `valor > 100` com `valor < 100`, sinais negativos, códigos, acentos e caixa. Era possível receber evidência válida para outra pergunta. | Chave conserva o conteúdo, normalizando apenas Unicode canônico e espaços nas pontas. Entradas antigas são reindexadas pela pergunta original; a leitura não sobrescreve o arquivo. Testes com filtros, códigos, espaços, números e texto não latino. |
| Alta | `SELECT nextval('workspace.seq')` passava pelo validador e avançava uma sequência existente, sem aprovação. | Recusa de funções conhecidas que alteram sequência, estado ou logs, inclusive em subconsultas e chamadas qualificadas. Teste com sequência real confirma que seu valor permanece intacto. `SELECT INTO` também é recusado no validador; o motor atual já recusava essa sintaxe. |
| Alta | O avaliador conferia colunas isoladamente e aprovava totais trocados entre clientes. Uma coluna também podia servir de correspondente para várias colunas do gabarito. | Correspondência um a um entre colunas e entre linhas completas. Mantém suporte a linhas/colunas reordenadas, colunas extras, arredondamento e escala percentual. Testes cobrem associações erradas, duplicidades e nulo versus texto. |
| Média | Timeout ou erro de memória no perfil de coluna escapava da ferramenta e interrompia a análise. Na página Dados, uma falha interrompia as demais abas. | A ferramenta retorna erro legível para o modelo; a página mostra o problema da tabela e continua as demais. Testes de timeout/memória e AppTest com uma tabela falhando e outra disponível. |
| Média | A CLI exigia construir o modelo antes de consultar o cache, impedindo respostas guardadas quando faltava a chave. | Modelo construído somente quando necessário. Testes confirmam cache sem modelo e exigência da chave em falta de cache ou com `--no-cache`. |
| Baixa | Schemas em maiúsculas e referências a CTEs com caixa diferente eram rejeitados, embora válidos no DuckDB. | Comparação dos identificadores sem distinguir caixa, preservando as restrições de schemas e catálogos. |

As restrições SQL continuam sendo defesa em profundidade. Não representam uma fronteira
completa de isolamento; o próprio DuckDB recomenda isolamento de sistema operacional para
SQL não confiável. Referências oficiais: [segurança](https://www.duckdb.org/security),
[sequências](https://duckdb.org/docs/current/sql/statements/create_sequence).

## Validação

- **228 testes aprovados**, incluindo integração MCP e interface via AppTest.
- **228 testes aprovados** em cópia temporária sem `.env` e sem chaves de API.
- Ruff lint e formatação aprovados; mypy sem erros nos 31 módulos verificados.
- `olheiro-check` aprovado no ambiente local, sem imprimir valores de segredos.
- Wheel e distribuição fonte construídos offline em `/tmp/analisia-audit-dist`.
- `git diff --check` sem erros.

Para reproduzir no projeto:

```bash
uv run --locked olheiro-check
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked analisia
```

Docker não está instalado neste Mac. A configuração foi revisada, mas a imagem, a rede e o
filesystem do contêiner desta revisão ainda precisam passar pela CI após push liberado pelo
autor. Testes offline não medem a acurácia atual do Gemini; a comparação real F5 permanece
pendente de faturamento e execução autorizados. Avisos de depreciação do loop assíncrono nas
bibliotecas de avaliação não impediram a aprovação dos testes.

## Próxima fase: F9B — qualidade e semântica dos dados

F9A e F9A.1 estão concluídas. A F9B é a próxima fase funcional registrada no planejamento.
Como esta varredura encontrou falhas, esta entrega priorizou sua correção. A implementação
da F9B não está incluída nesta auditoria; o escopo abaixo deixa sua continuação definida.

| Entrega | Resultado esperado | Critério de conclusão |
|---|---|---|
| Prévia de importação | Examinar dados antes de criar a base; escolher tipos, cabeçalho, codificação, separador e decimal. Preservar identificadores com zeros iniciais. | Prévia e carga usam as mesmas opções; entradas incompatíveis falham sem publicar nem sobrescrever a base. |
| Diagnóstico de qualidade | Contagem de nulos e linhas repetidas; candidatos a chave e relacionamentos acompanhados de evidência. | Unicidade, ausência de nulos e cardinalidade verificadas no SQL; nenhuma relação é aceita apenas pelo nome da coluna. |
| Editor de semântica | Descrever tabelas, colunas, unidades e regras na interface pessoal. | Validar referências antes de salvar; invalidar cache após mudança e preservar o isolamento entre bases e a demo. |
| Catálogos grandes | Descobrir tabelas e colunas conforme a pergunta, limitando o contexto inicial. | Testar busca seletiva e sinalização de truncamento, sem perder acesso às demais tabelas. |
| Validação em outros domínios | Exercitar vendas/estoque e arquivos com tipos e identificadores difíceis. | Casos offline reproduzíveis; benchmark real complementar separado da integração. |

Sequência seguinte preservada: F5 complementar (acurácia), F9C (conversa com contexto) e F8C
(publicação). Hospedagem/acesso e condições de redistribuição dos dados ainda exigem decisão.
Antes de acesso público amplo, continuam pendentes coordenação persistente entre processos,
autenticação por usuário, quotas persistentes e retenção dos logs. Esses itens já constavam da
[auditoria anterior](auditoria-2026-10-27.md) e não são apresentados como concluídos aqui.
