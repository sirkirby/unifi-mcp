FROM python:3.14-slim

WORKDIR /app

# Version passed from CI/CD (used by hatch-vcs when git is unavailable)
ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

RUN pip install --upgrade pip \
 && pip install uv

# Copy workspace structure
COPY pyproject.toml uv.lock ./
COPY apps/access/pyproject.toml apps/access/pyproject.toml
COPY apps/access/README.md apps/access/README.md
COPY packages/unifi-core/pyproject.toml packages/unifi-core/pyproject.toml
COPY packages/unifi-mcp-shared/pyproject.toml packages/unifi-mcp-shared/pyproject.toml

# Copy source trees
COPY apps/access/src apps/access/src
COPY packages/unifi-core/src packages/unifi-core/src
COPY packages/unifi-mcp-shared/src packages/unifi-mcp-shared/src

# Install all packages using uv sync (respects lockfile for reproducible builds)
RUN uv sync --frozen --no-dev --package unifi-access-mcp

# Use the venv Python directly
ENV PATH="/app/.venv/bin:$PATH"

# Expose the MCP server port (for optional HTTP transport: streamable-http or SSE)
EXPOSE 3002

# Console-script entrypoint
CMD ["unifi-access-mcp"]
