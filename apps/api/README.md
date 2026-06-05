# unifi-api-server

REST + GraphQL HTTP API for UniFi controllers — a standalone HTTP service for
desktop apps, web dashboards, Pi extensions, and any consumer that wants typed
read access to UniFi Network, Protect, and Access without speaking MCP.

## Quickstart

Two paths — pick the one that matches what you have. Both end with the admin
URL and the bootstrap key printed in your terminal so you can paste and sign
in. **No `UNIFI_API_DB_KEY` to generate, no `.env` file, no `docker exec`
incantations.** The disk-encryption key and the bootstrap admin API key are
both auto-generated on first boot and persisted inside the container's
named volume.

### A. Local clone (developing or testing changes)

Uses [`docker/docker-compose-api.yml`](../../docker/docker-compose-api.yml),
which builds from source and exposes the API on `localhost:8089`.

```bash
./scripts/start-api.sh
```

That's the whole thing. The script builds, starts, waits for first-boot
bootstrap + HTTP readiness, then prints the URL and the key. Paste the key
into <http://localhost:8089/admin/login> and you're in.

### B. Public image (just want to use it)

```bash
docker run -d --name unifi-api-server -p 8080:8080 \
  -v unifi-api-state:/var/lib/unifi-api \
  ghcr.io/sirkirby/unifi-api-server:latest && \
  until docker exec unifi-api-server \
    test -f /var/lib/unifi-api/bootstrap-admin-key 2>/dev/null; \
    do sleep 1; done && \
  echo "" && \
  echo "Admin UI:  http://localhost:8080/admin/login" && \
  echo "Admin key: $(docker exec unifi-api-server cat /var/lib/unifi-api/bootstrap-admin-key)"
```

Paste that whole block into a terminal. It starts the container, waits for
first-boot, and prints the URL and key. Open the URL, paste the key, sign in.

### What's next

Once you're signed in:

- **Register a controller** via the **Controllers** tab (or `POST /v1/controllers`).
- **Mint your own keys** via the **Keys** tab — pick `read`, `write`, or `admin`
  scope per consumer. Once you have a personal key saved, revoke
  `bootstrap-admin` and delete `/var/lib/unifi-api/bootstrap-admin-key`.
- **Explore the APIs:**
  - REST playground: `/v1/docs`
  - GraphQL playground: `/v1/graphql`
  - OpenAPI spec: `/v1/openapi.json`
  - Health: `/v1/health`

Current Network and Protect read surfaces include Network Traffic Flows
(`GET /v1/sites/{site_id}/traffic-flows`, `network.trafficFlows`) and Protect
Find Anything detection search (`GET /v1/sites/{site_id}/detection-search`,
`protect.searchDetections`).

First GraphQL query:

```bash
curl -s http://localhost:8089/v1/graphql \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ network { clients(controller: \"<id>\") { items { mac hostname } } } }"}'
```

### Production deployments

For shared / production deployments, set `UNIFI_API_DB_KEY` explicitly (e.g.
from a secret manager) so the encryption key lives outside the container
volume:

```bash
docker run -d \
  --name unifi-api-server \
  -p 8080:8080 \
  -e UNIFI_API_DB_KEY=$(openssl rand -hex 32) \
  -v unifi-api-state:/var/lib/unifi-api \
  ghcr.io/sirkirby/unifi-api-server:latest
```

When the env var is set, the file-backed fallback is skipped entirely.

### Reset / lost-key recovery

State (controllers, audit log, admin keys, both encryption and bootstrap key
files) lives in the `unifi-api-state` volume. `docker compose down` keeps it;
`docker compose down -v` wipes for a fresh bootstrap.

If you lose the bootstrap admin key file *and* never saved a personal admin
key, the simplest recovery is to wipe and re-bootstrap:

```bash
docker compose -f docker/docker-compose-api.yml down -v
docker compose -f docker/docker-compose-api.yml up --build -d
```

Note that wiping also drops registered controller credentials, since they
were encrypted with the now-discarded DB key.

## Architecture

`unifi-api-server` is a **standalone HTTP service**. It runs independently of the
MCP servers — both projects share the same manager packages from `unifi-core`,
but neither depends on the other being running. Choose based on the consumer:

- **Hobbyist with Claude Code:** run only the MCP servers; skip `unifi-api-server`.
- **App developer building on the API:** run only `unifi-api-server` via Docker.
- **Tool builder who wants both:** run both as parallel containers (see
  [`docs/docker-compose.example.yml`](docs/docker-compose.example.yml)).

The HTTP layer is FastAPI; GraphQL is Strawberry on top of the same projection
types REST uses, so consumer-facing field names are identical across the two
surfaces. Pagination is cursor-based on REST, slice-based on GraphQL.

## Distribution

`unifi-api-server` is published to:

- **PyPI:** `pip install unifi-api-server`
- **GHCR:** `docker pull ghcr.io/sirkirby/unifi-api-server:latest`
- **GitHub Releases:** wheels attached to each `api/v*` tag

The distribution name `unifi-api-server` establishes `unifi-api-*` as the family
namespace for the API and its future ecosystem (planned: `unifi-api-python-sdk`,
`unifi-api-ts-sdk`, `unifi-api-cli`). The import name remains `unifi_api`.

## Configuration

Two layers — environment variables override `config.yaml`. Defaults work for a
standard local install; override only what you need.

| Variable | Default | Purpose |
|---|---|---|
| `UNIFI_API_DB_KEY` | _auto-generated on first boot_ | Encrypts controller credentials at rest. Auto-generated and persisted to `<state_dir>/.db_encryption_key` if unset. **Not a login credential** — set explicitly in production via secret manager so the key lives outside the volume. |
| `UNIFI_API_STATE_DIR` | `/var/lib/unifi-api` | Where the SQLite state DB lives |
| `UNIFI_API_HTTP_HOST` | `127.0.0.1` | Bind address (set to `0.0.0.0` for non-localhost access) |
| `UNIFI_API_HTTP_PORT` | `8080` | Listen port |
| `UNIFI_API_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Per-controller credentials are stored encrypted in the state DB after the first
`POST /v1/controllers` call — no controller credentials in env vars.

## MFA / 2FA support

`unifi-api-server` connects to UniFi controllers using local-account credentials
(username + password + optional API token). It does **not** currently support
controllers that require MFA / 2FA on local accounts.

If your controller has MFA enabled, you'll need either:
- A separate local account with MFA disabled (recommended for service accounts)
- A long-lived API token (UniFi Network and Protect both support this on recent
  firmware)

This is the same constraint the MCP servers (`unifi-network-mcp`,
`unifi-protect-mcp`, `unifi-access-mcp`) inherit. See issue #150 for context.

## Documentation

- **Reference docs** are auto-generated and drift-gated. Browse them in-repo or
  via the live exploration UIs:
  - [REST OpenAPI spec (JSON)](openapi.json)
  - [REST reference (markdown)](docs/openapi-reference.md)
  - [GraphQL SDL](src/unifi_api/graphql/schema.graphql)
  - [GraphQL reference (markdown)](docs/graphql-reference.md)
  - **Live exploration:** Swagger UI at `/v1/docs`, GraphiQL at `/v1/graphql`
- [`docs/README.md`](docs/README.md) — index linking all artifacts plus
  deployment patterns
- [`docs/release-smoke-checklist.md`](docs/release-smoke-checklist.md) — manual
  release smoke checks
- [`docs/release-coverage.md`](docs/release-coverage.md) — coverage matrix
  (live smoke / fixture e2e / known gaps)
- [`docs/graphql-versioning.md`](docs/graphql-versioning.md) — schema
  versioning policy

## Development

The project uses an `uv` workspace covering `apps/api/` plus the shared
`packages/unifi-core/` and three MCP apps. Common development commands:

```bash
# Install everything once
uv sync --all-packages

# Run the unifi-api-server test suite (~700 tests)
uv run --package unifi-api-server pytest apps/api/tests

# Run live smoke against real controllers (requires .env)
uv run --package unifi-api-server python scripts/live_api_smoke.py --output /tmp/smoke.json

# Re-export drift-gated artifacts after schema changes
uv run --package unifi-api-server python -m unifi_api.graphql.docgen
```

The full project quality gate runs `make pre-commit` (lint + format + sync-skills
+ tests) at the repo root.

### Image-level smoke harness

`scripts/live_api_smoke.py` boots the API in-process via `ASGITransport`,
which means it cannot detect dep-closure bugs that only manifest in the
published Docker image (e.g. a missing runtime dependency that gets
masked by a `uv sync --all-packages` workspace). For that, use
`scripts/smoke-api-image.sh`:

```bash
# Optionally point at a real controller so authenticated paths get tested.
# Without these env vars the sweep still verifies first-boot, auth, and
# the capability_mismatch / api_key_required error paths.
export UNIFI_HOST=10.0.0.1
export UNIFI_USERNAME=svc
export UNIFI_PASSWORD=...
export UNIFI_API_TOKEN=...   # optional; required for DPI to return 200

./scripts/smoke-api-image.sh
```

The script wipes any existing state, rebuilds the image, brings it up,
registers a controller (when env vars are set), runs
`scripts/api_image_smoke.py` against every GET endpoint in the schema,
and fails on any 5xx or network error. Tears down on exit.

This is the harness that should run on every release tag.

## License

See the repository root [LICENSE](../../LICENSE) file. MIT License, © 2025 Chris Kirby.
