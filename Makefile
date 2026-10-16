.PHONY: test lint

test:
	uv run pytest

lint:
	uv run python -m compileall -q tomorrow tests
