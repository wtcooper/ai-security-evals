FROM ghcr.io/astral-sh/uv:0.11.31 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY meridian ./meridian
COPY web ./web
RUN mkdir -p /data /connector-data /vault-data && chown -R 10001:10001 /data /connector-data /vault-data
USER 10001:10001
CMD ["uv", "run", "--no-sync", "uvicorn", "meridian.app:app", "--host", "0.0.0.0", "--port", "8080"]
