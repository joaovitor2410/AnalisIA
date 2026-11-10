# Correção do workspace publicado — 10/11/2026

Relato do autor: no site Streamlit publicado, não era possível trocar datasets nem fazer
perguntas personalizadas. A entrada anterior `portfolio_app.py` impunha uma demonstração
fixa, com `olheiro_demo_mode=true`, sem chave/modelo, seleção/importação ocultas e chat
desabilitado. Era uma restrição implementada no produto, não uma falha do Gemini.

O teste completo também mostrou perda da seleção ao navegar entre Dados e Perguntar.
A seleção agora tem estado durável próprio, separado do widget da página. O formatador
preserva valores já formatados e distingue bases com nomes iguais usando o identificador.

## Comportamento corrigido

- `Meu workspace` é o modo inicial no site, com Loja, Vendas e Estoque já disponíveis.
- Importação CSV/Parquet mantém prévia e opções de tipos; a base importada é selecionada
  automaticamente. `Perguntar sobre esta base` leva ao chat sem trocar a seleção.
- `Conectar IA` configura uma chave/modelo por sessão. Não usa nem publica chave compartilhada
  do servidor. O formulário limpa a senha; a chave não é escrita em cache, dashboard ou logs.
- Conectar e desconectar preserva o dataset. Alterar base/modelo limpa contexto e aprovações
  anteriores, para não consultar uma base diferente ou retomar mensagens do modelo antigo.
- Conexões, fontes importadas, cache e dashboard pertencem ao visitante, sem cache global
  de dados privados ou credenciais. Caminhos de outro workspace são recusados pelo backend.
- O botão de encerrar fecha conexões e remove os arquivos da sessão. A outra sessão não é afetada.
- `Análises prontas` mantém a navegação sem API e permite voltar ao workspace completo.
- Hospedagem continua sem contratação de infraestrutura. A geração usa a cota/faturamento
  da chave de quem pergunta; sem chave, importação/exploração e exemplos continuam disponíveis.

## Verificação

Os testes AppTest percorrem a entrada real do site, o seletor por clique, navegação,
conexão/desconexão, pergunta livre e continuação, CSV e Parquet com prévia, consulta à base
importada, bases com títulos iguais e isolamento entre visitantes. A confirmação de senha
vazia e a busca nos arquivos do workspace verificam que a credencial não foi persistida.
SQL e evidência são realmente executados no DuckDB; os modelos desses testes são roteirizados.

Resultado: **351 testes aprovados**, também em cópia sem `.env`/chaves. Ruff lint/format,
mypy (46 módulos), sincronização dos 24 recursos públicos e build wheel/sdist aprovados.
O teste real autorizado foi iniciado para a pergunta de faturamento na base sintética
Vendas, com limite de quatro requisições e sem retries do SDK. O processo encerrou, mas sua saída
não pôde ser recuperada; portanto, o resultado permanece **inconclusivo**, sem afirmar
resposta correta ou consumo observado. Nenhuma chamada adicional foi feita para repeti-lo.

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked python deploy/package_smoke.py
```

O smoke do wheel também verifica criação de workspace e seleção de Estoque fora do checkout.
As métricas antigas da F5 não são uma medição desta versão. Funcionamento dos fluxos não
equivale a garantir acurácia de 100% de um LLM ou disponibilidade da API.

## Atualizar o site

O arquivo principal continua **portfolio_app.py**, com Python 3.13. Envie o commit após
liberação do autor e aguarde a CI/redeploy. Se necessário, reinicie o app no painel do
Streamlit e abra uma nova sessão. A correção local só chega ao endereço público após esse envio.
