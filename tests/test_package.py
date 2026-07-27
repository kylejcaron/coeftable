"""Packaging smoke tests."""

import coeftable


def test_version_is_exposed():
    assert isinstance(coeftable.__version__, str)
    assert coeftable.__version__


def test_runtime_dependencies_are_light():
    """matplotlib and plotnine must never be imported by the package."""
    import sys

    assert "matplotlib" not in sys.modules
    assert "plotnine" not in sys.modules
