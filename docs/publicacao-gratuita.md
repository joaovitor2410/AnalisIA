# Publicar a demo gratuita do portfólio

Escolha de 09/11/2026: **Streamlit Community Cloud**, usando `portfolio_app.py`.
O serviço oferece hospedagem gratuita e integra com GitHub; não é necessário contratar
VPS, domínio ou banco externo. [Documentação oficial](https://docs.streamlit.io/deploy/streamlit-community-cloud).

## O que esta entrada apresenta

Uma loja fictícia com 120 pedidos, 13 clientes, seis meses e dez análises curadas. O visitante
escolhe uma pergunta pronta, confere SQL/tabela/gráfico, explora os dados e monta um dashboard
da sessão. Não há upload, chamada a LLM nem pergunta livre nesse perfil. A interface informa
que a geração de novas análises com IA está disponível na execução local do projeto.

O perfil ignora `.env`, variáveis de ambiente e segredos pessoais. Não coloque chaves de API
na configuração desta demo: elas não são necessárias. Banco e estado são temporários;
reiniciar recria os dados e cada visitante tem histórico/dashboard próprios. Isso combina
com a proposta de demonstração sem exigir disco persistente ou quota distribuída.
Os dados sintéticos são do próprio projeto: [origem](../examples/datasets/portfolio/SOURCE.md).

## Conferir no computador

```bash
uv sync --locked
uv run --locked streamlit run portfolio_app.py
```

Abra o endereço informado. Escolha uma análise, fixe no dashboard e explore Dados.
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

- Abra em janela anônima: os dez exemplos devem funcionar sem chave.
- Confira o gráfico mensal, a recusa de margem e o botão de fixar no dashboard.
- Abra outra janela anônima: o dashboard deve começar vazio.
- Confira Dados: 120 pedidos e 13 clientes fictícios; sem importação de arquivos.
- Confira no celular e pelo teclado a legibilidade e a navegação.
- Reinicie pelo painel: a demo deve voltar com os exemplos disponíveis.

Uma alternativa sem conta de hospedagem é gravar um vídeo curto da execução local e colocá-lo
no portfólio, junto do GitHub. Se quiser mostrar IA real sem financiar visitantes, grave a
execução local de uma pergunta nova; a versão pública continua com SQL curado.

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
