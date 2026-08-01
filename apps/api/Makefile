.PHONY: test lint format format-fix

test:
	# --all-packages first, mirroring .github/workflows/test-api.yml. These tests
	# build a registry from every product's tools_manifest.json, and
	# ManifestRegistry.load_from_apps() silently skips products that are not
	# installed. Without the sync the suite fails on imports or, worse, passes a
	# thinner registry than CI exercises.
	cd ../.. && uv sync --all-packages && uv run --package unifi-api-server pytest apps/api/tests -v

lint:
	cd ../.. && uv run ruff check apps/api/src apps/api/tests

format:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests

format-fix:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests
	cd ../.. && uv run ruff check apps/api/src apps/api/tests --fix
