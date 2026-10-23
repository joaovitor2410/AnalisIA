"""Preço dos modelos, para estimar e medir custo (evals e página Operação).

No nível gratuito nada é cobrado: o valor é o "custo equivalente" no nível pago.
"""

# US$ por 1M tokens (entrada, saída com thinking), nível pago padrão. Conferido em 2026-10-22 em
# https://ai.google.dev/gemini-api/docs/pricing (3.8 e 3.6 Flash dobram a partir de 2027-01-01).
# O gemini-3.5-flash é servido como gemini-3.6-flash, por isso o 3.6 está na tabela.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Custo em US$; aceita 'google:gemini-3.8-flash' ou 'gemini-3.8-flash'. None se sem preço."""
    prices = PRICES_PER_MILLION.get(model.split(":")[-1])
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000
