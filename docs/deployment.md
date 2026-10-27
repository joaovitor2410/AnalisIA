# Docker e CI — Fase 8A

Escopo escolhido pelo autor em 2026-10-26: preparar Docker e CI primeiro. Esta entrega não
publica demo, cria conta em provedor nem distribui imagens em registry.

## Executar e verificar

Requisitos: Docker Engine ou Docker Desktop e Compose v2 com suporte a `--wait`.
As bases são Python `3.13.16-slim-trixie`, uv `0.13.1` e Debian `trixie-slim` para o Squid.
Dependências Python seguem `uv.lock`, com `uv sync --locked --no-dev`.
Tags de imagem são explícitas; o lock Python não fixa os pacotes Debian nem o digest das
bases. Atualizações dessas bases exigem novo build e validação.

Na raiz do checkout:

```bash
docker version
docker compose version
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 120
curl --fail http://127.0.0.1:8501/_stcore/health
docker compose exec -T app python deploy/smoke.py
```

Abra http://localhost:8501. `config --quiet` valida sem imprimir a configuração resolvida,
que pode conter a chave. O `.env` é opcional; `GOOGLE_API_KEY` habilita novas perguntas.
A interface web e o MCP stdio são pontos de entrada separados.

Outra porta: `OLHEIRO_PORT=8502 docker compose up --detach --wait`.
Logs: `docker compose logs --follow app egress`.
Encerrar preservando os dados: `docker compose down`.

### Workspace em uso ao rodar localmente

Fora do Docker, uma instância anterior do app, CLI ou MCP pode manter o arquivo
`data/workspace.duckdb` aberto. O DuckDB permite um processo escritor por arquivo; mudar só
a porta do Streamlit não separa o workspace. Encerre a instância anterior com `Ctrl+C` no
terminal onde foi iniciada e use `uv run olheiro-app`. Não apague o banco para liberar o lock.
O launcher explica o conflito antes de iniciar outro servidor; uma corrida posterior aparece
na interface com o botão **Tentar novamente**. Reinicie o processo após atualizar módulos Python.
Para processos simultâneos, configure caminhos de workspace e arquivos de estado separados;
as tabelas salvas pertencem ao workspace de cada processo.

O health HTTP prova que o Streamlit responde. O smoke test verifica também abertura da base,
SQL, blindagem, filesystem, usuário, AppTest e regras de rede. Execute-o numa instância recém
iniciada, sem sessões ativas no navegador: ele usa um processo separado para o workspace,
cujo arquivo admite um processo escritor.

## Imagem e estado

O build instala as dependências no builder; o runtime não leva uv nem ferramentas de
desenvolvimento. O código fica em `/app/src`, instalado em modo editável para preservar a
raiz dos recursos usada pelo projeto. O filesystem do runtime é de leitura, inclusive o código.
Os CSVs e o glossário entram no build; o banco bruto é criado e validado durante essa etapa.
Não se copiam banco local, `.env`, cache pessoal, dashboard ou logs do autor.

| Caminho | Uso | Persistência |
|---|---|---|
| `/app/data/raw` | CSVs | Imagem, leitura |
| `/app/data/olheiro.duckdb` | Banco derivado | Imagem, leitura |
| `/app/semantic` | Glossário | Imagem, leitura |
| `/state` | Workspace, cache, dashboard, logs e exportações | Volume `olheiro_state` |
| `/state/datasets` | Bases pessoais CSV/Parquet importadas, com estado próprio | Mesmo volume |
| `/tmp` | Arquivos temporários | tmpfs, descartado ao recriar |

O usuário é `10001:10001`; capacidades Linux são removidas e novos privilégios bloqueados.
O app tem limite de 2 GB, duas CPUs e 256 processos. O DuckDB mantém o limite de 1 GB e o
prazo de 10 segundos por consulta.

`olheiro-app` também funciona fora do Docker. Quando a base falta, carrega num temporário,
valida tabelas e glossário e publica atomicamente sem sobrescrever. Uma base existente é apenas
validada, sem recriação ou conversão de versão. Falhas não publicam um banco parcial.

## Rede

`app` pertence apenas à rede `isolated`, com `internal: true`. `egress` pertence às redes
interna e externa. `HTTPS_PROXY` e `HTTP_PROXY` encaminham o tráfego pelo Squid, que só permite
`CONNECT` para `generativelanguage.googleapis.com:443`, por domínio exato. Outros destinos
ou portas são negados. O proxy não é publicado e não intercepta TLS; o certificado segue
sendo validado pelo SDK.

O serviço `web` (NGINX sem root, versão 1.30.6) publica HTTP e WebSocket no host e encaminha
para `app:8501`. Ele participa das redes `frontend` e `isolated`; o app continua exclusivamente
na rede interna. Essa entrada separada evita depender da publicação de portas de um serviço
em rede interna, que falhou na validação do runner Linux. O health do proxy verifica todo
o caminho HTTP até o Streamlit.

O SDK Gemini instalado usa `trust_env=True`. A receita atende ao provedor Google implementado
no Olheiro. Outros provedores ou OTLP remoto exigem política explícita e novo teste.
O Compose usa tracing em arquivo e `OLHEIRO_TRACE_CONTENT=false`. O registro de execuções
ainda guarda as perguntas no volume local; ele não é conteúdo público.

O smoke test verifica que a rede não permite conexão externa direta, que o proxy nega
`example.com:443` com 403 e que permite túnel TCP para a API. Esse túnel não gera conteúdo
pelo modelo nem consome cota. A CI não faz chamadas ao Gemini.

## CI

O workflow roda em push para `main`, pull requests e disparo manual. Tem permissão somente
de leitura, ações fixadas por SHA, timeout e cancelamento de execuções antigas.

1. Instala Python conforme `.python-version` e uv `0.13.1`.
2. Sincroniza o lock, executa Ruff, formatação, mypy e pytest e constrói wheel/sdist.
3. Após qualidade, valida o Compose, constrói as imagens e inicia sem chave.
4. Executa smoke e health HTTP, mostra logs em falha e descarta volumes temporários do runner.
   Isso não afeta o volume no computador do autor.

A infraestrutura base foi validada no GitHub em 2026-10-26, no commit `dc48922`, pela
[execução 40365502597](https://github.com/joaovitor2410/AnalisIA/actions/runs/40365502597):
qualidade, build, smoke de isolamento e acesso HTTP pelo host passaram. A matriz pessoal/demo
também passou no commit `845767d`, na
[execução 40502502772](https://github.com/joaovitor2410/AnalisIA/actions/runs/40502502772).
As alterações da F9A acrescentam importação CSV/Parquet ao smoke, `/state/datasets` gravável e
limite HTTP de 64 MB; precisam de nova CI após push autorizado. Docker segue ausente
neste Mac; a evidência de execução da infraestrutura vem do runner Linux.
Uploads são encaminhados sem buffering de requisição no NGINX, para não ocupar todo o
tmpfs de 32 MB do proxy com um arquivo permitido de até 50 MB.

## Backup e atualização

Pare a instância antes de copiar, para o workspace não estar em escrita:

```bash
docker compose stop
docker compose cp app:/state ./backup-state
docker compose start
```

O backup pode conter perguntas e respostas; mantenha-o privado. Restaure com a instância
parada, preservando a escrita pelo UID 10001 em `/state`. Atualizar a imagem não requer
apagar o volume. Após mudar os dados/glossário do exemplo, refaça o build e valide. O cache
da F9A invalida respostas por revisão da base/semântica. Bases pessoais importadas persistem
no volume; veja [datasets.md](datasets.md) para importação e recarga explícita.

## Próxima etapa

A Fase 8B prepara a demo antes de publicar, conforme escolha do autor: estado por sessão,
exemplos curados, leitura e limites de uso. Veja [docs/demo.md](demo.md). O modo pessoal
continua compartilhando estado entre sessões da instância. Hospedagem, acesso, condições de
redistribuição dos dados e publicação ficam para uma etapa posterior.

DuckDB permanece em `>=1.5.6,<2`. A versão 2.0 altera o formato padrão: testes em cópias e uma
estratégia de retorno precedem a atualização dos bancos. A recomendação oficial prevê teste
num ambiente separado antes da migração.

Referências consultadas em 2026-10-26:

- [uv no Docker](https://docs.astral.sh/uv/guides/integration/docker/)
- [uv no GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
- [Redes Compose](https://docs.docker.com/compose/how-tos/networking/)
- [Serviços Compose](https://docs.docker.com/reference/compose-file/services/)
- [Controle de acesso Squid](https://www.squid-cache.org/Doc/config/http_access/)
- [Migração DuckDB 2.0](https://www.duckdb.org/docs/2.0/clients/python/migration)
- [Origem dos dados](../data/raw/SOURCE.md)

Na F9A (2026-10-27): [buffering de requisições no NGINX](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering).
