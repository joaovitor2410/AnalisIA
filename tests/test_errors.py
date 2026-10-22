"""Testes das mensagens de falha do modelo (corpo de erro igual ao 429 real do Gemini)."""

from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError

from olheiro.errors import explain_model_failure, quota_detail

QUOTA_MESSAGE = (
    "You exceeded your current quota, please check your plan and billing details.\n"
    "* Quota exceeded for metric: generativelanguage.googleapis.com/"
    "generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\n"
    "Please retry in 6h4m48.348302821s."
)


def http_error(status: int, model: str, message: str = "") -> ModelHTTPError:
    return ModelHTTPError(status, model, {"error": {"code": status, "message": message}})


def test_quota_detail_extracts_limit_and_retry_time() -> None:
    assert quota_detail(QUOTA_MESSAGE) == " (limite: 20 requisições; tente de novo em 6h4m48s)"


def test_quota_detail_handles_seconds_only_and_missing_info() -> None:
    assert quota_detail("Please retry in 31.5s.") == " (tente de novo em 31s)"
    assert quota_detail("sem detalhes") == ""


def test_explains_every_model_of_a_failed_fallback() -> None:
    group = FallbackExceptionGroup(
        "All models from FallbackModel failed",
        [
            http_error(429, "gemini-3.8-flash", QUOTA_MESSAGE),
            http_error(503, "gemini-3.5-flash", "high demand"),
        ],
    )

    lines = explain_model_failure(group).splitlines()

    assert lines[0] == "Todos os modelos falharam:"
    assert lines[1] == (
        "  • gemini-3.8-flash: HTTP 429, limite de requisições excedido "
        "(limite: 20 requisições; tente de novo em 6h4m48s)"
    )
    assert lines[2] == "  • gemini-3.5-flash: HTTP 503, modelo sobrecarregado (alta demanda)"


def test_explains_a_single_error() -> None:
    message = explain_model_failure(http_error(404, "gemini-9-flash"))
    assert message == "gemini-9-flash: HTTP 404, modelo não encontrado (confira o nome no .env)"
