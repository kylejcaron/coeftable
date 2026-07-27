"""Publication-quality summary tables for estimates with uncertainty."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("coeftable")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
