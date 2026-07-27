"""Publication-quality summary tables for estimates with uncertainty."""

from importlib.metadata import PackageNotFoundError, version

from coeftable.format import CIStyle, Currency, Number, Percent
from coeftable.spec import (
    CoefTable,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    SpecError,
)
from coeftable.theme import COLORBLIND, DEFAULT, MONO, Theme, role_for

try:
    __version__ = version("coeftable")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = [
    "COLORBLIND",
    "DEFAULT",
    "MONO",
    "CIStyle",
    "CoefTable",
    "ColumnNotFoundError",
    "Currency",
    "Estimate",
    "Forest",
    "Number",
    "Passthrough",
    "Percent",
    "SpecError",
    "Theme",
    "__version__",
    "role_for",
]
