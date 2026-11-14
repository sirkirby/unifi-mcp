FROM python:3.15-slim

WORKDIR /app

# Version passed from CI/CD (used by hatch-vcs when git is unavailable)
ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}
# unifi-core and unifi-mcp-shared carry their own release versions, not the image's
ARG CORE_VERSION=0.0.0.dev0
ARG SHARED_VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_UNIFI_CORE=${CORE_VERSION}
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_UNIFI_MCP_SHARED=${SHARED_VERSION}

RUN pip install --upgrade pip \
 && pip install uv

# Copy workspace structure
COPY pyproject.toml uv.lock ./
COPY apps/sitemanager/pyproject.toml apps/sitemanager/pyproject.toml
COPY apps/sitemanager/README.md apps/sitemanager/README.md
COPY packages/unifi-core/pyproject.toml packages/unifi-core/pyproject.toml
COPY packages/unifi-mcp-shared/pyproject.toml packages/unifi-mcp-shared/pyproject.toml

# Copy source trees
COPY apps/sitemanager/src apps/sitemanager/src
COPY packages/unifi-core/src packages/unifi-core/src
COPY packages/unifi-mcp-shared/src packages/unifi-mcp-shared/src

# Install all packages using uv sync (respects lockfile for reproducible builds)
RUN uv sync --frozen --no-dev --package unifi-sitemanager-mcp --extra otel

# Use the venv Python directly
ENV PATH="/app/.venv/bin:$PATH"

# Expose the MCP server port (for optional HTTP transport: streamable-http or SSE)
EXPOSE 3003

# Console-script entrypoint
CMD ["unifi-sitemanager-mcp"]
