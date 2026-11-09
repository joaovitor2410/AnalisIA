# Preparação operacional local — F8C.1

Esta fase prepara a persistência antes da escolha de hospedagem. Cache e dashboard continuam
em JSON; a mudança coordena escritores de processos diferentes no mesmo disco. A quota
diária da demo passa a sobreviver a reinícios, e logs/traces locais têm rotação por tamanho.
Não houve migração de bancos, dependência nova ou publicação.

## Estado compartilhado no mesmo filesystem

`JsonFile.update()` bloqueia um sidecar estável, lê a versão atual, permite a alteração e
publica um arquivo completo por troca atômica. Usa `fcntl.flock` no macOS/Linux, temporário
com nome único na mesma pasta, flush e `fsync` antes do replace. A segunda instância só lê
para atualizar depois que a primeira libera a transação. Isso evita perder alterações de
cache/dashboard quando dois objetos ou processos gravam ao mesmo tempo.

Uma exceção no corpo da transação ou antes da publicação preserva a versão anterior.
Um processo encerrado durante a alteração libera o lock pelo sistema operacional.
JSON inválido é reportado, sem sobrescrever o arquivo como se estivesse vazio. Leituras de
JSON inteiro continuam vendo uma versão completa, anterior ou posterior ao replace.

O sidecar tem formato `.nome-do-arquivo.lock` e permanece no disco. Não o remova enquanto
houver escritores: seu nome precisa apontar sempre para o mesmo lock. Temporários normais
são removidos no sucesso ou na falha tratada; encerramento abrupto durante a escrita pode
deixar um temporário órfão. Com todos os processos parados, ele pode ser examinado e removido.

As garantias são locais e por arquivo. Não há transação conjunta de vários JSONs, garantia
contra queda de energia nem suporte validado a locks em NFS/armazenamento distribuído.
Todos os escritores devem usar esta versão: reinicie os processos antigos antes de compartilhar
estado. Os arquivos já existentes não são migrados nem reescritos na inicialização.

O DuckDB ainda admite um processo escritor por workspace. App, CLI e MCP simultâneos
precisam de workspaces diferentes; podem coordenar os JSONs no mesmo disco. Conversas,
aprovações e dashboards da demo continuam privados da sessão.

## Quota diária persistente da demo

```dotenv
OLHEIRO_DEMO_TOTAL_QUESTION_LIMIT=10
OLHEIRO_DEMO_BUDGET_PATH=data/demo-budget.json
```

O limite agora vale por **dia UTC**, para os processos que usam o mesmo arquivo. Cada
tentativa reserva uma unidade em uma transação antes de chamar o modelo. Reiniciar o app
ou abrir outra aba não recupera as unidades. No próximo dia UTC, a primeira reserva renova
o contador automaticamente. A data UTC é explícita e independente do fuso do servidor.

Falhas do modelo também consomem a reserva; não há devolução. Cache não consome quota e
continua disponível após o limite. O limite por sessão (padrão 5), o teto por análise
(6 requisições/12 ferramentas) e o opt-in do modelo continuam valendo.

Se o arquivo estiver incompatível, corrompido, sem permissão ou com data no futuro, a reserva
falha e nenhuma nova chamada é autorizada. A interface mostra a indisponibilidade e mantém
os exemplos funcionando. Verifique permissões, relógio e backups antes de recuperar o arquivo;
não o apague para liberar uso, pois apagar ou perder esse estado inicia uma quota nova.

No Docker, o arquivo fica em `/state/demo-budget.json`, dentro do volume existente. Todos
os processos que compartilham a quota precisam usar o mesmo caminho e o mesmo limite.
Instâncias com discos diferentes mantêm quotas independentes. Não há identificação persistente
de visitante: o teto de sessão ainda depende da sessão do Streamlit, enquanto o teto diário
protege o conjunto de visitantes. Limites financeiros do provedor continuam sendo separados.

## Retenção de registros e traces

```dotenv
OLHEIRO_LOG_MAX_BYTES=5242880
OLHEIRO_LOG_BACKUP_COUNT=3
```

O padrão mantém um arquivo ativo de até **5 MiB** e até **3 arquivos anteriores** para cada
JSONL. Exemplos: `runs.jsonl`, `runs.jsonl.1`, `.2`, `.3`; o mesmo vale para `traces.jsonl`.
Ao precisar de espaço, o mais antigo é removido e os demais avançam na sequência.
`OLHEIRO_LOG_MAX_BYTES` aceita valores a partir de 1.024 bytes; backups entre 1 e 20.
As opções também são encaminhadas pelo Compose.

Escrita e rotação usam o mesmo lock de arquivo. A leitura bloqueia a rotação enquanto
reúne o ativo e os arquivos anteriores em ordem. A página Operação e a cascata de traces
consultam esses arquivos retidos, não apenas o ativo. Seus indicadores refletem esse
histórico, sem prometer totais de toda a vida do projeto.

Uma linha incompleta ou inválida é ignorada sem descartar as demais; a próxima escrita
introduz uma quebra de linha quando necessário para preservar o registro novo.
Um registro individual maior que o teto é omitido com aviso contendo só tamanho e limite,
sem seu conteúdo. O exportador de spans sinaliza falha nesse caso. Erros de I/O na gravação
de observabilidade geram aviso sem conteúdo e não substituem o resultado ou o erro original
da análise. Portanto observabilidade local não é um registro de auditoria infalível.

Rotação é progressiva: arquivos grandes já existentes não são cortados no upgrade. Ao receber
novos registros, eles avançam para os arquivos anteriores e expiram nas rotações seguintes.
Reduzir o limite não diminui retroativamente os arquivos antigos. Uma interrupção no meio
da sequência de renames pode deixar lacunas; o leitor considera os arquivos que permaneceram.
Registros e spans expiram independentemente, de modo que um trace antigo pode estar parcial
ou já ter sido removido. Para retenção por prazo/data e buscas de maior escala, use OTLP
com um backend que ofereça essa política.

Na demo, perguntas/erros continuam omitidos dos registros e traces detalhados seguem
desligados. No modo pessoal, as configurações de conteúdo anteriores continuam aplicáveis.
JSONs de cache/dashboard não entram na rotação dos logs. Versões antigas do glossário e
backups de bases também não são removidos automaticamente.

## Validar e executar

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked analisia
# Demonstração com modelo desabilitado, sem custo:
OLHEIRO_DEMO_MODE=true uv run --locked olheiro-app --server.port=8503
```

**309 testes offline**: quatro processos atualizando o mesmo JSON, escritores em threads
com objetos distintos, processo encerrado durante uma transação, rollback e falha de
publicação, rotação concorrente, preservação de UTF-8/linhas após interrupção, quota única
entre processos, reinício, renovação UTC, relógio regressivo e bloqueio sem modelo quando
a quota falha. Traces de arquivos anteriores são reconstituídos, e falha de log não oculta
o erro original. O smoke de ingestão roda em modo pessoal e demo com quota e rotação locais.
Esta fase não chama o Gemini.

A F9C foi enviada no commit `071dd2d`; sua
[CI passou](https://github.com/joaovitor2410/AnalisIA/actions/runs/41865983452) em qualidade
e nos contêineres pessoal/demo. A F8C.1 também passou após o push de `0a66018`, na
[CI 42211982307](https://github.com/joaovitor2410/AnalisIA/actions/runs/42211982307).
A [varredura de 06/11](auditoria-2026-11-06.md) acrescenta rejeição de quota consumida sem
data e leitura tolerante a spans com estrutura inválida/ciclos. Essas correções aguardam
novo push/CI. Docker continua indisponível no Mac de desenvolvimento.

## O que continua pendente

- Definir hospedagem, público e forma de acesso para a publicação F8C.
- Autenticação e autorização por usuário caso a ferramenta exponha dados particulares.
- Backend compartilhado de estado/quota para réplicas sem o mesmo disco local.
- Política automatizada de backup, remoção de bases e retenção de versões semânticas.
- Corrigir e reavaliar as divergências da [F5 real de 09/11](f5-2026-11-09.md), já executada.
- Resolver as condições dos dados do futebol ou escolher uma demo com dados sintéticos.

Esses itens não são apresentados como concluídos pela coordenação de arquivos locais.

Referências conferidas para Python 3.13, sem dependências novas:
[flock](https://docs.python.org/3.13/library/fcntl.html#fcntl.flock),
[temporários](https://docs.python.org/3.13/library/tempfile.html#tempfile.NamedTemporaryFile) e
[replace](https://docs.python.org/3.13/library/os.html#os.replace).

Perguntas para revisar os conceitos:

1. Por que um lock apenas em memória não coordena processos distintos?
2. Por que a quota precisa ser gravada antes de chamar o modelo?
3. Por que as métricas de logs com retenção não representam todo o histórico do projeto?
