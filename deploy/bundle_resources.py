"""Espelha somente fixtures públicas para o pacote; --check verifica sem alterar arquivos."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/olheiro/resources"
FILES = [
    "data/raw/brasileirao.csv",
    "data/raw/teams.csv",
    "data/raw/SOURCE.md",
    "semantic/glossary.toml",
    "demo/examples.toml",
    "demo/portfolio.toml",
    "evals/cases.yaml",
    "evals/vendas.yaml",
    "evals/estoque.yaml",
    "evals/conversations.toml",
]
DIRECTORIES = [
    "examples/datasets/retail",
    "examples/datasets/portfolio",
    "evals/fixtures/inventory",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sources = [ROOT / name for name in FILES]
    sources += [
        path
        for name in DIRECTORIES
        for path in (ROOT / name).iterdir()
        if path.suffix in {".csv", ".toml", ".json", ".md"}
    ]
    wanted = {path.relative_to(ROOT): path.read_bytes() for path in sources}
    present = {path.relative_to(TARGET): path for path in TARGET.rglob("*") if path.is_file()}
    extra = present.keys() - wanted.keys()
    if extra:
        raise SystemExit(f"Recursos extras não permitidos: {sorted(map(str, extra))}")
    stale = [
        name
        for name, data in wanted.items()
        if name not in present or present[name].read_bytes() != data
    ]
    if args.check and stale:
        raise SystemExit(
            f"Atualize os recursos: python deploy/bundle_resources.py ({len(stale)} arquivos)."
        )
    if not args.check:
        for name in stale:
            path = TARGET / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wanted[name])
    print(f"Recursos públicos: {len(wanted)} arquivos sincronizados.")


if __name__ == "__main__":
    main()
