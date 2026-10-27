"""Configurações do projeto, lidas de variáveis de ambiente e do arquivo .env.

Toda configuração passa por aqui: nenhum outro módulo lê os.environ diretamente.
Assim, trocar de modelo/provedor é só mudar o .env.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/olheiro/config.py -> parents[2] é a raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Provedor (prefixo do nome do modelo) -> campo que guarda a chave dele
PROVIDER_KEY_FIELDS: dict[str, str] = {
    "google": "google_api_key",
    "anthropic": "anthropic_api_key",
}


class DatasetManifest(BaseModel):
    """Metadados de uma base local; os caminhos do estado são relativos ao manifesto."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=120)
    glossary: bool = False


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
    glossary_path: Path | None = Path("semantic/glossary.toml")
    answer_cache_path: Path = Path("data/answer_cache.json")
    dashboard_path: Path = Path("data/dashboard.json")
    datasets_dir: Path = Path("data/datasets")
    olheiro_dataset: Path | None = None
    olheiro_workspace_override: Path | None = None
    dataset_title: str = "Brasileirão Série A 2003–2024"
    olheiro_import_max_mb: int = Field(default=50, ge=1)
    # Perguntas que vão ao modelo por sessão do app (respostas do cache não contam).
    # Vazio = sem limite (uso local); numa demo pública, protege a cota do nível gratuito.
    olheiro_session_question_limit: int | None = Field(default=None, ge=0)
    # Demonstração do app: estado por visitante, leitura e exemplos curados.
    olheiro_demo_mode: bool = False
    # Chamadas ao modelo exigem opt-in, mesmo que o .env pessoal já contenha uma chave.
    olheiro_demo_model_enabled: bool = False
    olheiro_demo_total_question_limit: int = Field(default=10, ge=0)
    demo_examples_path: Path = Path("demo/examples.toml")
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
        "demo_examples_path",
        "datasets_dir",
        "olheiro_dataset",
        "olheiro_workspace_override",
    )
    @classmethod
    def _resolve_from_root(cls, path: Path | None) -> Path | None:
        """Caminhos relativos são relativos à raiz do projeto, não à pasta atual."""
        return path if path is None or path.is_absolute() else PROJECT_ROOT / path

    def for_dataset(self, path: Path) -> "Settings":
        """Aplica uma base sem carregar segredos do manifesto nem reutilizar estado pessoal."""
        if self.olheiro_demo_mode:
            raise ValueError("A demonstração usa uma base fixa e não permite trocar os dados.")
        path = path.resolve()
        with path.open("rb") as file:
            manifest = DatasetManifest.model_validate(tomllib.load(file))
        root = path.parent
        return self.model_copy(
            update={
                "olheiro_dataset": path,
                "dataset_title": manifest.title,
                "duckdb_path": root / "source.duckdb",
                "raw_data_dir": root / "raw",
                "glossary_path": root / "glossary.toml" if manifest.glossary else None,
                "workspace_path": self.olheiro_workspace_override or root / "workspace.duckdb",
                "answer_cache_path": root / "answer_cache.json",
                "dashboard_path": root / "dashboard.json",
                "exports_dir": root / "exports",
                "runs_path": root / "runs.jsonl",
                "traces_path": root / "traces.jsonl",
            }
        )

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

    @property
    def session_question_limit(self) -> int | None:
        """A demo limita a sessão a cinco perguntas quando não há limite explícito."""
        if self.olheiro_demo_mode and self.olheiro_session_question_limit is None:
            return 5
        return self.olheiro_session_question_limit


def get_settings() -> Settings:
    """Lê as configurações atuais (.env + ambiente)."""
    settings = Settings()
    return settings.for_dataset(settings.olheiro_dataset) if settings.olheiro_dataset else settings
