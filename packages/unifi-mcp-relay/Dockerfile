FROM python:3.13-slim
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

# Copy relay source only
COPY packages/unifi-mcp-relay/src packages/unifi-mcp-relay/src

RUN uv sync --frozen --no-dev --package unifi-mcp-relay

ENV PATH="/app/.venv/bin:$PATH"

CMD ["unifi-mcp-relay"]
