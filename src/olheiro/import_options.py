"""Opções de leitura persistidas com a base e compartilhadas pela prévia e pela carga."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

type ImportType = Literal[
    "VARCHAR", "BIGINT", "DOUBLE", "DECIMAL(18,2)", "BOOLEAN", "DATE", "TIMESTAMP"
]
IMPORT_TYPES = ("VARCHAR", "BIGINT", "DOUBLE", "DECIMAL(18,2)", "BOOLEAN", "DATE", "TIMESTAMP")


class FileOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delimiter: str | None = None
    header: bool | None = None
    encoding: Literal["utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16"] = "utf-8"
    decimal_separator: Literal[".", ","] = "."
    all_varchar: bool = False
    types: dict[str, ImportType] = {}

    @field_validator("delimiter")
    @classmethod
    def check_delimiter(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 1 or value in "\r\n\x00"):
            raise ValueError("O separador deve ser um caractere, diferente de quebra de linha.")
        return value


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: dict[str, FileOptions] = {}

    def validate_files(self, files: list[Path]) -> None:
        unknown = self.files.keys() - {path.name for path in files}
        if unknown:
            raise ValueError(f"Opções para arquivos ausentes: {sorted(unknown)}")
        for path in files:
            options = self.files.get(path.name, FileOptions())
            if path.suffix.lower() == ".parquet" and options.model_dump(exclude={"types"}) != (
                FileOptions().model_dump(exclude={"types"})
            ):
                raise ValueError("Opções de CSV não se aplicam a arquivos Parquet.")


def load_import_options(path: Path | None) -> ImportOptions:
    return (
        ImportOptions.model_validate_json(path.read_text(encoding="utf-8"))
        if path
        else ImportOptions()
    )
