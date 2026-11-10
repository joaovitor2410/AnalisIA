# Pendências para concluir a AnalisIA

Atualização após a correção de 10/11/2026. Escopo: agente local completo e aplicação
de portfólio no Streamlit Community Cloud, com workspace isolado e chave de IA por sessão.
Análises prontas continuam disponíveis sem modelo. As restrições relatadas pelo autor foram
corrigidas em [correcao-workspace-2026-11-10.md](correcao-workspace-2026-11-10.md).
Guia: [publicacao-gratuita.md](publicacao-gratuita.md). Entrega: [relatório](entrega-portfolio-gratuito.md).

## Resolvido localmente

- Dados sintéticos com procedência própria, dez análises curadas e perfil gratuito separado.
- Entrada `portfolio_app.py`, com workspace completo por visitante, CSV/Parquet, seleção persistente
  de bases, chave Gemini da sessão e modo separado de análises prontas. Sem chave compartilhada.
- Recursos empacotados e instalação do wheel fora do checkout verificada; CI ampliada.
- Ferramentas de catálogo condicionais, registro de consumo parcial em erros e retomada sem duplicação.
- Proteções para KPI com várias linhas e eixos ambíguos.
- Benchmark de conversas com 12 turnos, validado offline e pronto para medição real opcional.
- CLI de backup/verificação/restauração, com testes de integridade e recuperação.
- Resultados da F5 preservados e guia de publicação/roteiro de demonstração documentados.

## Entrega da versão de portfólio

| Prioridade | Pendência | Entrega verificável |
|---|---|---|
| P0 | Corrigir divergências reveladas pela F5 | A medição dos 118 casos foi concluída: Flash 41/44 e Lite 39/44 em equivalência da evidência, com três/oito falhas por limite e uma proposta indevida de gravação no Lite. Priorizar esses casos, sem apagar a rodada original |
| P0, autor | Atualizar o site já publicado | Rodar os testes e liberar push; manter `portfolio_app.py` e Python 3.13 no Community Cloud e aguardar o redeploy; seguir `publicacao-gratuita.md` |
| P0, após push | Conferir CI | Qualidade/pacote e contêiner pessoal/demo precisam executar no runner; Docker indisponível neste Mac. A demo Community Cloud usa a entrada própria e não o Compose |
| P1, no destino | Testar o endereço publicado | Dois visitantes, upload, seleção, conexão de IA, pergunta, reinício, memória e navegação; dados da sessão são temporários e consumo da API pertence à chave de cada visitante |
| P1, autor | Escolher a apresentação no portfólio | Link do site; opcionalmente vídeo curto mostrando upload, pergunta e continuação |

## Qualidade do agente e do código

| Prioridade | Pendência | Motivo e critério de conclusão |
|---|---|---|
| P1, opcional com API | Medir novamente perguntas/conversas reais | A nova suíte já cobre filtros, períodos, códigos e ambiguidades offline. O teste real limitado de 10/11 foi autorizado/iniciado, mas a saída não foi recuperada e o resultado é inconclusivo. Nova chamada exige liberação; os resultados reais antigos não medem a versão nova |
| P1 | Reduzir afirmações fora da evidência final | Executar SQL e validar colunas do gráfico não comprova toda frase; revisar números, identificadores, posições e justificativas citadas |
| P1 | Medir o efeito das correções de ferramentas/recusa | Descoberta redundante já foi removida de catálogos completos e a instrução foi reforçada; falta comprovar o ganho com modelo real |
| P1 | Expandir a avaliação semântica dos gráficos | Há critérios de tipo nos cenários de conversa e proteções estruturais; título, unidade, ordenação e adequação visual ainda exigem avaliação mais ampla |
| P1 | Expandir casos de domínio e volume | Vendas/estoque têm dez perguntas cada; acrescentar dados maiores, datas, nulos, granularidade, chaves compostas e JOINs que multiplicam medidas; variar fixtures para detectar respostas/SQL com valores fixados indevidamente |
| P2 | Medir o ciclo de vida das conexões | No workspace hospedado, as conexões pertencem à sessão e são fechadas ao encerrar. Medir crescimento com muitas bases; o modo pessoal mantém recursos em `st.cache_resource` |
| P2 | Completar o ciclo de vida de bases e semântica | A importação existe; faltam fluxos de exclusão segura, limpeza de versões antigas e política de retenção dos arquivos |
| P2 | Rever estimativas de preço periodicamente | A tabela local de tokens não é a fatura; preços têm data de referência e mudanças previstas precisam ser conferidas |
| P2, autor no piloto | Medir acessibilidade e uso em telas pequenas | AppTest passou; conferir celular, teclado e exportações. A ferramenta de navegador estava indisponível nesta sessão |

## Evoluções condicionadas ao produto

Estes itens ampliam a versão de portfólio com dados temporários por sessão.

Backups pessoais estão implementados, mas agendamento/local de guarda e remoção de versões antigas
dependem de como o autor utiliza os dados. A demo gratuita não mantém dados pessoais persistentes.
Publicar uma imagem/pacote contendo o futebol ainda exige conferir as condições da fonte;
a nova demonstração usa somente os dados sintéticos.

| Quando ampliar o escopo | O que implementar |
|---|---|
| Manter contas e dados particulares persistentes | Autenticação, autorização por usuário e armazenamento durável; o workspace atual isola bases/cache/dashboard por sessão temporária |
| Executar réplicas com discos diferentes | Backend compartilhado de quota/estado e arquitetura compatível com a concorrência do DuckDB; `flock` local não resolve esse cenário |
| Retomar conversas após sair da aplicação | Persistência de sessões, consentimento, remoção e regras de retenção; hoje o contexto fica na sessão |
| Integrar interface própria ao portfólio | API HTTP e frontend se essa experiência for escolhida; hoje Streamlit/CLI/MCP atendem ao núcleo |
| Expor MCP pela rede | Transporte remoto, autenticação, autorização e limites; a implementação atual usa stdio local |
| Consultar sistemas externos | Conectores de fontes SQL/APIs e atualização controlada; CSV e Parquet são as fontes implementadas |
| Operar com maior escala de observabilidade | Backend OTLP com buscas, alertas e retenção por prazo; os JSONLs locais têm retenção por tamanho |

Não é necessário acrescentar outro framework de agentes, banco vetorial ou outro modelo
para encerrar a versão atual. Uma nova dependência deve resolver uma necessidade medida.

## Referências internas

- `avaliacoes.md`: reprodução da F5 e interpretação das métricas.
- `hospedagem.md` e `deployment.md`: opções de destino e limites do Compose local.
- `operacao.md`: quota, locks, logs, backup e limitações de uma instância.
- `../data/raw/SOURCE.md`: procedência e pendência de redistribuição do futebol.
- `conversa.md`: janela de contexto, isolamento e aprovações.
