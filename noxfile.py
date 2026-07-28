"""Test, lint, and typecheck sessions."""

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

PYTHON_VERSIONS = ["3.12", "3.13", "3.14"]


@nox.session(python=PYTHON_VERSIONS)
def tests(session):
    """Run the test suite against every supported Python version."""
    session.install("-e", ".[dev]")
    session.run("pytest")


@nox.session(python="3.12")
def lint(session):
    """Check formatting and lint rules."""
    session.install("ruff>=0.15")
    session.run("ruff", "check", "src", "tests")
    session.run("ruff", "format", "--check", "src", "tests")


@nox.session(python="3.12")
def typecheck(session):
    """Run the static type checker."""
    session.install("-e", ".[dev]")
    session.run("ty", "check", "src", "tests")
