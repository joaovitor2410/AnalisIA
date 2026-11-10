# Opções para a demo pública — F8C.2

**Correção de 10/11/2026:** `portfolio_app.py` agora oferece workspace individual com
troca/upload de datasets e chave Gemini por sessão. As análises prontas continuam sem API.
Não é necessário configurar chave compartilhada no servidor; o consumo pertence à chave do usuário.
Veja [correcao-workspace-2026-11-10.md](correcao-workspace-2026-11-10.md).

**Decisão atualizada em 09/11/2026:** o autor escolheu hospedagem sem custo para portfólio.
A entrada preparada é `portfolio_app.py`, para Streamlit Community Cloud, com dados sintéticos
e modelo desabilitado. Siga [publicacao-gratuita.md](publicacao-gratuita.md). A comparação
abaixo é histórica; não é mais a proposta de contratação desta entrega.

Comparação preparada em **06/11/2026**, após o autor escolher manter a demo pública e
receber opções de hospedagem antes de contratar. Nenhum provedor foi escolhido, nenhuma
conta/recurso foi criado e nenhum deploy foi executado nesta fase.

## Decisão proposta

**Para conservar o Docker/Compose atual e permitir Gemini com quota persistente, a opção
mais direta é uma VPS Linux.** É uma conclusão da arquitetura do projeto, não um benchmark
entre provedores. Como referência de custo, usei DigitalOcean; outra VPS com recursos
equivalentes também pode ser avaliada.

**Para custo de hospedagem zero, a alternativa é Community Cloud com exemplos/cache e
modelo desabilitado.** Para habilitar o Gemini ali, seria necessário antes substituir a
quota em arquivo por um backend externo persistente e rever o isolamento da execução.
Isso altera o escopo da primeira publicação.

Preços abaixo são referências publicadas consultadas na data acima, em USD. Não incluem
Gemini, impostos, domínio próprio, backups opcionais ou excedentes de tráfego. Confirme a
cotação/plano/região no provedor antes de contratar. Nenhum valor foi convertido para reais.

| Opção | Referência mensal | Compatibilidade com a AnalisIA | Trabalho antes de publicar |
|---|---:|---|---|
| **VPS Linux + Compose** | **US$ 24** no exemplo DigitalOcean, 2 vCPU/4 GiB/80 GiB | Conserva os três contêineres, rede interna/proxy e volume local | Configurar servidor, HTTPS, domínio e backup; executar smoke no destino |
| **Railway Hobby + volume** | **Mínimo US$ 5**, consumo variável; cenário ilustrativo abaixo ≈ US$ 12,15 | Docker e volume disponíveis; importação de Compose é parcial | Validar limites/rede/permissões do volume e adaptar cache mounts/serviços |
| **Render pago + disco** | **Cenário US$ 39,25** com três serviços e disco de 1 GB | Suporta Docker e disco persistente, com uma instância usando o disco | Traduzir a topologia para serviços da plataforma; validar rede/UID/health |
| **Streamlit Community Cloud** | **US$ 0** de hospedagem | Adequado como candidato para exemplos sem modelo; disco local não é durável | Preparar inicialização da base, dependências e piloto dentro dos limites da plataforma |

Fontes de preço: [DigitalOcean](https://www.digitalocean.com/pricing/droplets),
[Railway](https://docs.railway.com/pricing),
[Render](https://render.com/pricing?trk=article-ssr-frontend-pulse_little-text-block) e
[Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud).

## Por que esses tamanhos e valores

**VPS.** O Compose atual limita app a 2 GiB, Squid a 256 MiB e NGINX a 128 MiB. Uma VM
com 4 GiB deixa margem para sistema operacional, Docker e futura entrada HTTPS. Essa é uma
estimativa inicial a partir dos limites configurados; ainda falta medir uso sob carga no
destino. O plano Basic Regular de 2 vCPU/4 GiB tem referência de US$ 24/mês na tabela oficial.
O autor administrará atualizações, acesso ao servidor e recuperação. A publicação precisará
de HTTPS na frente da entrada local atual, que hoje escuta apenas em `127.0.0.1`.
[Configuração de uma Droplet](https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/).

**Railway.** O mínimo Hobby inclui US$ 5 de consumo, não é US$ 5 somado a todo o consumo.
Pelas tarifas mensais publicadas, um cenário hipotético de 1 GB médio de RAM e 0,1 vCPU
médio, somados entre todos os serviços, mais 1 GB de volume resulta aproximadamente em
`10 + 2 + 0,15 = US$ 12,15`, antes de tráfego e demais itens. Não é uma medição do projeto
nem um teto de cobrança. [Tarifas e créditos](https://docs.railway.com/pricing).

Os volumes têm restrições de réplicas, e a documentação alerta para permissões com imagens
que executam sem root. Nosso runtime usa UID 10001; essa escrita deve passar no piloto
mantendo esse usuário. [Volumes](https://docs.railway.com/volumes/reference).
A importação de Compose não cobre toda configuração, e os cache mounts têm formato próprio.
[Docker/Compose](https://docs.railway.com/builds/dockerfiles). A plataforma oferece domínio
e certificado automáticos. [Entrada HTTPS](https://docs.railway.com/networking/public-networking).

**Render.** O cenário da tabela considera app `1c-2g` a US$ 25, dois serviços
`0.5c-512mb` a US$ 7 cada e 1 GB de disco a US$ 0,25: `25 + 7 + 7 + 0,25 = US$ 39,25`.
São recursos provisionados para uma proposta com app/proxy/gateway, não um orçamento aprovado
nem uma implantação já verificada. [Preços](https://render.com/pricing?trk=article-ssr-frontend-pulse_little-text-block)
e [planos de compute](https://render.com/docs/compute-plans).
O disco só é acessível por uma instância e a troca de deploy com disco tem interrupção.
[Persistência e limitações](https://render.com/docs/disks).

**Community Cloud.** A hospedagem é gratuita, mas arquivos locais podem ser descartados.
Isso impede usar a quota diária atual como limite persistente ali. O candidato gratuito
usa `OLHEIRO_DEMO_MODE=true` e `OLHEIRO_DEMO_MODEL_ENABLED=false`, sem chave de API.
[Persistência não garantida](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).
Será preciso preparar um entrypoint que inicialize o banco ausente antes de abrir a UI;
o comando `olheiro-app` já faz isso localmente, mas não é o entrypoint automático do serviço.
Também falta testar instalação com Python 3.13 e memória no ambiente oferecido. Não é
apresentado como deploy pronto. [Ambiente do Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

## Compatibilidade que ainda precisa de prova no destino

Railway e Render terem rede privada não prova que reproduzem a rede Docker `internal`
com saída bloqueada e proxy restrito à API Gemini. Essa equivalência **não foi validada**.
Não publicaremos SQL gerado pelo modelo supondo que importar Compose ou configurar
`HTTPS_PROXY` bloqueia toda saída direta. O piloto deve medir essa propriedade ou usar
um isolamento equivalente aprovado no desenho. A VPS permite manter os controles atuais
do Compose, que já passaram na CI Linux, e repetir o smoke no servidor escolhido.

Manteremos uma única instância com `/state` persistente quando houver quota em arquivo.
Réplicas sem o mesmo disco exigem backend compartilhado; autenticação para dados particulares
continua fora desta demo pública fixa. O visitante não terá upload de bases.
O piloto de qualquer opção usará `OLHEIRO_DEMO_MODE=true` e
`OLHEIRO_DEMO_MODEL_ENABLED=false`; o modo pessoal não será o perfil da publicação pública.

## Próximo passo após a escolha

1. Escolher entre **VPS com Docker**, **PaaS com adaptação** ou **demo gratuita sem Gemini**.
2. Resolver as condições de redistribuição do futebol ou aprovar uma demo com dados sintéticos.
   O exemplo sintético de vendas já existe, mas os exemplos curados da demo atual são de
   futebol: mudar de domínio também exige curar esse conjunto.
3. Preparar a configuração específica, HTTPS, persistência/recuperação e teste de reinício.
4. Executar o piloto com modelo desabilitado, health, interface, isolamento e quota.
5. Habilitar perguntas ao modelo somente com configuração de limites também no provedor.

O custo mensal do Gemini não foi estimado nesta comparação. Em 09/11, a
[F5 real](f5-2026-11-09.md) mediu custo e consumo por caso, sem definir orçamento mensal
nem contratar serviços. Esta comparação não cria assinatura, domínio nem infraestrutura e não publica
os CSVs em outro serviço. A escolha do autor determinará a implementação da próxima etapa.
