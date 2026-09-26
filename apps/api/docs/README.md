# unifi-api-server documentation

This directory contains the auto-generated reference docs and operational
guides for `unifi-api-server`. All artifacts here are checked-in and
drift-gated by CI — `openapi.json`, `openapi-reference.md`, and
`graphql-reference.md` are regenerated from code, never edited by hand.

## Reference

- **REST**
  - [`openapi.json`](../openapi.json) — OpenAPI 3.x spec; consumable by codegen tools (`openapi-generator`, `graphql-codegen`, `Postman`)
  - [`openapi-reference.md`](./openapi-reference.md) — human-readable REST reference, grouped by tag
  - **Live exploration**: `GET /v1/docs` serves Swagger UI; `GET /v1/openapi.json` serves the live spec
- **GraphQL**
  - [`../src/unifi_api/graphql/schema.graphql`](../src/unifi_api/graphql/schema.graphql) — SDL artifact
  - [`graphql-reference.md`](./graphql-reference.md) — human-readable reference, grouped by namespace
  - **Live exploration**: `GET /v1/graphql` serves GraphiQL playground; `POST /v1/graphql` accepts queries

## Operations

- [`graphql-versioning.md`](./graphql-versioning.md) — schema versioning policy (Phase 6)
- [`docker-compose.example.yml`](./docker-compose.example.yml) — deployment patterns (Phase 8 — added in PR4)

## Deployment

`unifi-api-server` is a standalone HTTP service. It runs **independently** of the MCP servers — both projects share the same manager packages from `unifi-core`, but neither depends on the other being running.

Common patterns:
- **Hobbyist with Claude Code**: run only the MCP servers; skip `unifi-api-server`.
- **App developer building on the API**: run only `unifi-api-server` via Docker; skip the MCP servers.
- **Tool builder who wants both**: run both as parallel containers (see `docker-compose.example.yml`).

## Distribution

`unifi-api-server` is published to:
- PyPI: `pip install unifi-api-server`
- GHCR: `docker pull ghcr.io/sirkirby/unifi-api-server:latest`
- GitHub Releases: built wheels attached to each `api/v*` tag

The distribution name `unifi-api-server` establishes `unifi-api-*` as the family namespace for the API and its future ecosystem (SDKs, CLIs).
