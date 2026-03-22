.PHONY: help test lint format manifest skill-references sync-skills check-skills-sync pre-commit core-test shared-test \
       relay-test docker-relay sync docker-build docker-up docker-down docker-logs

help:
	@echo "UniFi MCP Ecosystem — Top-Level Commands"
	@echo ""
	@echo "  make sync           Sync uv workspace (install/update all packages)"
	@echo "  make test           Run all tests (core + shared + all apps)"
	@echo "  make lint           Lint all apps"
	@echo "  make format         Format all apps"
	@echo "  make manifest       Regenerate tool manifests + skill references"
	@echo "  make skill-references  Update skill tool tables from manifests"
	@echo "  make pre-commit     Format + lint + test"
	@echo ""
	@echo "  make docker-build   Build all Docker images"
	@echo "  make docker-up      Start all servers (docker compose)"
	@echo "  make docker-down    Stop all servers"
	@echo "  make docker-logs    Tail logs from all servers"
	@echo ""
	@echo "  make core-test      Run unifi-core tests only"
	@echo "  make shared-test    Run unifi-mcp-shared tests only"

sync:
	uv sync --all-packages

core-test:
	uv run --package unifi-core pytest packages/unifi-core/tests -v

shared-test:
	uv run --package unifi-mcp-shared pytest packages/unifi-mcp-shared/tests -v

test: core-test shared-test relay-test
	$(MAKE) -C apps/network test
	$(MAKE) -C apps/protect test
	$(MAKE) -C apps/access test

lint:
	$(MAKE) -C apps/network lint
	$(MAKE) -C apps/protect lint
	$(MAKE) -C apps/access lint

format:
	$(MAKE) -C apps/network format
	$(MAKE) -C apps/protect format
	$(MAKE) -C apps/access format

manifest:
	$(MAKE) -C apps/network manifest
	$(MAKE) -C apps/protect manifest
	$(MAKE) -C apps/access manifest
	$(MAKE) sync-skills
	$(MAKE) skill-references

skill-references:
	python3 scripts/generate_skill_references.py

sync-skills:
	python3 skills/_build/sync_shared.py

check-skills-sync:
	python3 skills/_build/sync_shared.py --check

relay-test:
	uv run --package unifi-mcp-relay pytest packages/unifi-mcp-relay/tests -v

docker-relay:
	docker build -f packages/unifi-mcp-relay/Dockerfile -t unifi-mcp-relay .

pre-commit: format lint sync-skills test

docker-build:
	docker compose -f docker/docker-compose.yml build

docker-up:
	docker compose -f docker/docker-compose.yml up --build -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f
