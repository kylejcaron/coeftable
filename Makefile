.PHONY: setup tests tests-all lint typecheck prek

setup:
	uv sync --all-extras

tests:
	uv run pytest

tests-all:
	uv run nox -s tests

lint:
	uv run nox -s lint

typecheck:
	uv run nox -s typecheck

prek:
	SKIP=no-commit-to-branch uv run prek run --all-files
