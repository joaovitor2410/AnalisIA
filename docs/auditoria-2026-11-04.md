# Auditoria da AnalisIA — 04/11/2026

Varredura solicitada pelo autor sobre o commit `0e20330` (F9B), seguida da próxima fase
planejada: preparação das avaliações em outros domínios, F5 complementar.

## Estado encontrado

Checkout inicialmente limpo, `main` e referência local `origin/main` em `0e20330`.
**251 testes iniciais aprovados**, Ruff lint/formatação aprovados, mypy sem erros em 38
módulos. O diagnóstico abriu a base local, confirmou 450 classificações e 45 clubes,
glossário compatível e conexão do agente sem acesso externo. Não precisou reconstruir dados.

Foram revisados os caminhos de importação/prévia, qualidade, semântica, agente/validação,
cache, avaliações, CLI, testes, empacotamento e infraestrutura. Não foi identificado bloqueio
novo ao uso local nas verificações executadas. Essa conclusão não equivale a ausência de
bugs nem a uma medição da acurácia do modelo.

A documentação ainda dizia que a F9B aguardava push/CI. Consulta ao GitHub confirmou a
[execução 41637039752](https://github.com/joaovitor2410/AnalisIA/actions/runs/41637039752),
do SHA `0e203306d8a64c58b340522dc284359c560fab58`, concluída com sucesso em 03/11/2026.
README e memória foram atualizados. Docker continua indisponível neste Mac; a execução
remota anterior não valida automaticamente as alterações desta entrega.

## Ajustes no avaliador e avanço de fase

| Achado | Entrega |
|---|---|
| Avaliação CLI combinava casos de futebol com a base pessoal selecionada | Três suítes explícitas com fixtures, opções de leitura, glossário e banco temporário próprios |
| Ancoragem dispensava qualquer número entre 2003 e 2024 | Retirada da dispensa fixa; datas e códigos textuais presentes na evidência também são considerados |
| Cursor de cada caso não era fechado explicitamente | Fechamento garantido em sucesso e erro, com teste de regressão |
| Um caso de futebol avaliava apenas menção textual de zero títulos | Acrescentado gabarito SQL; todas as respostas esperadas têm evidência de referência |
| Casos e gabaritos não tinham validação completa antes da confirmação de custo | Checagem de nomes, metadata, SQL de leitura e limite de 50 linhas antes da rodada real |
| Novos domínios poderiam sobrescrever resultados de futebol | Diretório por suíte/modelo, identificação da suíte e hash dos arquivos usados |

Adicionados **20 casos** de vendas/estoque. Total: **59 casos**, dos quais **44 com gabarito
SQL**; os demais testam recusa ou proteção. O [guia de avaliações](avaliacoes.md) descreve
fixtures, comandos e limitações. A preparação offline está concluída; rodada real F5
continua pendente de faturamento e liberação. A próxima fase funcional é F9C.

## Evidência de validação final

- **270 testes aprovados** no checkout e **270 aprovados em cópia temporária sem `.env` e
  sem chaves dos provedores**, usando as dependências locais e o código da cópia isolada.
- Ruff lint/formatação aprovados; mypy sem erros em **39 módulos**.
- `olheiro-check` aprovado; validação offline das três suítes aprovada.
- Wheel e sdist construídos offline em `/tmp/analisia-audit-2026-11-04-dist`.
- `git diff --check` aprovado.

Comandos reproduzíveis:

```bash
uv run --locked olheiro-check
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --offline
uv run --locked olheiro-eval --suite brasileirao --validate-only
uv run --locked olheiro-eval --suite vendas --validate-only
uv run --locked olheiro-eval --suite estoque --validate-only
uv run --locked analisia
```

No sandbox desta revisão, o cache padrão do uv não permite escrita; os comandos foram
executados com `UV_CACHE_DIR=/tmp/analisia-uv-cache`, sem modificar a configuração do autor.
Aviso de depreciação do loop assíncrono do `pydantic_evals` apareceu em execução direcionada;
não impediu a aprovação dos testes.

Nenhuma chamada ao Gemini, dependência nova, migração de banco, publicação ou push nesta
entrega. Continuam pendentes a rodada real, F9C, hospedagem/condições dos dados na F8C e
as limitações operacionais já registradas (rotação de logs e coordenação de estado entre
processos/réplicas). Ao fim desta fase, manter o commit local e aguardar a revisão do autor,
conforme `CLAUDE.md`.
