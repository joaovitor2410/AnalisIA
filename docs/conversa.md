# Conversa com contexto — F9C

Uma pergunta de continuação depende da análise anterior. Depois de perguntar quem foi
campeão de 2019 e com quantos pontos, “e em 2020?” deve manter competição e métrica,
mudando o ano. A F9C fornece esse contexto ao agente no app e no modo interativo da CLI.
O modelo continua responsável por interpretar a referência; cada resposta precisa de
evidência SQL validada e executada no banco atual.

## Usar na interface

```bash
uv run --locked analisia
```

Em **Perguntar**, envie uma pergunta completa e depois uma continuação. Exemplo:

1. “Quem foi campeão brasileiro de 2019 e com quantos pontos?”
2. “E em 2020?”
3. “Compare os dois anos em um gráfico.”

O rodapé mostra quantas análises compõem a janela de contexto. **Nova exploração** limpa
histórico visual, rascunho e contexto; preserva perguntas contabilizadas e itens fixados.
Perguntas prontas, selecionadas ou digitadas com o mesmo texto, iniciam um novo contexto:
são análises independentes e continuam disponíveis sem modelo, mesmo após esgotar a quota.
Continuações geradas não aparecem como atalhos independentes.

Trocar de base ou editar a semântica remove o contexto e as pendências anteriores.
Sessões e visitantes distintos têm instâncias separadas, inclusive na demo. Na demo,
continuações novas exigem opt-in do modelo e respeitam os limites já existentes.

## Conversar pelo terminal

```bash
uv run --locked olheiro-ask --chat
# Ou comece com uma pergunta:
uv run --locked olheiro-ask --chat "Quem foi campeão brasileiro de 2019 e com quantos pontos?"
# Conversa sem ler nem gravar cache de respostas:
uv run --locked olheiro-ask --chat --no-cache
```

Digite `/nova` para limpar o contexto ou `/sair` para encerrar. EOF também encerra a sessão.
Cada pergunta mostra SQL, tabela e consumo como antes; `--verbose` mostra as ferramentas.
`uv run --locked olheiro-ask "pergunta"` continua sendo uma consulta independente.
Na CLI, use `/nova` explicitamente quando quiser mudar de assunto: o terminal não seleciona
automaticamente perguntas prontas. O modelo é construído apenas na falta de cache.

No chat, a CLI relê a semântica a cada turno e depois da decisão de salvar, caso tenha
mudado enquanto o usuário respondia. A conexão de dados permanece aberta durante a conversa.
Para usar CLI e app simultaneamente, mantenha workspaces diferentes, conforme o README.

## O que entra no contexto

`olheiro.conversation.Conversation` guarda pares completos de pergunta e saída estruturada
da análise: resposta, SQL, insights e especificação de gráfico. Mantém até **6 análises** e
**16.000 caracteres** desses pares, removendo os mais antigos. Não envia a tabela inteira;
o agente pode reexecutar a consulta anterior para recuperar os dados necessários.

O limite se refere ao contexto de conversa, sem incluir instruções, catálogo e ferramentas.
Se um único par exceder o teto, ele também é descartado; a interface avisa que o contexto
foi limitado. O histórico visual pode continuar exibindo análises que já saíram da janela.
O usuário deve repetir referências antigas. Na falta de referente, a instrução pede
esclarecimento com `answerable=false`, sem inventar competição, período ou métrica.

Cada nova chamada reconstrói pares de `ModelRequest(UserPromptPart)` e
`ModelResponse(TextPart)`, passando-os como `message_history`. Isso funciona também quando
a análise anterior veio do cache. Mensagens de ferramentas, retentativas, assinaturas do
provedor e decisões de aprovação não entram nessa memória. A retomada de uma pausa usa
somente as mensagens originais daquela execução, preservando o protocolo do provedor.

O contexto fica em memória e não é restaurado entre sessões/processos. Cache continua
guardando perguntas e resultados; logs/traces seguem as configurações de conteúdo existentes.
Na demo, contexto/cache/dashboard são privados da sessão e traces detalhados seguem desligados.

## Cache e isolamento

A chave contextual combina a pergunta com um hash dos pares que o modelo receberá.
A mesma continuação em outro contexto não reutiliza o resultado. A revisão da base e do
glossário continua sendo o namespace externo do cache; a evidência é revalidada e reexecutada
em qualquer acerto. O hash não inclui timestamps das mensagens, permitindo reaproveitar uma
análise quando o contexto efetivo for idêntico.

Entradas antigas, sem hash de contexto, permanecem independentes. Resultados de continuações
têm `context_key` e ficam fora de `AnswerCache.questions()`. Os pares anteriores não são
gravados dentro dessa entrada. O contexto é descartado quando conexão, regras, namespace
ou permissão de gravação mudam.

O MCP mantém perguntas independentes: o modelo do cliente controla sua própria conversa.
Esta fase não adiciona histórico global nem identificador de conversa ao servidor stdio.

## Aprovar uma gravação

Histórico não autoriza salvar de novo. Uma pendência está vinculada à conexão da sessão e
ao glossário da execução. A decisão é consumida uma única vez; outra conexão, regra ou
modo de leitura causa `ApprovalContextError` antes de executar ferramentas ou chamar o modelo.
Uma segunda gravação exige outro pedido e outro clique. Se a retomada falhar após consumir
a decisão, faça um novo pedido; a aprovação antiga não pode ser reenviada.

Pausas e falhas não entram no contexto. Após concluir uma gravação ou recusa de gravação,
apenas a análise final entra na janela, sem chamadas antigas. A retomada preserva consumo
acumulado e limites da mesma análise. Ela continua fora do cache de respostas.

## Validação desta fase

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked olheiro-check
```

**290 testes offline**, incluindo continuação após cache, cache distinto por contexto,
evidência obrigatória por turno, corte de pares completos, limpeza ao trocar base/semântica,
Nova exploração, separação entre visitantes, CLI com/sem cache e aprovações de uso único.
A suíte também passou em cópia temporária sem `.env` e sem chaves de API.
Wheel/sdist e diagnóstico também passaram. O diagnóstico usou um workspace temporário,
pois o workspace pessoal estava ocupado por outra instância; o processo existente foi preservado.

Uma verificação real com `gemini-3.8-flash` partiu de resposta em cache sobre o campeão
de 2019 e perguntou “e em 2020?”. Em **2 requisições**, obteve Flamengo, 71 pontos,
sustentado por `SELECT season, team, points FROM raw.brasileirao WHERE season = 2020 AND place = 1`.
Usou banco/cache temporários, leitura e limite de quatro requisições, sem retentativas do
SDK. Este caso confirma o fluxo, sem substituir o benchmark real F5.

Pydantic AI 2.59.0 e Streamlit 1.66.1 conferidos no ambiente instalado, sem dependências novas.
Referência: [histórico de mensagens do Pydantic AI](https://pydantic.dev/docs/ai/core-concepts/message-history/).
Não há persistência de conversas, resumo por LLM nem busca de memórias antigas nesta fase.
A [F8C.1](operacao.md) acrescenta rotação dos logs e coordenação de arquivos no disco local.
Publicação, autenticação e estado entre réplicas sem disco comum continuam pendentes.

Perguntas para revisar os conceitos:

1. Por que “e em 2020?” precisa de uma chave de cache diferente em conversas diferentes?
2. Por que uma aprovação anterior não deve autorizar uma nova gravação?
3. Por que limitar o contexto enviado ao modelo não elimina a necessidade de validar o SQL?
