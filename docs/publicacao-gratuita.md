# Publicar a AnalisIA no portfólio

Escolha de 09/11/2026: **Streamlit Community Cloud**, usando `portfolio_app.py`.
O serviço oferece hospedagem gratuita e integra com GitHub; não é necessário contratar
VPS, domínio ou banco externo. [Documentação oficial](https://docs.streamlit.io/deploy/streamlit-community-cloud).

## Workspace completo e análises prontas

A partir da correção de 10/11, `portfolio_app.py` abre **Meu workspace** por padrão.
A barra lateral permite trocar entre Loja, Vendas e Estoque, importar CSV/Parquet e conectar
a IA. Em **Importar CSV/Parquet**, confira a prévia, importe e clique **Perguntar sobre esta base**.
A base selecionada permanece ativa ao navegar entre páginas ou conectar/desconectar a IA.

Em **Conectar IA**, informe sua chave Gemini e clique **Usar chave nesta sessão**. A chave
é mantida pelo cliente de IA somente na sessão, sem cache global ou gravação em arquivos.
O campo de senha é limpo ao enviar. Perguntas e dados necessários à análise são enviados ao
Google, usando a cota/faturamento da chave informada. Hospedagem gratuita não torna a API gratuita.

O modo **Análises prontas** continua disponível, com dez exemplos sem chave ou chamada ao
modelo: loja fictícia com 120 pedidos, 13 clientes e seis meses. Nesse modo, selecione
**Meu workspace** para habilitar dados próprios e perguntas livres.

O servidor continua ignorando `.env`, variáveis de ambiente e segredos pessoais nessa entrada.
Não coloque uma chave compartilhada em Secrets: cada visitante conecta a própria chave.
Datasets, conexões, histórico, cache e dashboard ficam isolados por sessão em diretório
temporário. Use **Encerrar sessão e apagar meus uploads** para fechar as conexões e remover
seus arquivos; **Desconectar IA** retira a chave da sessão sem remover as bases.
Os uploads não têm persistência garantida em reinícios do serviço.
Os dados sintéticos são do próprio projeto: [origem](../examples/datasets/portfolio/SOURCE.md).

## Conferir no computador

```bash
uv sync --locked
uv run --locked streamlit run portfolio_app.py
```

Abra o endereço informado. Em Meu workspace, selecione uma base ou importe arquivos.
Para novas análises, conecte sua chave; para exemplos sem API, escolha Análises prontas.
O agente completo continua disponível por `uv run --locked analisia`.

## Passos que dependem da sua conta

1. Rode os testes abaixo e libere o push da entrega. O fluxo de `CLAUDE.md` reserva essa
   liberação ao autor. O arquivo precisa estar no GitHub antes de o serviço poder encontrá-lo.
2. Acesse [Streamlit Community Cloud](https://share.streamlit.io/) e conecte sua conta GitHub.
3. Em criar/deploy app, selecione o repositório `joaovitor2410/AnalisIA` e a branch `main`.
4. Informe **`portfolio_app.py`** como arquivo principal.
5. Nas configurações avançadas, escolha **Python 3.13**. Deixe a área de segredos vazia.
6. Escolha um subdomínio disponível e publique. Use o endereço `*.streamlit.app` no portfólio.
7. Se a instalação falhar, consulte os logs e confira primeiro a versão do Python e o arquivo
   principal. O `uv.lock` da raiz já descreve as dependências; não é necessário criar outro
   `requirements.txt` com versões diferentes.

[Deploy e Python](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[detecção de dependências](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

O serviço pode hibernar o app após inatividade e tem limites de recursos. Um visitante pode
reativá-lo; isso é aceitável para este portfólio. Não há garantia de disponibilidade contínua.
[Limitações oficiais](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).

## Aceitação depois de publicar

- Abra em janela anônima: Meu workspace deve oferecer três bases e importação.
- Conecte sua chave e envie uma pergunta personalizada sobre a base ativa.
- Importe um CSV/Parquet, confira a prévia e consulte essa base.
- Navegue de Dados para Perguntar e confirme que a seleção foi preservada.
- Alterne para Análises prontas: os dez exemplos devem funcionar sem chave.
- Confira o gráfico mensal, a recusa de margem e o botão de fixar no dashboard.
- Abra outra janela anônima: o dashboard deve começar vazio.
- Confira que os uploads de uma janela não aparecem no outro visitante.
- Confira no celular e pelo teclado a legibilidade e a navegação.
- Reinicie pelo painel: a demo deve voltar com os exemplos disponíveis.

Você pode complementar o link com um vídeo curto. Para publicar sem financiar consultas
de visitantes, mantenha a conexão de IA por chave individual e o modo sem API com análises prontas.

## Testar antes do push

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked python deploy/bundle_resources.py --check
uv run --locked olheiro-eval-chat --validate-only
uv build --offline
uv run --locked python deploy/package_smoke.py
```

O teste do wheel usa dependências já instaladas, instala o artefato em diretório temporário e
comprova que os recursos não vêm do checkout. Ele também faz parte da CI.

Não há deploy remoto executado nesta entrega. O piloto no destino depende dos passos da sua conta.
