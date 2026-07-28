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
from coeftable.theme import Theme, role_for

try:
    __version__ = version("coeftable")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = [
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


def __getattr__(name: str):
    """Intercept deprecated theme imports and issue warnings."""
    import warnings

    from coeftable.theme import COLORBLIND, DEFAULT, MONO

    _deprecated_themes = {"DEFAULT": DEFAULT, "COLORBLIND": COLORBLIND, "MONO": MONO}
    if name in _deprecated_themes:
        warnings.warn(
            f"Importing {name} from coeftable is deprecated. "
            f"Use 'from coeftable.theme import {name}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _deprecated_themes[name]
    raise AttributeError(f"module 'coeftable' has no attribute '{name}'")
