.PHONY: check test lint

check:
	uv run pytest
	npm run test:browser
	uv run python -m compileall -q tomorrow tests

test:
	uv run pytest

lint:
	uv run python -m compileall -q tomorrow tests
