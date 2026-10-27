# Auditoria do Olheiro — 27/10/2026

Solicitação do autor: revisar o projeto completo e priorizar um agente flexível para arquivos
CSV e Parquet de diferentes domínios. Esta auditoria considera o checkout `845767d` como
origem e as mudanças da Fase 9A descritas abaixo.

## Diagnóstico

O núcleo já separava agente, SQL, gráficos, armazenamento e interfaces. A limitação principal
estava no onboarding: carga apenas de CSV, glossário obrigatório do futebol, estado único e
textos específicos na UI/MCP. Trocar somente `RAW_DATA_DIR` não era um fluxo confiável para
outro domínio. O cache reexecutava SQL, mas poderia exibir texto ou recusa de uma revisão
antiga dos dados. Identificadores vindos do catálogo ainda eram interpolados sem escapar
aspas internas, o que quebrava perfis de colunas legítimas.

Foi revisado o código em `src/olheiro`, testes, CLI/MCP, Streamlit, configuração, armazenamento,
tracing, evals, material de estudo, exemplos, Docker/Compose/proxy, workflow, documentação e
memória `CLAUDE.md`. Validação local e leitura da CI complementam a revisão; isso não é uma
certificação de segurança ou de acurácia do modelo.

## Estado das etapas anteriores

| Etapa | Situação e evidência |
|---|---|
| F0–F3: dados, loop, agente, SQL e segurança | Implementadas; testes offline e verificações reais históricas registradas no CLAUDE |
| F4: produto Streamlit, cache e dashboard | Implementada; adaptada nesta fase para seleção de bases |
| F5: avaliações | 39 casos e avaliadores offline prontos; comparação com modelos reais continua pendente |
| F6: observabilidade | Implementada; falta retenção e persistência para operação em escala |
| F7: MCP local | Implementado em stdio; consultas, perfis, contexto e perguntas; sem publicação remota |
| F8A: Docker e CI | Implementada e validada no runner Linux |
| F8B: demo local | Implementada; matriz pessoal/demo aprovada no último push |
| F8C: publicação | Pendente: hospedagem/acesso, condições de redistribuição dos dados e limites no provedor |
| F9A: bases locais flexíveis | Implementada nesta revisão, com CSV/Parquet e semântica opcional |

A CI do commit inicial `845767d` passou na
[execução 40502502772](https://github.com/joaovitor2410/AnalisIA/actions/runs/40502502772),
incluindo os contêineres pessoal e demo. A alteração atual precisa de nova CI após push
autorizado. Docker não está instalado neste Mac; não se atribui execução local a esse cenário.

## Achados tratados nesta entrega

| Prioridade | Achado | Mudança |
|---|---|---|
| Alta | Outro domínio exigia trocar manualmente caminhos e glossário | Manifesto por base; importação e seleção por UI/CLI; configuração comum para app, CLI e MCP |
| Alta | Respostas antigas podiam acompanhar dados diferentes | Cache por identidade/revisão e conferência da evidência; recusas antigas também invalidadas |
| Alta | Estado e aprovação poderiam acompanhar uma troca de base | Workspace/cache/dashboard por base; troca limpa histórico, pendência e cursor; quota permanece |
| Média | Entrada limitada a CSV | CSV e Parquet materializados em transação; arquivos misturados e extensões em maiúsculas |
| Média | Glossário completo obrigatório | Catálogo automático e semântica opcional/parcial; referências inválidas seguem sendo erro |
| Média | Nomes reais com aspas e caminhos com apóstrofos quebravam SQL interno | Escape de identificadores/literais e regressões com dados reais temporários |
| Média | Pasta vazia poderia apagar raw; colisões tinham erro pouco claro | Validação anterior à transação; falhas preservam o banco existente |
| Média | Tabela sem linhas impedia abrir uma base válida | Tabelas vazias aceitas no diagnóstico |
| Média | Valores de glossário podiam gerar contexto sem limite | Valores amostrados/truncados com aviso e prazo de consulta |
| Média | Upload Docker sem diretório gravável e barrado no proxy em 1 MB | `/state/datasets` no volume; limite HTTP 64 MB para o limite padrão de 50 MB do app |
| Baixa | Contrato/contexto ainda induziam domínio esportivo | Instruções, UI, MCP e descrição de gráfico generalizados; exemplo sintético de varejo |

A separação é por **base local**, não por conta de usuário. O agente continua sem acesso aos
leitores externos: a importação é uma ação explícita do usuário, anterior à conexão blindada.
SQL de leitura, prazo, limite de linhas e aprovação para `save_result` continuam valendo.

## O que falta e sequência proposta

1. **F9B — qualidade e semântica dos dados.** Prévia de importação com ajuste de tipos,
   cabeçalho, codificação e separador decimal; preservação explícita de identificadores;
   diagnóstico de nulos/duplicidades, sugestão verificável de chaves e relacionamentos;
   editor de descrições e regras. Catálogos grandes precisam de descoberta seletiva para
   não enviar todas as colunas em toda pergunta. Validar com bases de outros domínios.
2. **F5 complementar — evidência de acurácia.** Executar a comparação real já planejada,
   após faturamento autorizado; acrescentar benchmark de vendas/estoque e casos sem
   glossário. A suíte de 39 casos e a heurística de anos ainda são específicas do Brasileirão.
   Os testes offline da F9A verificam integração e proteção, não medem a capacidade do Gemini.
3. **F9C — análises com contexto de conversa.** Resolver perguntas de continuação sem misturar
   bases ou reutilizar aprovações. Hoje “e no mês anterior?” precisa repetir o contexto.
4. **Operação antes de acesso público amplo.** Backend persistente com transações entre
   processos, autenticação/escopo por usuário, quotas persistentes, retenção de logs e
   política de remoção/backup das bases importadas. `JsonFile` usa locks por objeto/thread;
   escritores em processos distintos ainda podem disputar os mesmos arquivos. Cada base
   selecionada mantém conexão em cache no processo: medir memória e definir ciclo de vida
   para grande quantidade de bases. A revisão do cache lê o banco inteiro na inicialização.
5. **F8C — publicar a demonstração.** Definir hospedagem e acesso, resolver as condições do
   dataset de futebol ou usar dados sintéticos com procedência clara; validar a nova imagem
   e configurar limites de cobrança. A demo pública segue sem upload nesta entrega.
6. **Evoluções opcionais.** Conectores PostgreSQL/MySQL/SQLite/Excel/APIs com ingestão fora
   do sandbox do agente; provedores além do Google; MCP HTTP com autenticação; migração
   DuckDB 2.x em cópias e com retorno planejado. Não são requisitos da F9A escolhida.

Permanecem também as limitações da evidência: heurísticas não provam toda afirmação textual,
50 linhas podem truncar resultados e inferência de tipos não substitui conhecimento do
negócio. Não há rodada de carga nem avaliação paga automática nesta varredura.

## Validação e reprodução

Baseline: **167 testes passaram** antes das mudanças. A suíte ampliada cobre domínios
distintos, formatos misturados, snapshots independentes, colisões, arquivos corrompidos,
rollback, ausência de glossário, semântica parcial, seleção pela configuração, troca na UI,
separação de estado, revisão do cache, nomes especiais e MCP sem chave. Os comandos e
o resultado final estão na memória da Fase 9A em `CLAUDE.md`.

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
```

Para experimentar outra base, siga [o guia de datasets](datasets.md). Não houve implantação
nem publicação de arquivos particulares. Bases importadas ficam ignoradas pelo Git.
