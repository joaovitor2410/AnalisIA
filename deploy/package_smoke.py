"""Verifica o wheel instalado fora do checkout, com dependências locais e sem API."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Execute uv build e mantenha somente o wheel atual em dist/.")
    with TemporaryDirectory(prefix="analisia-package-") as folder:
        root = Path(folder)
        target, work = root / "installed", root / "work"
        work.mkdir()
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--target",
                str(target),
                str(wheels[0]),
            ],
            check=True,
        )
        code = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import olheiro
assert Path(olheiro.__file__).is_relative_to(Path(sys.argv[1]))
from olheiro.config import Settings, RESOURCE_ROOT
from olheiro.launcher import ensure_database
from olheiro.db import connect_agent, scalar
from olheiro.demo import load_examples
from olheiro.eval_suites import SUITES, suite_database
from olheiro.evaluation import golden_results, load_cases
from olheiro.portfolio import portfolio_settings
from olheiro.conversation_evaluation import load_scenarios, validate_scenarios
from olheiro.visitor import create_workspace
from olheiro.ui.resources import visitor_resources
settings = Settings(_env_file=None, google_api_key=None, anthropic_api_key=None,
                    olheiro_dataset=None, olheiro_demo_mode=True)
assert settings.raw_data_dir.is_relative_to(RESOURCE_ROOT)
assert ensure_database(settings)
with connect_agent(settings.duckdb_path, None) as con:
    assert scalar(con, 'SELECT count(*) FROM raw.brasileirao') == 450
    assert len(load_examples(settings.demo_examples_path, con).questions()) == 6
for name, suite in SUITES.items():
    with suite_database(suite) as (con, glossary):
        assert golden_results(load_cases(suite.cases), con)
public = portfolio_settings()
with connect_agent(public.duckdb_path, None) as con:
    assert scalar(con, 'SELECT count(*) FROM raw.orders') == 120
    assert len(load_examples(public.demo_examples_path, con).questions()) == 10
assert public.google_api_key is None and not public.olheiro_demo_model_enabled
visitor = create_workspace(public)
try:
    active = visitor_resources(visitor, None)
    assert not active.settings.olheiro_demo_mode and active.model is None
    assert scalar(active.con, 'SELECT count(*) FROM raw.orders') == 120
    stock = visitor_resources(visitor, str(visitor.settings.datasets_dir / 'estoque/dataset.toml'))
    assert scalar(stock.con, "SELECT sum(quantity) FROM raw.stock WHERE sku='001'") == 12
finally:
    visitor.close()
validate_scenarios(load_scenarios())
print('Wheel instalado: recursos, carga, demo e três suítes offline OK.')
"""
        # O código instalado é inserido antes do pacote editável; a asserção comprova a origem.
        environment = dict(os.environ)
        from olheiro.config import Settings

        for field in Settings.model_fields:
            environment.pop(field.upper(), None)
        subprocess.run(
            [sys.executable, "-I", "-c", code, str(target)], cwd=work, env=environment, check=True
        )


if __name__ == "__main__":
    main()
