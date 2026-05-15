.PHONY: check build test typecheck install dev

# Install all dependencies
install:
	npm ci
	cd worker && npm ci

# Typecheck the worker TypeScript
typecheck:
	cd worker && npm run typecheck

# Run all tests (CLI + worker)
test:
	npm run test:all

# Run typecheck + all tests (mirrors CI)
check: typecheck test

# Install deps + typecheck (no deploy)
build: install typecheck

# Install CLI globally from local source for development
dev:
	npm install -g .
