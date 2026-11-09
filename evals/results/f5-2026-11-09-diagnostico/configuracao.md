# Amostra de diagnóstico — não é a comparação final

Rodada de 09/11/2026 com Gemini 3.8 Flash: **35 casos concluídos**, sendo dez de vendas,
dez de estoque e quinze de futebol. O caso seguinte, `mais_participacoes_empate`, foi
interrompido para reiniciar a matriz completa com as correções identificadas. Houve ainda
uma verificação inicial de faturamento, fora dos relatórios desta pasta.

As instruções do agente desta amostra são as do commit `c3b07af`. Foram acrescentados ao
avaliador a captura da saída completa e limites de seis requisições/doze ferramentas por
caso. Sem cache, fallback ou retentativas do SDK; execução serial.

O diagnóstico encontrou três problemas no avaliador, corrigidos antes da rodada final:

- Consumo já ocorrido era omitido quando a análise terminava em erro. Os três casos com
  `UsageLimitExceeded` nesta pasta exibem zero em requisições/tokens, mas **não foram gratuitos**.
- A ancoragem ignorava números em detalhes textuais do SQL, como `Central: 10, Loja: 2`.
- A ancoragem aceitava conversão por fator 100 sem exigir uma afirmação percentual.

As notas originais foram preservadas. Não compare esta amostra parcial com os 59 casos
de um modelo completo, nem a use como medição da versão final. O diretório irmão
`f5-2026-11-09` contém a comparação completa planejada e hashes do código executado.

O custo conhecido desta amostra é incompleto: exclui consumo omitido nas falhas e a
requisição interrompida. A verificação inicial usou três requisições e tem custo equivalente
de US$ 0,007656. Nenhum desses números substitui a fatura do provedor.
