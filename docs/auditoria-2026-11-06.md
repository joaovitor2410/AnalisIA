# Auditoria da AnalisIA — 06/11/2026

Solicitação: enviar a F8C.1, revisar o projeto e avançar se estivesse apto. O checkout estava
limpo, um commit à frente de `origin/main`. **309 testes**, Ruff lint/formatação e mypy
passaram antes do push. `0a66018` foi enviado conforme autorização; a
[CI 42211982307](https://github.com/joaovitor2410/AnalisIA/actions/runs/42211982307) passou.

Durante a revisão, o autor escolheu **manter a demo pública e receber opções de hospedagem
para escolher**. A comparação foi preparada em [hospedagem](hospedagem.md), como F8C.2.
Nenhuma contratação ou publicação foi feita.

## Escopo e achados

Revisados agente/SQL/ferramentas, bancos e ingestão CSV/Parquet, opções de importação,
semântica/versionamento, cache, conversa/aprovações, dashboard/gráficos, CLI/Streamlit/MCP,
armazenamento/quota, logs/traces, avaliações, empacotamento, Docker/Compose, CI e documentação.
Os testes passaram, mas a revisão manual confirmou falhas fora da cobertura inicial.

| Achado confirmado | Efeito | Correção |
|---|---|---|
| Quota com `day=null` e `used=10` autorizava nova tentativa | Um estado inconsistente era tratado como período novo | Validador recusa consumo sem período; arquivo é preservado e o modelo fica bloqueado |
| JSON válido com estrutura de span incompleta gerava `KeyError` | Uma linha ruim podia interromper Operação | Validação de campos/tipos/datas; ignora registros inválidos, mantém válidos e limita ciclos na hierarquia |
| Conversão 1↔100 era aceita em qualquer coluna numérica do avaliador | Faturamento 100 vezes maior ou menor podia receber nota de evidência correta | Conversão percentual só em índices de coluna declarados em `percentage_columns`; três casos percentuais atualizados |
| Normalização do avaliador apagava alfabetos não latinos | `東京` e `大阪` eram considerados equivalentes | Remove marcas de acento preservando os demais caracteres Unicode, sem apagar os nomes |

As falhas do avaliador afetavam o benchmark, não alteravam os valores SQL exibidos pelo
produto. As correções foram priorizadas antes de preparar a decisão de publicação.
As tolerâncias de arredondamento e a ancoragem continuam heurísticas; não garantem todas
as afirmações qualitativas ou relações entre unidades e texto. F5 real continua pendente.

## Validação final

- **317 testes aprovados**, também em cópia temporária sem `.env` e sem chaves de API.
- Ruff lint/formatação e mypy sem erros nos 40 módulos.
- Três suítes offline validadas: 59 casos, 44 gabaritos; nenhum modelo foi construído.
- Diagnóstico aprovado: 450 classificações, 45 clubes, glossário compatível e banco blindado.
  Usou workspace temporário, sem encerrar processos ou tocar no workspace pessoal.
- Smoke local de ingestão/qualidade/estado nos modos pessoal e demo aprovado.
- Build offline wheel/sdist e `git diff --check` aprovados.

Os testes novos cobrem os estados inconsistentes da quota, spans incompletos e datas
inválidas/mistas, hierarquia cíclica, valores monetários com escala errada, caracteres não
latinos e propagação da configuração percentual no fluxo completo de avaliação roteirizada.
Não houve chamada ao Gemini, mudança de dependência, migração de banco ou deploy.

Comandos reproduzíveis:

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked olheiro-eval --suite brasileirao --validate-only
uv run --locked olheiro-eval --suite vendas --validate-only
uv run --locked olheiro-eval --suite estoque --validate-only
uv run --locked olheiro-check
```

No sandbox, os comandos uv usaram `UV_CACHE_DIR=/tmp/analisia-uv-cache`. Fora dele,
o cache padrão do autor pode ser usado. Para diagnóstico simultâneo com o app, escolha
outro `WORKSPACE_PATH`/`OLHEIRO_WORKSPACE_OVERRIDE`, conforme o modo/base.
Docker não está instalado neste Mac: a CI do commit enviado valida a F8C.1 anterior;
estas correções precisam de sua própria CI após novo push liberado pelo autor.

## Avanço e pendências

Com os achados corrigidos, não ficou bloqueio novo nas verificações locais executadas.
Isso não equivale a ausência de bugs nem à validação de uma implantação ainda inexistente.
A F8C.2 entrega a comparação de VPS/Docker, Railway, Render e Community Cloud, com fontes
oficiais, referências de custo e diferenças de persistência/isolamento.

Próxima ação depende da escolha da hospedagem pelo autor. Também permanecem a definição
dos dados públicos, o benchmark real F5 e a validação do destino antes da publicação.
O commit desta entrega fica local para revisão/testes; o push solicitado enviou `0a66018`.
