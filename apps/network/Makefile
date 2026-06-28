.PHONY: help venv install test test-cov test-async lint format format-fix format-check manifest server-manifest \
       run run-lazy run-eager run-meta version build build-check build-test docker docker-run \
       clean console console-debug console-proxy console-direct pre-commit pre-release \
       deps-check deps-update info run-with-all-permissions run-read-only

UV_RUN = cd ../.. && uv run --package unifi-network-mcp
UV = cd ../.. && uv

help:
	@echo "UniFi Network MCP — Development Commands"
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
	@echo "  make console        Start interactive dev console (auto-detect)"
	@echo "  make console-debug  Start dev console with debug logging"
	@echo "  make console-proxy  Force UniFi OS mode + debug logging"
	@echo "  make console-direct Force standalone mode + debug logging"
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
	@echo ""
	@echo "Permission Testing:"
	@echo "  make run-with-all-permissions  Run with all write permissions enabled"
	@echo "  make run-read-only             Run in read-only mode"

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
	$(UV_RUN) unifi-network-mcp

run-lazy:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=lazy uv run --package unifi-network-mcp unifi-network-mcp

run-eager:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-network-mcp unifi-network-mcp

run-meta:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=meta_only uv run --package unifi-network-mcp unifi-network-mcp

manifest:
	$(UV_RUN) python apps/network/scripts/generate_tool_manifest.py

server-manifest:
	$(UV_RUN) python scripts/generate_server_manifest.py --app network

# Testing
test:
	$(UV_RUN) pytest apps/network/tests -v

test-cov:
	$(UV_RUN) pytest apps/network/tests -v --cov=unifi_network_mcp --cov-report=html --cov-report=term-missing

test-async:
	$(UV_RUN) pytest apps/network/tests/test_async_jobs.py -v

# Code Quality
lint:
	cd ../.. && uv run ruff check apps/network/src apps/network/tests

format:
	cd ../.. && uv run ruff format apps/network/src apps/network/tests

format-fix:
	cd ../.. && uv run ruff check apps/network/src apps/network/tests --fix

format-check:
	cd ../.. && uv run ruff format --check apps/network/src apps/network/tests

# Version
version:
	@echo "Version Information"
	@echo ""
	@echo "Git tag:         $$(git -C ../.. describe --tags --always 2>/dev/null || echo 'no tags')"
	@echo "Package version: $$(cd ../.. && uv run python -c "from importlib.metadata import version; print(version('unifi-network-mcp'))" 2>/dev/null || echo 'not installed')"
	@echo ""
	@echo "Version is derived from git tags (e.g., network/v0.7.0 -> 0.7.0)"

# Build
build: manifest server-manifest
	cd ../.. && uv build --package unifi-network-mcp

build-check: clean manifest server-manifest
	@echo "Building and verifying version..."
	cd ../.. && uv build --package unifi-network-mcp
	@WHEEL=$$(ls ../../dist/unifi_network_mcp-*.whl | head -1); \
	WHEEL_VERSION=$$(basename $$WHEEL | sed -n 's/unifi_network_mcp-\([^-]*\)-.*/\1/p'); \
	echo "Wheel version: $$WHEEL_VERSION"

build-test: manifest
	cd ../.. && uv build --package unifi-network-mcp --out-dir /tmp/unifi-build-test

# Docker
docker:
	@if git -C ../.. describe --tags --match 'network/v*' HEAD >/dev/null 2>&1; then \
		RAW=$$(git -C ../.. describe --tags --match 'network/v*' HEAD); \
		BASE=$$(echo "$$RAW" | sed 's|^network/v||; s/-.*//'); \
	elif git -C ../.. describe --tags --match 'v*' HEAD >/dev/null 2>&1; then \
		RAW=$$(git -C ../.. describe --tags --match 'v*' HEAD); \
		BASE=$$(echo "$$RAW" | sed 's/^v//; s/-.*//'); \
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
	echo "Building Docker image with version: $$VERSION"; \
	docker build --build-arg VERSION=$$VERSION -t unifi-network-mcp:latest -f Dockerfile ../..

docker-run:
	docker run --rm --env-file ../../.env unifi-network-mcp:latest

# Cleanup
clean:
	rm -rf build/ dist/ *.egg-info
	rm -rf ../../dist/
	rm -rf .pytest_cache .coverage htmlcov/
	rm -f src/unifi_network_mcp/_version.py
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Dev Console
console:
	cd ../.. && UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-network-mcp python apps/network/devtools/dev_console.py

console-debug:
	cd ../.. && UNIFI_MCP_LOG_LEVEL=DEBUG UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-network-mcp python apps/network/devtools/dev_console.py

console-proxy:
	cd ../.. && UNIFI_CONTROLLER_TYPE=proxy UNIFI_MCP_LOG_LEVEL=DEBUG UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-network-mcp python apps/network/devtools/dev_console.py

console-direct:
	cd ../.. && UNIFI_CONTROLLER_TYPE=direct UNIFI_MCP_LOG_LEVEL=DEBUG UNIFI_TOOL_REGISTRATION_MODE=eager uv run --package unifi-network-mcp python apps/network/devtools/dev_console.py

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
	@echo "  4. Tag: git tag network/v0.X.0"
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
	@if [ -f src/unifi_network_mcp/tools_manifest.json ]; then \
		echo "Manifest: exists ($$(python -c "import json; print(json.load(open('src/unifi_network_mcp/tools_manifest.json'))['count'])" 2>/dev/null || echo '?') tools)"; \
	else \
		echo "Manifest: MISSING - run 'make manifest'"; \
	fi

# Permission testing helpers
run-with-all-permissions:
	cd ../.. && \
	UNIFI_PERMISSIONS_NETWORKS_CREATE=true \
	UNIFI_PERMISSIONS_NETWORKS_UPDATE=true \
	UNIFI_PERMISSIONS_WLANS_CREATE=true \
	UNIFI_PERMISSIONS_WLANS_UPDATE=true \
	UNIFI_PERMISSIONS_DEVICES_CREATE=true \
	UNIFI_PERMISSIONS_DEVICES_UPDATE=true \
	UNIFI_PERMISSIONS_CLIENTS_UPDATE=true \
	uv run --package unifi-network-mcp unifi-network-mcp

run-read-only:
	cd ../.. && \
	UNIFI_PERMISSIONS_FIREWALL_POLICIES_CREATE=false \
	UNIFI_PERMISSIONS_FIREWALL_POLICIES_UPDATE=false \
	UNIFI_PERMISSIONS_TRAFFIC_ROUTES_CREATE=false \
	UNIFI_PERMISSIONS_TRAFFIC_ROUTES_UPDATE=false \
	UNIFI_PERMISSIONS_PORT_FORWARDS_CREATE=false \
	UNIFI_PERMISSIONS_PORT_FORWARDS_UPDATE=false \
	UNIFI_PERMISSIONS_QOS_RULES_CREATE=false \
	UNIFI_PERMISSIONS_QOS_RULES_UPDATE=false \
	UNIFI_PERMISSIONS_VPN_CLIENTS_UPDATE=false \
	UNIFI_PERMISSIONS_VPN_SERVERS_UPDATE=false \
	uv run --package unifi-network-mcp unifi-network-mcp
