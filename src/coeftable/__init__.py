"""Publication-quality summary tables for estimates with uncertainty."""

from importlib.metadata import PackageNotFoundError, version

from coeftable.format import (
    CalendarStep,
    CIStyle,
    Currency,
    DateAxis,
    Number,
    Percent,
    TimeFormat,
)
from coeftable.spec import (
    CoefTable,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    Sparkline,
    SpecError,
)
from coeftable.theme import Theme, role_for

try:
    __version__ = version("coeftable")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = [
    "CIStyle",
    "CalendarStep",
    "CoefTable",
    "ColumnNotFoundError",
    "Currency",
    "DateAxis",
    "Estimate",
    "Forest",
    "Number",
    "Passthrough",
    "Percent",
    "Sparkline",
    "SpecError",
    "Theme",
    "TimeFormat",
    "__version__",
    "role_for",
]


def __getattr__(name: str):
    """Intercept deprecated theme imports and issue warnings.

    Only DEFAULT, COLORBLIND, and MONO ever lived at the top level before
    themes moved to `coeftable.theme`; BLUE and TEXTUAL never did, so they
    are not covered here -- import them from `coeftable.theme` directly.
    """
    import warnings

    from coeftable.theme import COLORBLIND, DEFAULT, MONO

    _deprecated_themes = {"DEFAULT": DEFAULT, "COLORBLIND": COLORBLIND, "MONO": MONO}
    if name in _deprecated_themes:
        if name == "DEFAULT":
            message = (
                "Importing DEFAULT from coeftable is deprecated. DEFAULT is now an "
                "alias for the TEXTUAL theme; 'from coeftable.theme import DEFAULT' "
                "will give you TEXTUAL, not the original blue theme. Use "
                "'from coeftable.theme import BLUE' to keep the prior appearance, "
                "or 'from coeftable.theme import TEXTUAL' to use it explicitly."
            )
        else:
            message = (
                f"Importing {name} from coeftable is deprecated. "
                f"Use 'from coeftable.theme import {name}' instead."
            )
        warnings.warn(message, DeprecationWarning, stacklevel=2)
        return _deprecated_themes[name]
    raise AttributeError(f"module 'coeftable' has no attribute '{name}'")
