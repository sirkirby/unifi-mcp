.PHONY: help sync build check test lint format format-check format-fix manifest generate server-manifests skill-references \
       check-skill-references check-generated pre-commit ci core-test shared-test \
       relay-test worker-install worker-test worker-typecheck worker-build worker-check docker-relay \
       docker-build docker-up docker-down docker-logs

help:
	@echo "UniFi MCP Ecosystem — Top-Level Commands"
	@echo ""
	@echo "  make sync           Sync uv workspace (install/update all packages)"
	@echo "  make build          Build all deployable artifacts"
	@echo "  make check          Run full lint + drift + test checks"
	@echo "  make test           Run all tests (core + shared + all apps)"
	@echo "  make lint           Lint the full workspace"
	@echo "  make format         Format the full workspace"
	@echo "  make format-check   Check full-workspace formatting"
	@echo "  make format-fix     Auto-fix lint issues in the full workspace"
	@echo "  make generate       Regenerate committed generated artifacts"
	@echo "  make manifest       Regenerate tool manifests + skill references"
	@echo "  make check-generated  Check generated artifacts for drift"
	@echo "  make ci             Lint + generated drift checks + tests"
	@echo "  make server-manifests  Regenerate server.json for all apps (MCP Registry)"
	@echo "  make skill-references  Update skill tool tables from manifests"
	@echo "  make pre-commit     Format + generate + lint + test + drift checks"
	@echo ""
	@echo "  make docker-build   Build all Docker images"
	@echo "  make docker-up      Start all servers (docker compose)"
	@echo "  make docker-down    Stop all servers"
	@echo "  make docker-logs    Tail logs from all servers"
	@echo ""
	@echo "  make core-test      Run unifi-core tests only"
	@echo "  make shared-test    Run unifi-mcp-shared tests only"
	@echo "  make worker-build   Install worker deps + typecheck Worker app"
	@echo "  make worker-check   Run worker CLI tests + TypeScript checks"

sync: worker-install
	uv sync --all-packages

build: docker-build worker-build

check: format-check lint check-generated test worker-typecheck

core-test:
	uv run --package unifi-core pytest packages/unifi-core/tests -v

shared-test:
	uv run --package unifi-mcp-shared pytest packages/unifi-mcp-shared/tests -v

test: core-test shared-test relay-test worker-test
	$(MAKE) -C apps/network test
	$(MAKE) -C apps/protect test
	$(MAKE) -C apps/access test
	$(MAKE) -C apps/api test

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

format-fix:
	uv run ruff format .
	uv run ruff check . --fix

generate: manifest

manifest:
	$(MAKE) -C apps/network manifest
	$(MAKE) -C apps/protect manifest
	$(MAKE) -C apps/access manifest
	$(MAKE) skill-references
	$(MAKE) server-manifests

server-manifests:
	$(MAKE) -C apps/network server-manifest
	$(MAKE) -C apps/protect server-manifest
	$(MAKE) -C apps/access server-manifest

skill-references:
	python3 scripts/generate_skill_references.py

check-skill-references:
	python3 scripts/generate_skill_references.py --check

check-generated: check-skill-references

relay-test:
	uv run --package unifi-mcp-relay pytest packages/unifi-mcp-relay/tests -v

worker-install:
	npm ci --prefix apps/worker
	npm ci --prefix apps/worker/worker

worker-typecheck: worker-install
	npm run --prefix apps/worker/worker typecheck

worker-test: worker-install
	npm run --prefix apps/worker test:all

worker-build: worker-typecheck

worker-check: worker-typecheck worker-test

docker-relay:
	docker build -f packages/unifi-mcp-relay/Dockerfile -t unifi-mcp-relay .

pre-commit: format generate lint test check-generated worker-typecheck

ci: check

docker-build:
	docker compose -f docker/docker-compose.yml build

docker-up:
	docker compose -f docker/docker-compose.yml up --build -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f
