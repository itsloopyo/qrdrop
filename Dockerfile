# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.16-python3.13-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13-alpine

LABEL org.opencontainers.image.title="qrdrop" \
      org.opencontainers.image.description="Instant file sharing from your terminal" \
      org.opencontainers.image.source="https://github.com/itsloopyo/qrdrop" \
      org.opencontainers.image.licenses="MIT"

RUN addgroup -g 1000 qrdrop && \
    adduser -u 1000 -G qrdrop -s /sbin/nologin -D qrdrop && \
    mkdir /data && chown qrdrop:qrdrop /data

COPY --from=builder /app/.venv /app/.venv
# DOCKER_CONTAINER pins qrdrop to the requested port instead of hunting for a
# free one: inside the container the port must stay 8000 (the published port,
# EXPOSE, and the healthcheck all assume it).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1

USER qrdrop
WORKDIR /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

ENTRYPOINT ["qrdrop", "--bind", "0.0.0.0", "--port", "8000"]
