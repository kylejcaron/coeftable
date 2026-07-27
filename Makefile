.PHONY: setup tests prek lint

setup:
	uv sync --all-extras

tests:
	uv run pytest

prek:
	SKIP=no-commit-to-branch uv run prek run --all-files

lint:
	uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check
