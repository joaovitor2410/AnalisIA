"""Configurações do projeto, lidas de variáveis de ambiente e do arquivo .env.

Toda configuração passa por aqui: nenhum outro módulo lê os.environ diretamente.
Assim, trocar de modelo/provedor é só mudar o .env.
"""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/olheiro/config.py -> parents[2] é a raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Provedor (prefixo do nome do modelo) -> campo que guarda a chave dele
PROVIDER_KEY_FIELDS: dict[str, str] = {
    "google": "google_api_key",
    "anthropic": "anthropic_api_key",
}


class Settings(BaseSettings):
    """Configurações tipadas. Cada campo corresponde a uma variável de ambiente
    com o mesmo nome em maiúsculas (ex.: olheiro_model <- OLHEIRO_MODEL)."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_ignore_empty=True,  # "GOOGLE_API_KEY=" vazio vira None, não ""
        extra="ignore",
    )

    olheiro_model: str = "google:gemini-3.8-flash"
    # Usado quando o principal falha na API (ex.: 503 de alta demanda). Vazio = sem fallback.
    olheiro_fallback_model: str | None = None
    google_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    duckdb_path: Path = Path("data/olheiro.duckdb")
    raw_data_dir: Path = Path("data/raw")
    exports_dir: Path = Path("data/exports")
    workspace_path: Path = Path("data/workspace.duckdb")
    glossary_path: Path = Path("semantic/glossary.toml")
    answer_cache_path: Path = Path("data/answer_cache.json")
    dashboard_path: Path = Path("data/dashboard.json")
    # Perguntas que vão ao modelo por sessão do app (respostas do cache não contam).
    # Vazio = sem limite (uso local); numa demo pública, protege a cota do nível gratuito.
    olheiro_session_question_limit: int | None = None
    # Observabilidade (F6). Traces OpenTelemetry: off, file (traces_path) ou otlp (backend).
    olheiro_tracing: Literal["off", "file", "otlp"] = "file"
    olheiro_otlp_endpoint: str = "http://localhost:4318/v1/traces"
    # Perguntas, respostas e argumentos das ferramentas nos traces. Desligar numa demo pública.
    olheiro_trace_content: bool = True
    traces_path: Path = Path("data/traces.jsonl")
    runs_path: Path = Path("data/runs.jsonl")

    @field_validator(
        "duckdb_path",
        "raw_data_dir",
        "exports_dir",
        "workspace_path",
        "glossary_path",
        "answer_cache_path",
        "dashboard_path",
        "traces_path",
        "runs_path",
    )
    @classmethod
    def _resolve_from_root(cls, path: Path) -> Path:
        """Caminhos relativos são relativos à raiz do projeto, não à pasta atual."""
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def provider(self) -> str:
        """Provedor do modelo, ex.: 'google' em 'google:gemini-3.8-flash'."""
        return self.olheiro_model.split(":", 1)[0]

    @property
    def model_name(self) -> str:
        """Nome do modelo sem o provedor, ex.: 'gemini-3.8-flash' (formato dos SDKs nativos)."""
        return self.olheiro_model.split(":", 1)[-1]

    def api_key_for_model(self) -> SecretStr | None:
        """Devolve a chave do provedor configurado (ou None se faltar/desconhecido)."""
        field_name = PROVIDER_KEY_FIELDS.get(self.provider)
        return getattr(self, field_name) if field_name else None


def get_settings() -> Settings:
    """Lê as configurações atuais (.env + ambiente)."""
    return Settings()
