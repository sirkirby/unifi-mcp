.PHONY: test lint format format-fix

PACKAGING_TESTS = \
	apps/api/tests/test_action_catalog_packaging.py \
	apps/api/tests/test_admin_template_packaging.py \
	apps/api/tests/test_migration_packaging.py

test:
	# Sync only the standalone API dependency closure. Product MCP apps are
	# build-time catalog inputs and must not be required by API runtime tests.
	# Packaging contracts build from the shared source tree, where hatch-vcs
	# writes _version.py. Keep those builds serial; the rest can use xdist.
	cd ../.. && uv sync --package unifi-api-server && \
		UV_NO_SYNC=1 uv run --package unifi-api-server pytest apps/api/tests \
			$(addprefix --ignore=,$(PACKAGING_TESTS)) -n auto --dist=worksteal -v && \
		UV_NO_SYNC=1 uv run --package unifi-api-server pytest $(PACKAGING_TESTS) -v

lint:
	cd ../.. && uv run ruff check apps/api/src apps/api/tests

format:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests

format-fix:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests
	cd ../.. && uv run ruff check apps/api/src apps/api/tests --fix
