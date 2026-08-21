FROM ghcr.io/astral-sh/uv:0.8.13 AS uv
FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
USER app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn ocr_service.app:app --host 0.0.0.0 --port ${PORT} --workers 1"]
