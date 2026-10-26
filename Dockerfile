# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.13.16-slim-trixie AS builder

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src/ src/
COPY semantic/ semantic/
COPY demo/ demo/
COPY data/raw/ data/raw/
COPY deploy/smoke.py deploy/smoke.py
# O pacote editável mantém a mesma raiz de recursos do checkout. O código fica somente
# leitura no runtime; apenas o ambiente já resolvido e a aplicação entram na imagem final.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev && \
    .venv/bin/python -c "from olheiro.config import get_settings; from olheiro.launcher import ensure_database; ensure_database(get_settings())"

FROM python:3.13.16-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    WORKSPACE_PATH=/state/workspace.duckdb \
    ANSWER_CACHE_PATH=/state/answer_cache.json \
    DASHBOARD_PATH=/state/dashboard.json \
    RUNS_PATH=/state/runs.jsonl \
    TRACES_PATH=/state/traces.jsonl \
    EXPORTS_DIR=/state/exports
WORKDIR /app
COPY --from=builder /app /app
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin olheiro && \
    mkdir /state && chown olheiro:olheiro /state
USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
    CMD ["python", "-c", "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).read() == b'ok'"]
ENTRYPOINT ["olheiro-app"]
CMD ["--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
