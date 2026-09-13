.PHONY: setup tests tests-all lint typecheck prek review

setup:
	uv sync --all-extras
	uv run prek install

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

# Review the current branch as a pull request and post the verdict as a
# comment. Runs locally against the checked-out tree, so it uses this
# repo's .roborev.toml as it stands rather than the copy on the base branch.
# Usage: make review PR=56
review:
	@test -n "$(PR)" || { echo "usage: make review PR=<number>"; exit 2; }
	roborev ci review --comment \
	  --gh-repo $$(gh repo view --json nameWithOwner --jq .nameWithOwner) \
	  --pr $(PR) \
	  --ref $$(git merge-base origin/main HEAD)..$$(git rev-parse HEAD)
