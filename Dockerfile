ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest

FROM ${BASE_IMAGE} AS builder

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-editable --no-dev; \
    else \
        uv sync --no-editable --no-dev; \
    fi

FROM ${BASE_IMAGE}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    imagemagick \
    && if ! command -v magick >/dev/null 2>&1 && command -v convert >/dev/null 2>&1; then ln -s "$(command -v convert)" /usr/local/bin/magick; fi \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "printf '[BOOT] cwd=%s\\n' \"$PWD\"; printf '[BOOT] python=%s\\n' \"$(command -v python)\"; printf '[BOOT] uvicorn=%s\\n' \"$(command -v uvicorn)\"; python -c \"import os, sys; print(f'[BOOT] PYTHONPATH={os.getenv(\\\"PYTHONPATH\\\", \\\"\\\")}'); print(f'[BOOT] sys.path entries={len(sys.path)}'); import server.app; print('[BOOT] import server.app OK')\"; exec uvicorn server.app:app --host 0.0.0.0 --port 8000 --log-level info"]
