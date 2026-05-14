.PHONY: test lint format format-fix

test:
	cd ../.. && uv run --package unifi-api-server pytest apps/api/tests -v

lint:
	cd ../.. && uv run ruff check apps/api/src apps/api/tests

format:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests

format-fix:
	cd ../.. && uv run ruff format apps/api/src apps/api/tests
	cd ../.. && uv run ruff check apps/api/src apps/api/tests --fix
