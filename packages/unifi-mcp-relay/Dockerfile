FROM python:3.14-slim
WORKDIR /app

ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

RUN pip install --upgrade pip && pip install uv

# Copy workspace root and all member pyproject.toml files (uv needs them to resolve)
COPY pyproject.toml uv.lock ./
COPY packages/unifi-mcp-relay/pyproject.toml packages/unifi-mcp-relay/pyproject.toml
COPY packages/unifi-core/pyproject.toml packages/unifi-core/pyproject.toml
COPY packages/unifi-mcp-shared/pyproject.toml packages/unifi-mcp-shared/pyproject.toml
COPY apps/network/pyproject.toml apps/network/pyproject.toml
COPY apps/protect/pyproject.toml apps/protect/pyproject.toml
COPY apps/access/pyproject.toml apps/access/pyproject.toml

# Copy relay source and its workspace dependencies (unifi-mcp-shared, unifi-core)
# unifi-core is required because unifi-mcp-shared now depends on it (Phase 0 refactor)
COPY packages/unifi-mcp-relay/src packages/unifi-mcp-relay/src
COPY packages/unifi-mcp-shared/src packages/unifi-mcp-shared/src
COPY packages/unifi-core/src packages/unifi-core/src

RUN uv sync --frozen --no-dev --package unifi-mcp-relay

ENV PATH="/app/.venv/bin:$PATH"

CMD ["unifi-mcp-relay"]
