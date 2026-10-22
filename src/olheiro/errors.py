"""Explica em português por que a consulta ao modelo falhou (cota, sobrecarga, prazo...).

Sem isso, um FallbackModel em que todos os modelos falham mostra só
"All models from FallbackModel failed (2 sub-exceptions)", escondendo o motivo de cada um.
"""

import re

from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelHTTPError,
    ModelRequestTimeout,
    UnexpectedModelBehavior,
)

HTTP_REASONS: dict[int, str] = {
    400: "requisição recusada pela API",
    401: "chave de API inválida",
    403: "chave sem permissão para este modelo",
    404: "modelo não encontrado (confira o nome no .env)",
    429: "limite de requisições excedido",
    500: "erro interno do provedor",
    503: "modelo sobrecarregado (alta demanda)",
}


def explain_model_failure(error: BaseException) -> str:
    """Uma linha por modelo que falhou, com o motivo e, quando houver, quando tentar de novo."""
    if isinstance(error, FallbackExceptionGroup):
        lines = [f"  • {explain_single(sub)}" for sub in error.exceptions]
        return "Todos os modelos falharam:\n" + "\n".join(lines)
    return explain_single(error)


def explain_single(error: BaseException) -> str:
    if isinstance(error, ModelRequestTimeout):
        return f"{error.model_name}: sem resposta dentro do prazo"
    if isinstance(error, ModelHTTPError):
        reason = HTTP_REASONS.get(error.status_code, "erro da API")
        detail = quota_detail(provider_message(error.body))
        return f"{error.model_name}: HTTP {error.status_code}, {reason}{detail}"
    if isinstance(error, UnexpectedModelBehavior):
        return f"o modelo esgotou as retentativas sem uma resposta válida ({error.message})"
    return f"{type(error).__name__}: {error}"


def provider_message(body: object) -> str:
    """Extrai a mensagem do corpo de erro do Google: {'error': {'message': ...}}."""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message", ""))
    return ""


def quota_detail(message: str) -> str:
    """Do texto do Google, pega o limite e quando liberar.

    Ex.: '... limit: 20, model: gemini-3.8-flash ... Please retry in 6h4m48.3s.'
    -> ' (limite: 20 requisições; tente de novo em 6h4m48s)'
    """
    limit = re.search(r"limit: (\d+)", message)
    retry = re.search(r"retry in ([\dhm]*\d+)(?:\.\d+)?s", message)
    parts = []
    if limit:
        parts.append(f"limite: {limit.group(1)} requisições")
    if retry:
        parts.append(f"tente de novo em {retry.group(1)}s")
    return f" ({'; '.join(parts)})" if parts else ""
