# Configuração da rodada F5 — 09/11/2026

118 casos planejados: 59 em cada modelo, nas três suítes versionadas.
Concorrência total: dois; um caso por modelo. Sem cache, fallback ou retry do SDK.
Limites por caso: seis requisições e doze chamadas de ferramenta.
Critério: primeira tentativa de cada caso, sem repetir até obter aprovação.
O diretório irmão `f5-2026-11-09-diagnostico` contém a amostra interrompida anterior.
O custo dessa amostra é parcial nos casos que falharam; não equivale à fatura.

SHA-256 dos arquivos executados:

- `src/olheiro/agent.py`: `f5648da703884065f4e5d81a209b9fb6826c9814f71de8b0c1c77b4ad17615e6`
- `src/olheiro/evaluation.py`: `96e2acba31ef36bd0ac762b469587fce77affbaab3bd4ebd66603ba4521f0771`
- `uv.lock`: `5beb097f0f9f02a0cdb1910497575f5701719c3700cba9ddb2d90d923cc8da59`
