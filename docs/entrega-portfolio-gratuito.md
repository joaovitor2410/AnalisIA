# Entrega para o portfólio gratuito — 09/11/2026

Pedido: avançar nas pendências locais e escolher hospedagem sem custo, proporcional a um portfólio.
O caminho preparado é o Streamlit Community Cloud com dados sintéticos e geração desabilitada.
O guia operacional está em [publicacao-gratuita.md](publicacao-gratuita.md).

## Implementado

- `portfolio_app.py`: entrada independente das configurações pessoais, com banco temporário,
  dez análises curadas e dashboard privado por sessão. Sem modelo ou chave na demo pública.
- Dados fictícios de seis meses, importação reproduzível e procedência/licença próprias.
- Recursos públicos incluídos no wheel/sdist, com sincronização por lista de inclusão e
  teste de instalação fora do checkout. O estado instalado fica no diretório de trabalho,
  em vez de tentar gravar dentro de `site-packages`.
- O agente retira ferramentas de descoberta quando o contexto já está completo; catálogos
  grandes/truncados preservam paginação e leitura adicional. A instrução também explicita
  a recusa de alterar raw, sem converter esse pedido em salvar uma cópia.
- App, CLI e MCP registram tokens/requisições recebidos antes de falhar. Registros distinguem
  consumo completo, parcial e desconhecido; retomadas de aprovação não duplicam o consumo anterior.
- KPIs recusam múltiplas linhas e gráficos recusam nomes de eixo ambíguos. Assim um KPI não
  esconde os demais empatados ou escolhe silenciosamente uma coluna repetida.
- Benchmark de conversa: cinco cenários/12 turnos, incluindo filtros, datas, códigos com
  zeros, referente ausente, limite dos dados e gráficos. Validação e testes roteirizados offline.
- Backup frio com hashes e permissões privadas, verificação e restauração para destino novo.
  Bancos em uso, WAL, links e corrupção são recusados. Operação local, sem serviço pago.
- CI ampliada para recursos, conversas e wheel instalado. Docker/CI remotos ainda dependem
  do push autorizado; a preparação não equivale a deploy remoto validado.

## Conversas: validar ou medir

```bash
uv run --locked olheiro-eval-chat --validate-only
# Opcional, depois de escolher chave/cota e autorizar o consumo:
uv run --locked olheiro-eval-chat --model google:gemini-3.8-flash
```

O segundo comando apresenta estimativa e pede confirmação. As saídas por turno incluem SQL,
tabela, gráfico, notas e consumo. Cada conversa inicia contexto próprio e roda sem cache/fallback.
Não houve nova chamada paga nesta entrega. Os testes com FunctionModel detectam perda de filtro;
não medem a capacidade linguística de um modelo real. Os resultados anteriores da F5 permanecem
preservados e não são apresentados como uma medição destas novas instruções/ferramentas.

## Backup pessoal opcional

Encerre app, CLI e MCP antes de copiar. O comando não é um snapshot de um aplicativo em execução.
Use pastas privadas fora de `data/` para o destino; não envie backups ao GitHub.

```bash
uv run --locked olheiro-backup create data ../AnalisIA-backups/copia-01
uv run --locked olheiro-backup verify ../AnalisIA-backups/copia-01
uv run --locked olheiro-backup restore ../AnalisIA-backups/copia-01 ../AnalisIA-restaurada
```

Destinos precisam ser novos. O comando não substitui arquivos existentes nem remove backups
antigos. A restauração foi testada em estado temporário, incluindo uma tabela DuckDB.
Para Docker, pare o Compose e copie `/state` conforme `deployment.md`; restaure com a instância
parada e permissões compatíveis com UID 10001. A demo pública descartável não precisa de backup.

## Validação final

- **345 testes passaram** no checkout e **345** em cópia temporária sem `.env`/chaves.
- Ruff lint/formatação e mypy nos 44 módulos aprovados; `git diff --check` sem problemas.
- Build offline de wheel/sdist e instalação do wheel fora do checkout aprovados.
- 24 arquivos públicos sincronizados; demos e três suítes funcionam a partir do pacote instalado.
- Cinco conversas/12 turnos validados sem modelo. Nenhuma chamada paga adicional.
- AppTest exercitou as dez análises do portfólio, o bloqueio de configuração pessoal e
  isolamento de dashboards entre visitantes. Backup/restauração passaram em banco temporário.
- A ferramenta de navegador estava indisponível: revisão visual em celular/teclado fica no piloto.
- Docker e publicação remota não foram executados; a CI ampliada aguarda push autorizado.

## Passos do autor

1. Executar a conferência final/liberar push e conectar GitHub ao Community Cloud.
2. Publicar usando `portfolio_app.py`/Python 3.13 e fazer os testes no endereço final/celular.
3. Escolher um vídeo curto da IA local ou apenas a demo guiada para a página de portfólio.
4. Se desejar medir o agente novamente, usar cota gratuita em rodadas pequenas ou autorizar
   uma comparação paga; não habilitar uma chave compartilhada na entrada pública gratuita.

Autenticação, réplicas e banco externo não são necessários para esta entrega de portfólio.
Melhorias de acurácia real, grandes volumes, retenção automática de bases pessoais e acessibilidade
no navegador permanecem no roteiro, sem impedir a demonstração guiada.
