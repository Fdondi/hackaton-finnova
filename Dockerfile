# OpenShift-ready: stateless, one port, config via env, runs as an arbitrary non-root UID.
FROM docker.io/library/node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
RUN npm run build

FROM docker.io/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv
WORKDIR /app
# Dependencies first (only pyproject + lock, so code or README edits don't invalidate this layer). The cache mount
# keeps downloaded wheels between builds, so even a lock change only fetches what's new.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra anthropic --extra openai --no-install-project
COPY README.md ./
COPY mygoal ./mygoal
COPY config ./config
COPY data ./data
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra anthropic --extra openai
COPY --from=web /web/dist ./web/dist
RUN chgrp -R 0 /app && chmod -R g=u /app
USER 1001
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["/app/.venv/bin/uvicorn", "mygoal.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
