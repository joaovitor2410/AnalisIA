"""Configurações do projeto, lidas de variáveis de ambiente e do arquivo .env.

Toda configuração passa por aqui: nenhum outro módulo lê os.environ diretamente.
Assim, trocar de modelo/provedor é só mudar o .env.
"""

from pathlib import Path

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
    google_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    duckdb_path: Path = Path("data/olheiro.duckdb")
    raw_data_dir: Path = Path("data/raw")

    @field_validator("duckdb_path", "raw_data_dir")
    @classmethod
    def _resolve_from_root(cls, path: Path) -> Path:
        """Caminhos relativos são relativos à raiz do projeto, não à pasta atual."""
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def provider(self) -> str:
        """Provedor do modelo, ex.: 'google' em 'google:gemini-3.8-flash'."""
        return self.olheiro_model.split(":", 1)[0]

    def api_key_for_model(self) -> SecretStr | None:
        """Devolve a chave do provedor configurado (ou None se faltar/desconhecido)."""
        field_name = PROVIDER_KEY_FIELDS.get(self.provider)
        return getattr(self, field_name) if field_name else None


def get_settings() -> Settings:
    """Lê as configurações atuais (.env + ambiente)."""
    return Settings()
