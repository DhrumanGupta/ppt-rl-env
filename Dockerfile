ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest

FROM ${BASE_IMAGE} AS builder

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-install-project --no-dev; \
    else \
        uv sync --no-install-project --no-dev; \
    fi

COPY __init__.py agent_action_tools.py client.py inference.py inference_debug.py models.py README.md LICENSE openenv.yaml /app/
COPY server /app/server

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

COPY --from=builder /app/.venv /app/.venv
COPY __init__.py agent_action_tools.py client.py inference.py inference_debug.py models.py LICENSE /app/
COPY server /app/server
COPY README.md openenv.yaml /app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["uvicorn", "ppt_agent.server.app:app", "--host", "0.0.0.0", "--port", "7860", "--log-level", "info"]
