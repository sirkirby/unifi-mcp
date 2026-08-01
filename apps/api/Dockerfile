# syntax=docker/dockerfile:1.7

# ============================================================================
# Builder stage — install dependencies into an isolated venv
# ============================================================================
FROM python:3.13-slim AS builder

WORKDIR /build

# Version passed from CI/CD (used by hatch-vcs when git is unavailable)
ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

RUN pip install --no-cache-dir uv

# Copy workspace root and member pyproject.toml files (uv needs them to resolve)
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/README.md apps/api/README.md
COPY packages/unifi-core/pyproject.toml packages/unifi-core/pyproject.toml
COPY packages/unifi-mcp-shared/pyproject.toml packages/unifi-mcp-shared/pyproject.toml
COPY packages/unifi-mcp-relay/pyproject.toml packages/unifi-mcp-relay/pyproject.toml
COPY apps/network/pyproject.toml apps/network/pyproject.toml
COPY apps/protect/pyproject.toml apps/protect/pyproject.toml
COPY apps/access/pyproject.toml apps/access/pyproject.toml

# Copy api source and its workspace dependencies (unifi-core, unifi-mcp-shared).
# Their source is REQUIRED — without it, hatch-vcs fails with
# FileNotFoundError writing _version.py.
COPY apps/api/src apps/api/src
COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/api/alembic apps/api/alembic
COPY packages/unifi-core/src packages/unifi-core/src
COPY packages/unifi-mcp-shared/src packages/unifi-mcp-shared/src

# Install all packages using uv sync (respects lockfile for reproducible builds)
RUN uv sync --frozen --no-dev --package unifi-api-server

# ============================================================================
# Runtime stage — slim image with just the venv + app source
# ============================================================================
FROM python:3.13-slim AS runtime

# curl is needed for the HEALTHCHECK; ca-certificates for HTTPS to controllers
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user with writable state dir
RUN useradd -m -u 1000 -d /home/unifi-api unifi-api \
 && mkdir -p /var/lib/unifi-api \
 && chown -R unifi-api:unifi-api /var/lib/unifi-api

# Copy the venv + workspace source from builder. The venv contains symlinks
# back into the workspace tree, so the source has to live at the same paths.
COPY --from=builder /build/.venv /build/.venv
COPY --from=builder /build/apps/api/src /build/apps/api/src
COPY --from=builder /build/apps/api/alembic /build/apps/api/alembic
COPY --from=builder /build/apps/api/alembic.ini /build/apps/api/alembic.ini
COPY --from=builder /build/packages/unifi-core/src /build/packages/unifi-core/src
COPY --from=builder /build/packages/unifi-mcp-shared/src /build/packages/unifi-mcp-shared/src

ENV PATH="/build/.venv/bin:$PATH"
ENV UNIFI_API_STATE_DIR=/var/lib/unifi-api

USER unifi-api
WORKDIR /home/unifi-api

VOLUME ["/var/lib/unifi-api"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -fsS http://localhost:8080/v1/health || exit 1

# Console-script entrypoint (renamed in Phase 8 PR4 from `unifi-api`).
#
# `migrate` is idempotent on subsequent runs (alembic stops at head, admin key
# only emitted when no key exists), so chaining migrate → serve makes the
# image self-bootstrapping for fresh deployments without breaking restarts.
CMD ["sh", "-c", "unifi-api-server migrate && exec unifi-api-server serve --host 0.0.0.0 --port 8080"]
