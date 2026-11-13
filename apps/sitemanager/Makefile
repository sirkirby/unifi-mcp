.PHONY: help venv install test test-cov lint format format-fix format-check manifest server-manifest \
       run run-lazy run-eager run-meta version build build-check build-test docker docker-run \
       clean pre-commit pre-release \
       deps-check deps-update info

UV_RUN = cd ../.. && uv run --package unifi-sitemanager-mcp
UV = cd ../.. && uv

help:
	@echo "UniFi Site Manager MCP — Development Commands"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make venv           Create virtual environment (requires uv)"
	@echo "  make install        Install dependencies with uv"
	@echo ""
	@echo "Development:"
	@echo "  make run            Run MCP server locally (lazy mode)"
	@echo "  make run-lazy       Run with lazy loading (default)"
	@echo "  make run-eager      Run with eager loading (all tools)"
	@echo "  make run-meta       Run with meta-only mode"
	@echo "  make manifest       Regenerate tool manifest"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test           Run tests"
	@echo "  make test-cov       Run tests with coverage"
	@echo "  make lint           Run linters"
	@echo "  make format         Format code"
	@echo "  make format-fix     Auto-fix lint issues"
	@echo "  make pre-commit     Format + manifests + lint + test"
	@echo ""
	@echo "Build & Release:"
	@echo "  make version        Show current version (from git tags)"
	@echo "  make build          Build package (wheel + sdist)"
	@echo "  make server-manifest  Regenerate server.json for MCP Registry"
	@echo "  make build-check    Build and verify version in package"
	@echo "  make docker         Build Docker image"
	@echo "  make docker-run     Run Docker container"
	@echo "  make pre-release    Full release preparation"
	@echo "  make clean          Clean build artifacts"
	@echo ""
	@echo "Dependencies:"
	@echo "  make deps-check     Check for outdated dependencies"
	@echo "  make deps-update    Update all dependencies"

# Setup
venv:
	@command -v uv >/dev/null 2>&1 || { echo "Error: uv is not installed. Visit https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@if [ ! -d "../../.venv" ]; then \
		echo "Creating virtual environment..."; \
		$(UV) sync; \
	else \
		echo "Virtual environment already exists."; \
	fi

install:
	$(UV) sync

# Development
run:
	$(UV_RUN) unifi-sitemanager-mcp

run-lazy:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=lazy uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp

run-eager:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp

run-meta:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=meta_only uv run --package unifi-sitemanager-mcp unifi-sitemanager-mcp

manifest:
	$(UV_RUN) python apps/sitemanager/scripts/generate_tool_manifest.py

server-manifest:
	$(UV_RUN) python scripts/generate_server_manifest.py --app sitemanager

# Testing
test:
	$(UV_RUN) pytest apps/sitemanager/tests -v

test-cov:
	$(UV_RUN) pytest apps/sitemanager/tests -v --cov=unifi_sitemanager_mcp --cov-report=html --cov-report=term-missing

# Code Quality
lint:
	cd ../.. && uv run ruff check apps/sitemanager/src apps/sitemanager/tests

format:
	cd ../.. && uv run ruff format apps/sitemanager/src apps/sitemanager/tests

format-fix:
	cd ../.. && uv run ruff check apps/sitemanager/src apps/sitemanager/tests --fix

format-check:
	cd ../.. && uv run ruff format --check apps/sitemanager/src apps/sitemanager/tests

# Version
version:
	@echo "Version Information"
	@echo ""
	@echo "Git tag:         $$(git -C ../.. describe --tags --always 2>/dev/null || echo 'no tags')"
	@echo "Package version: $$(cd ../.. && uv run python -c "from importlib.metadata import version; print(version('unifi-sitemanager-mcp'))" 2>/dev/null || echo 'not installed')"
	@echo ""
	@echo "Version is derived from git tags (e.g., sitemanager/v0.1.0 -> 0.1.0)"

# Build
build: manifest server-manifest
	cd ../.. && uv build --package unifi-sitemanager-mcp

build-check: clean manifest server-manifest
	@echo "Building and verifying version..."
	cd ../.. && uv build --package unifi-sitemanager-mcp
	@WHEEL=$$(ls ../../dist/unifi_sitemanager_mcp-*.whl | head -1); \
	WHEEL_VERSION=$$(basename $$WHEEL | sed -n 's/unifi_sitemanager_mcp-\([^-]*\)-.*/\1/p'); \
	echo "Wheel version: $$WHEEL_VERSION"

build-test: manifest
	cd ../.. && uv build --package unifi-sitemanager-mcp --out-dir /tmp/unifi-sitemanager-build-test

# Docker
docker:
	@if git -C ../.. describe --tags --match 'sitemanager/v*' HEAD >/dev/null 2>&1; then \
		RAW=$$(git -C ../.. describe --tags --match 'sitemanager/v*' HEAD); \
		BASE=$$(echo "$$RAW" | sed 's|^sitemanager/v||; s/-.*//'); \
	else \
		RAW=""; BASE="0.0.0"; \
	fi; \
	if [ -n "$$RAW" ] && ! echo "$$RAW" | grep -q '-'; then \
		VERSION="$$BASE"; \
	else \
		COMMITS=$$(git -C ../.. rev-list --count HEAD); \
		SHA=$$(git -C ../.. rev-parse --short HEAD); \
		VERSION="$${BASE}.dev$${COMMITS}+g$${SHA}"; \
	fi; \
	CORE_VERSION=$$(python3 ../../scripts/package_versions.py | sed -n 's/^core=//p'); \
	SHARED_VERSION=$$(python3 ../../scripts/package_versions.py | sed -n 's/^shared=//p'); \
	echo "Building Docker image with version: $$VERSION (core $$CORE_VERSION, shared $$SHARED_VERSION)"; \
	docker build --build-arg VERSION=$$VERSION --build-arg CORE_VERSION=$$CORE_VERSION \
		--build-arg SHARED_VERSION=$$SHARED_VERSION -t unifi-sitemanager-mcp:latest -f Dockerfile ../..

docker-run:
	docker run --rm --env-file ../../.env unifi-sitemanager-mcp:latest

# Cleanup
clean:
	rm -rf build/ dist/ *.egg-info
	rm -rf ../../dist/
	rm -rf .pytest_cache .coverage htmlcov/
	rm -f src/unifi_sitemanager_mcp/_version.py
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Pre-commit / Pre-release
pre-commit: format manifest server-manifest lint test

pre-release: clean manifest server-manifest format lint test build-check
	@echo ""
	@echo "Release preparation complete!"
	@echo ""
	@echo "Current version: $$(git -C ../.. describe --tags --always 2>/dev/null)"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Review changes: git status"
	@echo "  2. Commit any changes"
	@echo "  3. Push to main"
	@echo "  4. Tag: git tag sitemanager/v0.X.0"
	@echo "  5. Push tag: git push --tags"

# Dependency management
deps-check:
	@echo "Checking for outdated dependencies..."
	@$(UV) pip list --outdated 2>/dev/null || echo "Run 'uv sync' first"

deps-update:
	$(UV) lock --upgrade
	$(UV) sync
	@echo "Dependencies updated. Run 'make test' to verify."

# Info
info:
	@echo "Project Information"
	@echo ""
	@echo "Python: $$(python --version)"
	@echo "UV: $$(uv --version)"
	@echo ""
	@if [ -f src/unifi_sitemanager_mcp/tools_manifest.json ]; then \
		echo "Manifest: exists ($$(python -c "import json; print(json.load(open('src/unifi_sitemanager_mcp/tools_manifest.json'))['count'])" 2>/dev/null || echo '?') tools)"; \
	else \
		echo "Manifest: MISSING - run 'make manifest'"; \
	fi
