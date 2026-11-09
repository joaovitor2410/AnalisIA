# Pendências para concluir a AnalisIA

Revisão de 09/11/2026. Escopo de conclusão: agente de análise tabular para uso pessoal e
demo pública com base fixa. Os itens abaixo distinguem a entrega desse escopo de evoluções
que só se tornam necessárias ao ampliar o público ou a arquitetura.

## Entrega da versão de portfólio

| Prioridade | Pendência | Entrega verificável |
|---|---|---|
| P0 | Corrigir divergências reveladas pela F5 | A medição dos 118 casos foi concluída: Flash 41/44 e Lite 39/44 em equivalência da evidência, com três/oito falhas por limite e uma proposta indevida de gravação no Lite. Priorizar esses casos, sem apagar a rodada original |
| P0 | Resolver os dados da demo pública | Condições de redistribuição confirmadas ou base sintética escolhida, com perguntas, respostas SQL e gráficos curados |
| P0 | Escolher e configurar a hospedagem | Configuração específica do destino, HTTPS, segredos, volume persistente e perfil de demo com leitura; opções em `hospedagem.md` |
| P0 | Validar os contêineres da entrega | Build, health, smoke de isolamento, UI pessoal/demo e escrita com UID 10001 aprovados em Linux; Docker indisponível neste Mac |
| P0, com Gemini público | Configurar consumo no provedor | Limites/quota e acompanhamento no projeto da API; a quota local conta tentativas e não garante um teto financeiro |
| P1 | Testar operação no destino | Reinício preserva quota/estado; carga com visitantes simultâneos mede memória, latência e interrupção de consultas |
| P1 | Automatizar backup e comprovar restauração | Cópia privada de `/state`, retenção definida e restauração executada com a aplicação parada |
| P1 | Preparar a entrega demonstrável | README coerente com a versão atual, roteiro/vídeo, exemplos de resposta correta, recusa e continuidade; versão/release identificada |

## Qualidade do agente e do código

| Prioridade | Pendência | Motivo e critério de conclusão |
|---|---|---|
| P1 | Avaliar conversas com modelos reais | A F5 atual avalia perguntas independentes; incluir manutenção de filtros, troca de período, ambiguidades e referências fora da janela |
| P1 | Reduzir afirmações fora da evidência final | Executar SQL e validar colunas do gráfico não comprova toda frase; revisar números, identificadores, posições e justificativas citadas |
| P1 | Reduzir exploração redundante e melhorar recusas | A F5 encontrou consultas ao catálogo já disponível e tentativa de usar `information_schema`, recusada pelo guard; escolher ferramentas conforme o tamanho do catálogo e medir recusas dentro do limite de seis requisições |
| P1 | Completar consumo de falhas na Operação | A F5 passou a guardar consumo recebido antes de falhar; `telemetry.error_record` do app/CLI/MCP ainda usa os padrões de consumo zero. Propagar o uso conhecido também nesses fluxos e distinguir consumo desconhecido |
| P1 | Avaliar a escolha dos gráficos | O validador verifica colunas e tipos, mas não mede se tipo, título, eixo e ordenação comunicam corretamente a pergunta; incluir esse critério no benchmark |
| P1 | Expandir casos de domínio e volume | Vendas/estoque têm dez perguntas cada; acrescentar dados maiores, datas, nulos, granularidade, chaves compostas e JOINs que multiplicam medidas; variar fixtures para detectar respostas/SQL com valores fixados indevidamente |
| P1, para distribuição por pacote | Tornar wheel/sdist autossuficientes | O build atual passa, mas não inclui `demo/`, `semantic/`, `data/raw/` nem `evals/`; decidir recursos empacotados/configuração externa e testar instalação limpa fora do checkout |
| P1 | Reproduzir e preservar avaliações | Fixar revisão de casos/dados/regras, limites, modelo e versão do código; manter rodadas iniciais e reavaliações separadas, sem confundir testes filtrados com cobertura completa |
| P2 | Medir o ciclo de vida das conexões | Recursos de bases ficam em `st.cache_resource`; medir crescimento ao alternar muitas bases e definir descarte quando necessário |
| P2 | Completar o ciclo de vida de bases e semântica | A importação existe; faltam fluxos de exclusão segura, limpeza de versões antigas e política de retenção dos arquivos |
| P2 | Rever estimativas de preço periodicamente | A tabela local de tokens não é a fatura; preços têm data de referência e mudanças previstas precisam ser conferidas |
| P2 | Medir acessibilidade e uso em telas pequenas | Complementar AppTest com revisão visual, navegação por teclado, legibilidade e exportações no navegador |

## Evoluções condicionadas ao produto

Estes itens não impedem concluir a demo pública com dados fixos e uma única instância.

| Quando ampliar o escopo | O que implementar |
|---|---|
| Hospedar dados particulares de usuários distintos | Autenticação, autorização e isolamento de bases, caches, dashboards e exportações por usuário |
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
