.PHONY: setup tests tests-all tests-browser lint typecheck prek

setup:
	uv sync --extra dev
	uv run prek install

tests:
	uv run pytest

tests-all:
	uv run nox -s tests

tests-browser:
	uv sync --extra dev --extra browser
	uv run python -m playwright install chromium
	uv run pytest --no-cov tests/test_interactive.py

lint:
	uv run nox -s lint

typecheck:
	uv run nox -s typecheck

prek:
	SKIP=no-commit-to-branch uv run prek run --all-files
