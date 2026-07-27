# coeftable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lightweight package that turns tidy frames of `(value, lower, upper)` estimates into publication-quality `great_tables` output, with optional inline-SVG forest plots, flexible grouping, and meaning-named colour semantics.

**Architecture:** A table is a list of column specs (`Estimate`, `Forest`, `Passthrough`) over a frame read through narwhals. `frame.py` resolves specs plus frame into rendered cell strings and layout metadata; `render.py` turns that into a `GT`. Pure leaf modules (`format`, `theme`, `svg`) have no frame or GT dependency and are unit-testable over scalars.

**Tech Stack:** Python 3.12+, uv, hatchling, great-tables, narwhals, pytest, ruff, ty, prek.

**Design spec:** `docs/superpowers/specs/2026-07-27-coeftable-design.md`

## Global Constraints

- Runtime dependencies are exactly `great-tables>=0.22` and `narwhals>=2.24`. Adding any other runtime dependency requires changing this plan.
- No matplotlib, plotnine, pandas or polars as runtime dependencies. Tests may use pandas and polars as dev dependencies.
- No pydantic. Spec objects are frozen dataclasses with `Literal`-typed fields.
- `requires-python = ">=3.12"`; `line-length = 99`; ruff `select = ["B", "D", "DOC", "E", "F", "I", "RUF", "S", "UP", "W"]`; numpy docstring convention.
- Colour roles are named by meaning (`favorable`, `unfavorable`, `inconclusive`, `neutral`) and never by colour, in code and in docs.
- Every module gets a numpy-style module docstring and every public symbol a numpy-style docstring; ruff `D`/`DOC` enforce this.
- All floats emitted into SVG coordinates are formatted `:.2f` to keep HTML small.
- Commit messages describe the change in product terms. Never mention the planning or review tooling.

---

### Task 1: Project scaffold, lint, type-check and CI

**Files:**
- Create: `pyproject.toml`, `.pre-commit-config.yaml`, `Makefile`, `.gitignore`, `README.md`, `LICENSE`
- Create: `.github/workflows/ci.yml`
- Create: `src/coeftable/__init__.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `coeftable` package exposing `__version__: str`; `make setup`, `make tests`, `make prek` targets that every later task uses.

- [ ] **Step 1: Write the failing test**

`tests/test_package.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_package.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable'`

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "coeftable"
version = "0.1.0"
description = "Publication-quality summary tables for estimates with uncertainty."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Kyle Caron" }]
keywords = ["statistics", "tables", "forest-plot", "confidence-interval", "great-tables"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering",
]
dependencies = [
    "great-tables>=0.22",
    "narwhals>=2.24",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pandas>=2.2",
    "polars>=1.0",
    "ruff>=0.15",
    "ty>=0.0.49",
    "prek>=0.4.5",
]

[project.urls]
Repository = "https://github.com/kylejcaron/coeftable"
Issues = "https://github.com/kylejcaron/coeftable/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/coeftable"]

[tool.uv]
default-groups = []

[tool.ruff]
extend-include = ["*.ipynb"]
line-length = 99
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.format]
docstring-code-format = true

[tool.ruff.lint]
select = ["B", "D", "DOC", "E", "F", "I", "RUF", "S", "UP", "W"]
ignore = ["RUF001", "RUF002", "RUF012"]

[tool.ruff.lint.pydocstyle]
convention = "numpy"

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = [
    "-v",
    "--strict-markers",
    "--strict-config",
    "--cov=coeftable",
    "--cov-report=term-missing",
    "--no-cov-on-fail",
    "--color=yes",
]

[tool.coverage.run]
source = ["src/coeftable"]
branch = true

[tool.coverage.report]
show_missing = true
exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]

[tool.ty.environment]
python-version = "3.12"
root = ["src"]
```

- [ ] **Step 4: Write `src/coeftable/__init__.py`**

```python
"""Publication-quality summary tables for estimates with uncertainty."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("coeftable")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
```

- [ ] **Step 5: Write `.pre-commit-config.yaml`**

```yaml
ci:
  autofix_prs: false

repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.6
    hooks:
      - id: ruff-check
        types_or: [python, pyi, jupyter]
        args: ["--fix", "--output-format=full"]
      - id: ruff-format
        types_or: [python, pyi, jupyter]
  - repo: https://github.com/astral-sh/ty-pre-commit
    rev: v0.0.49
    hooks:
      - id: ty
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: no-commit-to-branch
        args: [--branch, main]
        stages: [pre-commit, pre-merge-commit, pre-push, manual]
      - id: debug-statements
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-toml
      - id: check-yaml
      - id: check-added-large-files
```

- [ ] **Step 6: Write `Makefile`**

```make
.PHONY: setup tests prek lint

setup:
	uv sync --all-extras

tests:
	uv run pytest

prek:
	uv run prek run --all-files

lint:
	uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check
```

- [ ] **Step 7: Write `.github/workflows/ci.yml`**

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  prek:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v6
      - run: make setup
      - name: prek check
        uses: j178/prek-action@v1
        env:
          SKIP: no-commit-to-branch

  test:
    runs-on: ubuntu-latest
    needs: prek
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python-version }}
      - run: make setup
      - run: make tests
```

- [ ] **Step 8: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
dist/
build/
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
coverage.xml
.ipynb_checkpoints/
.DS_Store
```

- [ ] **Step 9: Write `README.md`**

A title, one-paragraph description matching the `pyproject` description, an `Installation` section with `uv add coeftable`, and a `Status` line reading `Early development.` The full usage examples land in Task 8.

- [ ] **Step 10: Write `LICENSE`**

Standard MIT license text, copyright `2026 Kyle Caron`.

- [ ] **Step 11: Run the full gate**

Run: `make setup && make tests && make prek`
Expected: `tests/test_package.py` both tests PASS; all pre-commit hooks pass.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: scaffold package with lint, type-check and CI"
```

---

### Task 2: Number and interval formatting

**Files:**
- Create: `src/coeftable/format.py`
- Test: `tests/test_format.py`

**Interfaces:**
- Consumes: `coeftable.theme.Theme` (Task 3). **Implement Task 3 before Task 2, or stub `Theme` locally and delete the stub.** The scheduler should run Task 3 first.
- Produces:
  - `Format: TypeAlias = Callable[[float], str]`
  - `compact_number(value: float) -> str`
  - `Number(decimals=2, compact=False, signed=False, prefix="", suffix="", thousands=True)` — callable frozen dataclass
  - `Percent(decimals=2, signed=True, suffix="%", thousands=False, scale=1.0)` — subclass of `Number`
  - `Currency(prefix="$")` — subclass of `Number`
  - `CIStyle(layout="stacked", brackets=("[", "]"), separator=", ", unbounded="∞")`
  - `is_missing(value: float | None) -> bool`
  - `render_interval(value, lower, upper, *, fmt, style, theme) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_format.py`:

```python
import math

import pytest

from coeftable.format import (
    CIStyle,
    Currency,
    Number,
    Percent,
    compact_number,
    is_missing,
    render_interval,
)
from coeftable.theme import DEFAULT


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2_400_000_000, "2.4B"), (2_300_000, "2.3M"), (1_400, "1.4k"), (12.34, "12.3"), (0.456, "0.46")],
)
def test_compact_number(value, expected):
    assert compact_number(value) == expected


def test_number_defaults_use_thousands_separator():
    assert Number()(1234.5) == "1,234.50"


def test_number_signed_prefixes_positive_only():
    assert Number(signed=True)(3.0) == "+3.00"
    assert Number(signed=True)(-3.0) == "-3.00"
    assert Number(signed=True)(0.0) == "0.00"


def test_negative_currency_puts_sign_before_symbol():
    assert Currency()(-5.0) == "-$5.00"


def test_percent_scale_converts_fractions():
    assert Percent(scale=100.0, decimals=1)(0.034) == "+3.4%"


def test_percent_defaults_treat_input_as_percentage_points():
    assert Percent(decimals=1)(3.4) == "+3.4%"


def test_is_missing_covers_none_and_nan():
    assert is_missing(None)
    assert is_missing(math.nan)
    assert not is_missing(0.0)


def test_render_interval_stacked_has_value_and_bracketed_ci():
    html = render_interval(3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "+3.4%" in html
    assert "[+1.2%, +5.7%]" in html
    assert "<br>" in html


def test_render_interval_inline_layout_has_no_break():
    html = render_interval(
        3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(layout="inline"), theme=DEFAULT
    )
    assert "<br>" not in html


def test_render_interval_value_only_omits_ci():
    html = render_interval(
        3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(layout="value_only"), theme=DEFAULT
    )
    assert "1.2" not in html


def test_unbounded_upper_uses_asymmetric_bracket():
    html = render_interval(2.0, 1.0, None, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "[1.0, ∞)" in html


def test_unbounded_lower_uses_asymmetric_bracket():
    html = render_interval(2.0, None, 3.0, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "(-∞, 3.0]" in html


def test_missing_value_renders_theme_na_text():
    assert render_interval(
        None, 1.0, 2.0, fmt=Number(), style=CIStyle(), theme=DEFAULT
    ) == DEFAULT.na_text


def test_absent_ci_renders_point_estimate_only():
    html = render_interval(2.0, None, None, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "2.0" in html
    assert "∞" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.format'`

- [ ] **Step 3: Write `src/coeftable/format.py`**

```python
"""Number and confidence-interval formatting."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias

from coeftable.theme import Theme

Format: TypeAlias = Callable[[float], str]
Layout: TypeAlias = Literal["stacked", "inline", "value_only"]


def is_missing(value: float | None) -> bool:
    """Return True when `value` is None or NaN.

    Parameters
    ----------
    value
        Candidate value.

    Returns
    -------
    bool
        True when the value carries no information.
    """
    return value is None or (isinstance(value, float) and math.isnan(value))


def compact_number(value: float) -> str:
    """Format a magnitude compactly, e.g. ``1.4k``, ``2.3M``, ``2.4B``.

    Parameters
    ----------
    value
        Value to format. The sign is preserved.

    Returns
    -------
    str
        Compact representation.
    """
    av = abs(value)
    if av >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if av >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if av >= 1_000:
        return f"{value / 1_000:.1f}k"
    if av >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"


@dataclass(frozen=True)
class Number:
    """Format a float as a number.

    Parameters
    ----------
    decimals
        Digits after the decimal point. Ignored when `compact` is True.
    compact
        Use ``1.4k`` / ``2.3M`` style abbreviation.
    signed
        Prefix positive values with ``+``. Negatives always carry ``-``.
    prefix
        Text placed after the sign and before the digits, e.g. ``$``.
    suffix
        Text placed after the digits, e.g. ``x``.
    thousands
        Insert thousands separators.
    """

    decimals: int = 2
    compact: bool = False
    signed: bool = False
    prefix: str = ""
    suffix: str = ""
    thousands: bool = True

    def __call__(self, value: float) -> str:
        """Format `value`.

        Parameters
        ----------
        value
            Value to format.

        Returns
        -------
        str
            Formatted value.
        """
        magnitude = abs(value)
        if self.compact:
            body = compact_number(magnitude)
        else:
            spec = f",.{self.decimals}f" if self.thousands else f".{self.decimals}f"
            body = format(magnitude, spec)
        if value < 0:
            sign = "-"
        elif self.signed and value > 0:
            sign = "+"
        else:
            sign = ""
        return f"{sign}{self.prefix}{body}{self.suffix}"


@dataclass(frozen=True)
class Percent(Number):
    """Format a float as a percentage.

    Parameters
    ----------
    scale
        Multiplier applied before formatting. Leave at ``1.0`` when the data is
        already in percentage points; use ``100.0`` when it is a fraction.
    """

    decimals: int = 2
    signed: bool = True
    suffix: str = "%"
    thousands: bool = False
    scale: float = 1.0

    def __call__(self, value: float) -> str:
        """Format `value` as a percentage.

        Parameters
        ----------
        value
            Value to format.

        Returns
        -------
        str
            Formatted percentage.
        """
        return super().__call__(value * self.scale)


@dataclass(frozen=True)
class Currency(Number):
    """Format a float as currency, with the symbol inside the sign."""

    prefix: str = "$"


@dataclass(frozen=True)
class CIStyle:
    """Control how a point estimate and its interval are assembled.

    Parameters
    ----------
    layout
        ``"stacked"`` puts the interval on a muted second line, ``"inline"``
        keeps it on one line, ``"value_only"`` drops it.
    brackets
        Bracket pair for a two-sided interval. An unbounded side always uses a
        parenthesis regardless of this setting.
    separator
        Text between the two bounds.
    unbounded
        Symbol used for an absent bound.
    """

    layout: Layout = "stacked"
    brackets: tuple[str, str] = ("[", "]")
    separator: str = ", "
    unbounded: str = "∞"


def render_interval(
    value: float | None,
    lower: float | None,
    upper: float | None,
    *,
    fmt: Format,
    style: CIStyle,
    theme: Theme,
) -> str:
    """Render an estimate and its interval as an HTML fragment.

    Parameters
    ----------
    value
        Point estimate. A missing value renders `theme.na_text`.
    lower, upper
        Interval bounds. A missing bound renders as unbounded on that side.
    fmt
        Callable applied to the estimate and each bound.
    style
        Assembly options.
    theme
        Supplies typography, muted colour and the missing-value text.

    Returns
    -------
    str
        HTML fragment safe to pass through `great_tables` markdown formatting.
    """
    if is_missing(value):
        return theme.na_text
    assert value is not None  # noqa: S101 - narrowed by is_missing
    point = (
        f'<span style="font-size:{theme.value_size};font-weight:600">{fmt(value)}</span>'
    )
    lower = None if is_missing(lower) else lower
    upper = None if is_missing(upper) else upper
    if style.layout == "value_only" or (lower is None and upper is None):
        return point
    open_bracket = "(" if lower is None else style.brackets[0]
    close_bracket = ")" if upper is None else style.brackets[1]
    low_text = f"-{style.unbounded}" if lower is None else fmt(lower)
    high_text = style.unbounded if upper is None else fmt(upper)
    interval = f"{open_bracket}{low_text}{style.separator}{high_text}{close_bracket}"
    if style.layout == "inline":
        return f'{point} <span style="color:{theme.muted}">{interval}</span>'
    return (
        f"{point}<br>"
        f'<span style="font-size:{theme.ci_size};color:{theme.muted}">{interval}</span>'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_format.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coeftable/format.py tests/test_format.py
git commit -m "feat: add number and confidence-interval formatting"
```

---

### Task 3: Theme and direction semantics

**Files:**
- Create: `src/coeftable/theme.py`
- Test: `tests/test_theme.py`

**Interfaces:**
- Consumes: nothing. This is a leaf module — implement it first.
- Produces:
  - `Role: TypeAlias = Literal["favorable", "unfavorable", "inconclusive", "neutral"]`
  - `Direction: TypeAlias = Literal["higher_is_better", "lower_is_better", "neutral"]`
  - `ColorRule: TypeAlias = Callable[[float | None, float | None, float | None, float], Role]`
  - `Theme` frozen dataclass with `.color(role) -> str`
  - `role_for(lower, upper, ref, direction) -> Role`
  - `DEFAULT`, `COLORBLIND`, `MONO` theme instances

- [ ] **Step 1: Write the failing test**

`tests/test_theme.py`:

```python
import dataclasses

import pytest

from coeftable.theme import COLORBLIND, DEFAULT, MONO, Theme, role_for


@pytest.mark.parametrize(
    ("lower", "upper", "direction", "expected"),
    [
        (1.0, 2.0, "higher_is_better", "favorable"),
        (1.0, 2.0, "lower_is_better", "unfavorable"),
        (-2.0, -1.0, "higher_is_better", "unfavorable"),
        (-2.0, -1.0, "lower_is_better", "favorable"),
        (-1.0, 1.0, "higher_is_better", "inconclusive"),
        (-1.0, 1.0, "lower_is_better", "inconclusive"),
        (1.0, 2.0, "neutral", "neutral"),
        (-1.0, 1.0, "neutral", "neutral"),
    ],
)
def test_role_for_respects_direction(lower, upper, direction, expected):
    assert role_for(lower, upper, 0.0, direction) == expected


def test_interval_touching_reference_is_inconclusive():
    assert role_for(0.0, 2.0, 0.0, "higher_is_better") == "inconclusive"
    assert role_for(-2.0, 0.0, 0.0, "higher_is_better") == "inconclusive"


def test_one_sided_intervals_resolve():
    assert role_for(1.0, None, 0.0, "higher_is_better") == "favorable"
    assert role_for(None, -1.0, 0.0, "higher_is_better") == "unfavorable"
    assert role_for(None, None, 0.0, "higher_is_better") == "inconclusive"


def test_reference_other_than_zero():
    assert role_for(1.1, 1.5, 1.0, "higher_is_better") == "favorable"
    assert role_for(0.5, 0.9, 1.0, "higher_is_better") == "unfavorable"


def test_color_returns_the_slot_for_each_role():
    for role in ("favorable", "unfavorable", "inconclusive", "neutral"):
        assert DEFAULT.color(role).startswith("#")


def test_mono_encodes_no_significance():
    colors = {MONO.color(r) for r in ("favorable", "unfavorable", "inconclusive", "neutral")}
    assert len(colors) == 1


def test_colorblind_separates_favorable_from_unfavorable():
    assert COLORBLIND.color("favorable") != COLORBLIND.color("unfavorable")


def test_theme_is_frozen_and_replaceable():
    custom = dataclasses.replace(DEFAULT, favorable="#123456")
    assert custom.color("favorable") == "#123456"
    assert DEFAULT.color("favorable") != "#123456"
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT.favorable = "#000000"


def test_theme_is_hashable():
    assert isinstance(hash(Theme()), int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_theme.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.theme'`

- [ ] **Step 3: Write `src/coeftable/theme.py`**

```python
"""Colour roles, direction semantics and table chrome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias

Role: TypeAlias = Literal["favorable", "unfavorable", "inconclusive", "neutral"]
Direction: TypeAlias = Literal["higher_is_better", "lower_is_better", "neutral"]
ColorRule: TypeAlias = Callable[[float | None, float | None, float | None, float], Role]


@dataclass(frozen=True)
class Theme:
    """Colour, typography and chrome slots for a table.

    Roles are named by meaning rather than by colour so that a palette can be
    swapped without the calling code implying a value judgement.

    Parameters
    ----------
    favorable, unfavorable, inconclusive, neutral
        Colours for the four semantic roles.
    header_bg, header_fg, column_label_bg
        Title, subtitle and column-label chrome.
    band
        Fill for alternating row-key blocks.
    surface
        Table background; also the colour of the estimate tick inside a bar.
    rule, axis, muted, text
        Divider, axis, secondary-text and body-text colours.
    value_size, ci_size, table_font_size
        CSS font sizes.
    na_text
        Text substituted for a missing estimate.
    """

    favorable: str = "#55A868"
    unfavorable: str = "#C44E52"
    inconclusive: str = "#8C8C8C"
    neutral: str = "#4C72B0"

    header_bg: str = "#4C72B0"
    header_fg: str = "#FFFFFF"
    column_label_bg: str = "#8FA9CE"
    band: str = "#F2F5FA"
    surface: str = "#FFFFFF"
    rule: str = "#C7C8CD"
    axis: str = "#72767E"
    muted: str = "#72767E"
    text: str = "#343538"

    value_size: str = "15px"
    ci_size: str = "11px"
    table_font_size: str = "16px"
    na_text: str = "—"

    def color(self, role: Role) -> str:
        """Return the colour registered for `role`.

        Parameters
        ----------
        role
            Semantic role.

        Returns
        -------
        str
            Hex colour string.
        """
        match role:
            case "favorable":
                return self.favorable
            case "unfavorable":
                return self.unfavorable
            case "inconclusive":
                return self.inconclusive
            case "neutral":
                return self.neutral


def role_for(
    lower: float | None,
    upper: float | None,
    ref: float,
    direction: Direction,
) -> Role:
    """Map an interval to a semantic role.

    An interval lying entirely on one side of `ref` is favorable or unfavorable
    according to `direction`; one that spans `ref`, or that is unbounded on the
    deciding side, is inconclusive. A `direction` of ``"neutral"`` always yields
    ``"neutral"``, so a table making no directional claim does not look like a
    table full of null results.

    Parameters
    ----------
    lower, upper
        Interval bounds. `None` means unbounded on that side.
    ref
        Reference value the interval is compared against.
    direction
        Which side of `ref` counts as favorable.

    Returns
    -------
    Role
        The resolved role.
    """
    if direction == "neutral":
        return "neutral"
    if lower is not None and lower > ref:
        return "favorable" if direction == "higher_is_better" else "unfavorable"
    if upper is not None and upper < ref:
        return "unfavorable" if direction == "higher_is_better" else "favorable"
    return "inconclusive"


DEFAULT = Theme()

COLORBLIND = Theme(
    favorable="#0072B2",
    unfavorable="#D55E00",
    inconclusive="#999999",
    neutral="#0072B2",
    header_bg="#0072B2",
    column_label_bg="#7FB8DC",
    band="#EEF5FA",
)

MONO = Theme(
    favorable="#4A4A4A",
    unfavorable="#4A4A4A",
    inconclusive="#4A4A4A",
    neutral="#4A4A4A",
    header_bg="#343538",
    column_label_bg="#72767E",
    band="#F4F4F4",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_theme.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coeftable/theme.py tests/test_theme.py
git commit -m "feat: add colour roles and direction semantics"
```

---

### Task 4: Inline SVG forest bars and axes

**Files:**
- Create: `src/coeftable/svg.py`
- Test: `tests/test_svg.py`

**Interfaces:**
- Consumes: `coeftable.theme.Theme` (Task 3), `coeftable.format.Format` (Task 2).
- Produces:
  - `nice_ticks(low, high, target=4) -> list[float]`
  - `forest_bar(estimate, lower, upper, *, domain, ref, color, theme, width=220, height=18, bar_height=9, pad=3) -> str`
  - `forest_axis(*, domain, ref, fmt, theme, width=220, height=22, pad=3, target_ticks=4) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_svg.py`:

```python
import re

from coeftable.format import Number
from coeftable.svg import forest_axis, forest_bar, nice_ticks
from coeftable.theme import DEFAULT


def test_nice_ticks_are_round_and_inside_domain():
    ticks = nice_ticks(0.0, 10.0)
    assert ticks
    assert all(0.0 <= t <= 10.0 for t in ticks)
    assert ticks == [round(t, 10) for t in ticks]


def test_nice_ticks_handles_degenerate_domain():
    assert nice_ticks(5.0, 5.0) == [5.0]
    assert nice_ticks(5.0, 1.0) == []


def test_nice_ticks_handles_negative_domain():
    ticks = nice_ticks(-10.0, -2.0)
    assert ticks
    assert all(-10.0 <= t <= -2.0 for t in ticks)


def test_forest_bar_is_well_formed_svg():
    svg = forest_bar(
        1.0, 0.5, 1.5, domain=(0.0, 2.0), ref=0.0, color="#55A868", theme=DEFAULT
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<rect" in svg
    assert "#55A868" in svg


def test_forest_bar_draws_reference_line_only_when_inside_domain():
    inside = forest_bar(1.0, 0.5, 1.5, domain=(-1.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    outside = forest_bar(1.0, 0.5, 1.5, domain=(0.5, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "stroke-dasharray" in inside
    assert "stroke-dasharray" not in outside


def test_forest_bar_caps_clipped_upper_bound():
    svg = forest_bar(1.0, 0.5, 99.0, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_treats_unbounded_upper_as_clipped():
    svg = forest_bar(1.0, 0.5, None, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_without_clipping_has_no_cap():
    svg = forest_bar(1.0, 0.5, 1.5, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" not in svg


def test_forest_bar_survives_zero_width_domain():
    svg = forest_bar(1.0, 1.0, 1.0, domain=(1.0, 1.0), ref=0.0, color="#000", theme=DEFAULT)
    assert svg.startswith("<svg")


def test_forest_bar_coordinates_are_two_decimals():
    svg = forest_bar(1.0, 0.5, 1.5, domain=(0.0, 3.0), ref=0.0, color="#000", theme=DEFAULT)
    for value in re.findall(r'x="([-\d.]+)"', svg):
        if "." in value:
            assert len(value.split(".")[1]) <= 2


def test_forest_axis_renders_tick_labels():
    svg = forest_axis(domain=(0.0, 10.0), ref=0.0, fmt=Number(decimals=0), theme=DEFAULT)
    assert "<text" in svg
    assert svg.startswith("<svg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_svg.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.svg'`

- [ ] **Step 3: Write `src/coeftable/svg.py`**

```python
"""Inline SVG emitters for forest bars and their shared axis."""

from __future__ import annotations

import math

from coeftable.format import Format, is_missing
from coeftable.theme import Theme

_TICK_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_ticks(low: float, high: float, target: int = 4) -> list[float]:
    """Return round tick positions spanning ``[low, high]``.

    Parameters
    ----------
    low, high
        Domain bounds.
    target
        Approximate number of ticks wanted.

    Returns
    -------
    list of float
        Tick positions, empty when the domain is invalid.
    """
    if not (math.isfinite(low) and math.isfinite(high)) or high < low:
        return []
    if high == low:
        return [low]
    raw = (high - low) / max(target, 1)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = next(
        (m * magnitude for m in _TICK_STEPS if raw <= m * magnitude), 10.0 * magnitude
    )
    start = math.ceil(low / step) * step
    count = int(math.floor((high - start) / step)) + 1
    return [round(start + i * step, 10) for i in range(max(count, 0))]


def _projector(domain: tuple[float, float], width: int, pad: int):
    low, high = domain
    span = high - low
    if span <= 0:
        span = 1.0
    inner = width - 2 * pad

    def project(value: float) -> float:
        return pad + (value - low) / span * inner

    return project


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto">'
        f"{body}</svg>"
    )


def forest_bar(
    estimate: float | None,
    lower: float | None,
    upper: float | None,
    *,
    domain: tuple[float, float],
    ref: float,
    color: str,
    theme: Theme,
    width: int = 220,
    height: int = 18,
    bar_height: int = 9,
    pad: int = 3,
) -> str:
    """Render one interval as an inline SVG bar.

    The bar spans the interval, a light tick marks the point estimate, and a
    dashed line marks `ref` when it falls inside `domain`. A bound outside the
    domain, including an unbounded one, draws to the edge with a triangular cap
    so that clipping is visible rather than silently misleading.

    Parameters
    ----------
    estimate
        Point estimate; the tick is omitted when missing or outside `domain`.
    lower, upper
        Interval bounds. `None` means unbounded on that side.
    domain
        Shared x-domain the bar is drawn against.
    ref
        Reference value for the dashed line.
    color
        Bar colour, resolved from a semantic role by the caller.
    theme
        Supplies axis and surface colours.
    width, height, bar_height, pad
        Geometry in pixels.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, pad)
    low_value = low if is_missing(lower) else float(lower)  # type: ignore[arg-type]
    high_value = high if is_missing(upper) else float(upper)  # type: ignore[arg-type]
    clipped_low = is_missing(lower) or low_value < low
    clipped_high = is_missing(upper) or high_value > high

    x0 = project(max(low_value, low))
    x1 = project(min(high_value, high))
    top = (height - bar_height) / 2
    middle = height / 2
    parts: list[str] = []

    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{height}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    parts.append(
        f'<rect x="{x0:.2f}" y="{top:.2f}" width="{max(x1 - x0, 0.75):.2f}" '
        f'height="{bar_height}" fill="{color}" fill-opacity="0.75" '
        f'stroke="{color}" stroke-width="0.75"/>'
    )

    if not is_missing(estimate) and low <= float(estimate) <= high:  # type: ignore[arg-type]
        tick_x = project(float(estimate))  # type: ignore[arg-type]
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{top:.2f}" x2="{tick_x:.2f}" '
            f'y2="{top + bar_height:.2f}" stroke="{theme.surface}" stroke-width="1.5"/>'
        )

    cap = bar_height * 0.6
    if clipped_high:
        tip = width - pad / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip - cap:.2f},{middle - cap:.2f} '
            f'{tip - cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )
    if clipped_low:
        tip = pad / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip + cap:.2f},{middle - cap:.2f} '
            f'{tip + cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )

    return _svg(width, height, "".join(parts))


def forest_axis(
    *,
    domain: tuple[float, float],
    ref: float,
    fmt: Format,
    theme: Theme,
    width: int = 220,
    height: int = 22,
    pad: int = 3,
    target_ticks: int = 4,
) -> str:
    """Render the shared x-axis for a set of forest bars.

    Parameters
    ----------
    domain
        Shared x-domain.
    ref
        Reference value for the dashed line.
    fmt
        Callable used to label each tick.
    theme
        Supplies the axis colour and label size.
    width, height, pad
        Geometry in pixels.
    target_ticks
        Approximate number of ticks wanted.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, pad)
    baseline = 4.0
    parts = [
        f'<line x1="{pad}" y1="{baseline:.2f}" x2="{width - pad}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{baseline:.2f}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )
    for tick in nice_ticks(low, high, target_ticks):
        tick_x = project(tick)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{baseline:.2f}" x2="{tick_x:.2f}" '
            f'y2="{baseline + 3:.2f}" stroke="{theme.axis}" stroke-width="0.75"/>'
        )
        parts.append(
            f'<text x="{tick_x:.2f}" y="{height - 2:.2f}" fill="{theme.axis}" '
            f'font-size="9" text-anchor="middle">{fmt(tick)}</text>'
        )
    return _svg(width, height, "".join(parts))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_svg.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coeftable/svg.py tests/test_svg.py
git commit -m "feat: add inline SVG forest bars and axis"
```

---

### Task 5: Column specs and the CoefTable builder

**Files:**
- Create: `src/coeftable/spec.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Consumes: `Format`, `Number`, `CIStyle` (Task 2); `Theme`, `DEFAULT`, `Direction`, `ColorRule` (Task 3).
- Produces:
  - `Estimate(label, value, ci=None, fmt=Number(), ci_style=CIStyle())`
  - `Forest(label, of, ref=0.0, scale="table", domain=None, width=220, show_axis=True, axis_fmt=None)`
  - `Passthrough(label, column)`
  - `Column: TypeAlias = Estimate | Forest | Passthrough`
  - `Scale: TypeAlias = Literal["table", "row_group", "split_column", "row"]`
  - `SpecError`, `ColumnNotFoundError` exceptions
  - `CoefTable` with attributes `data, rows, nest, groups, split_columns, columns, direction, color_rule, theme, title, subtitle, sort_rows` and methods `.estimate() .forest() .passthrough() .header() .with_theme() .with_direction() .gt() ._repr_html_()`
  - `validate_columns(columns) -> None` raising `SpecError`

`CoefTable` is a plain class, not a dataclass: the `estimate=` constructor argument and the `.estimate()` method would otherwise collide on the class namespace. It is immutable by convention — every chain method returns a new instance via `_with`.

`.gt()` raises `NotImplementedError` in this task and is completed in Task 7.

- [ ] **Step 1: Write the failing test**

`tests/test_spec.py`:

```python
import pytest

from coeftable.format import Number, Percent
from coeftable.spec import (
    CoefTable,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    SpecError,
    validate_columns,
)
from coeftable.theme import MONO

DATA = {"metric": ["a"], "mean": [1.0], "lb": [0.5], "ub": [1.5]}


def test_constructor_sugar_declares_one_estimate():
    table = CoefTable(DATA, rows="metric", estimate="mean", ci=("lb", "ub"))
    assert len(table.columns) == 1
    column = table.columns[0]
    assert isinstance(column, Estimate)
    assert column.label == "Estimate"
    assert column.value == "mean"
    assert column.ci == ("lb", "ub")


def test_chain_methods_append_in_call_order():
    table = (
        CoefTable(DATA, rows="metric")
        .estimate("A", "mean", ci=("lb", "ub"))
        .estimate("B", "mean", fmt=Percent())
        .forest("Plot", of="A")
        .passthrough("Note", "metric")
    )
    assert [c.label for c in table.columns] == ["A", "B", "Plot", "Note"]


def test_sugar_is_prepended_before_columns_argument():
    table = CoefTable(
        DATA, rows="metric", estimate="mean", ci=("lb", "ub"),
        columns=[Estimate("Later", "mean")],
    )
    assert [c.label for c in table.columns] == ["Estimate", "Later"]


def test_chain_does_not_mutate_the_original():
    base = CoefTable(DATA, rows="metric").estimate("A", "mean")
    extended = base.estimate("B", "mean")
    assert len(base.columns) == 1
    assert len(extended.columns) == 2
    assert base is not extended


def test_header_and_theme_and_direction_are_chainable():
    table = (
        CoefTable(DATA, rows="metric")
        .estimate("A", "mean")
        .header("Title", "Subtitle")
        .with_theme(MONO)
        .with_direction("lower_is_better")
    )
    assert table.title == "Title"
    assert table.subtitle == "Subtitle"
    assert table.theme is MONO
    assert table.direction == "lower_is_better"


def test_forest_referencing_unknown_estimate_is_a_spec_error():
    with pytest.raises(SpecError, match="Plot"):
        validate_columns((Estimate("A", "mean", ci=("lb", "ub")), Forest("Plot", of="Nope")))


def test_forest_bound_to_ci_less_estimate_is_a_spec_error():
    with pytest.raises(SpecError, match="confidence interval"):
        validate_columns((Estimate("A", "mean"), Forest("Plot", of="A")))


def test_duplicate_labels_are_a_spec_error():
    with pytest.raises(SpecError, match="duplicate"):
        validate_columns((Estimate("A", "mean"), Passthrough("A", "metric")))


def test_no_columns_is_a_spec_error():
    with pytest.raises(SpecError, match="no columns"):
        validate_columns(())


def test_valid_spec_passes_validation():
    validate_columns((Estimate("A", "mean", ci=("lb", "ub")), Forest("Plot", of="A")))


def test_specs_are_frozen_and_hashable():
    assert isinstance(hash(Estimate("A", "mean")), int)
    assert Estimate("A", "mean") == Estimate("A", "mean")


def test_estimate_default_format_is_number():
    assert isinstance(Estimate("A", "mean").fmt, Number)


def test_column_not_found_error_is_available():
    assert issubclass(ColumnNotFoundError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.spec'`

- [ ] **Step 3: Write `src/coeftable/spec.py`**

```python
"""Column specifications and the table builder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from coeftable.format import CIStyle, Format, Number
from coeftable.theme import DEFAULT, ColorRule, Direction, Theme

if TYPE_CHECKING:
    from great_tables import GT

Scale: TypeAlias = Literal["table", "row_group", "split_column", "row"]


class SpecError(ValueError):
    """Raised when a table specification is internally inconsistent."""


class ColumnNotFoundError(KeyError):
    """Raised when a specification names a column absent from the frame."""


@dataclass(frozen=True)
class Estimate:
    """A column rendering a point estimate and its interval.

    Parameters
    ----------
    label
        Column header, and the name a `Forest` binds to.
    value
        Frame column holding the point estimate.
    ci
        Frame columns holding the lower and upper bounds, or None.
    fmt
        Callable applied to the estimate and both bounds.
    ci_style
        Assembly options for the rendered cell.
    """

    label: str
    value: str
    ci: tuple[str, str] | None = None
    fmt: Format = field(default=Number())
    ci_style: CIStyle = field(default=CIStyle())


@dataclass(frozen=True)
class Forest:
    """A column rendering an inline SVG interval bar.

    Parameters
    ----------
    label
        Column header.
    of
        Label of the `Estimate` this plot visualises.
    ref
        Reference value for the dashed line and for role resolution.
    scale
        Which set of bars share an x-domain.
    domain
        Explicit domain, overriding `scale`.
    width
        Bar width in pixels.
    show_axis
        Emit an axis row for each distinct domain.
    axis_fmt
        Callable labelling axis ticks; defaults to the bound estimate's `fmt`.
    """

    label: str
    of: str
    ref: float = 0.0
    scale: Scale = "table"
    domain: tuple[float, float] | None = None
    width: int = 220
    show_axis: bool = True
    axis_fmt: Format | None = None


@dataclass(frozen=True)
class Passthrough:
    """A column rendering a frame column verbatim.

    Parameters
    ----------
    label
        Column header.
    column
        Frame column to display.
    """

    label: str
    column: str


Column: TypeAlias = Estimate | Forest | Passthrough


def validate_columns(columns: tuple[Column, ...]) -> None:
    """Check a column specification for internal consistency.

    Parameters
    ----------
    columns
        Declared columns, in display order.

    Raises
    ------
    SpecError
        When no columns are declared, labels collide, a `Forest` names an
        undeclared estimate, or a `Forest` is bound to a CI-less estimate.
    """
    if not columns:
        raise SpecError("Table has no columns; declare at least one.")

    seen: set[str] = set()
    for column in columns:
        if column.label in seen:
            raise SpecError(f"Table has duplicate column label {column.label!r}.")
        seen.add(column.label)

    estimates = {c.label: c for c in columns if isinstance(c, Estimate)}
    for column in columns:
        if not isinstance(column, Forest):
            continue
        target = estimates.get(column.of)
        if target is None:
            raise SpecError(
                f"Forest column {column.label!r} references estimate {column.of!r}, "
                f"which is not declared. Declared estimates: {sorted(estimates)}."
            )
        if target.ci is None:
            raise SpecError(
                f"Forest column {column.label!r} references estimate {column.of!r}, "
                "which has no confidence interval to plot."
            )


class CoefTable:
    """A specification for a summary table over a frame of estimates.

    Immutable by convention: every chain method returns a new instance.

    Parameters
    ----------
    data
        Any frame narwhals can read: pandas, polars, pyarrow, or a dict.
    rows
        Frame column whose values become the leading row label.
    nest
        Frame column stacked beneath each row key.
    groups
        Frame column driving row-group section headers.
    split_columns
        Frame column whose values repeat the declared columns side by side.
    columns
        Declared columns, in display order.
    estimate, ci
        Sugar declaring a single `Estimate` labelled ``"Estimate"``, prepended
        before any `columns` entries.
    direction
        Which side of a reference counts as favorable, table-wide or per row key.
    color_rule
        Callable overriding role resolution entirely.
    theme
        Colour and typography.
    title, subtitle
        Header text.
    sort_rows
        Sort row keys lexically instead of by first appearance.
    """

    def __init__(
        self,
        data: Any,
        *,
        rows: str | None = None,
        nest: str | None = None,
        groups: str | None = None,
        split_columns: str | None = None,
        columns: Iterable[Column] = (),
        estimate: str | None = None,
        ci: tuple[str, str] | None = None,
        direction: Direction | Mapping[str, Direction] = "higher_is_better",
        color_rule: ColorRule | None = None,
        theme: Theme = DEFAULT,
        title: str = "",
        subtitle: str = "",
        sort_rows: bool = False,
    ) -> None:
        declared = tuple(columns)
        if estimate is not None:
            declared = (Estimate("Estimate", estimate, ci=ci), *declared)
        self.data = data
        self.rows = rows
        self.nest = nest
        self.groups = groups
        self.split_columns = split_columns
        self.columns = declared
        self.direction = direction
        self.color_rule = color_rule
        self.theme = theme
        self.title = title
        self.subtitle = subtitle
        self.sort_rows = sort_rows

    def _with(self, **changes: Any) -> CoefTable:
        settings: dict[str, Any] = {
            "rows": self.rows,
            "nest": self.nest,
            "groups": self.groups,
            "split_columns": self.split_columns,
            "columns": self.columns,
            "direction": self.direction,
            "color_rule": self.color_rule,
            "theme": self.theme,
            "title": self.title,
            "subtitle": self.subtitle,
            "sort_rows": self.sort_rows,
        }
        settings.update(changes)
        return CoefTable(self.data, **settings)

    def _add(self, column: Column) -> CoefTable:
        return self._with(columns=(*self.columns, column))

    def estimate(
        self,
        label: str,
        value: str,
        *,
        ci: tuple[str, str] | None = None,
        fmt: Format = Number(),
        ci_style: CIStyle = CIStyle(),
    ) -> CoefTable:
        """Append an estimate column.

        Parameters
        ----------
        label
            Column header, and the name a `Forest` binds to.
        value
            Frame column holding the point estimate.
        ci
            Frame columns holding the lower and upper bounds.
        fmt
            Callable applied to the estimate and both bounds.
        ci_style
            Assembly options for the rendered cell.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(Estimate(label, value, ci=ci, fmt=fmt, ci_style=ci_style))

    def forest(
        self,
        label: str,
        *,
        of: str,
        ref: float = 0.0,
        scale: Scale = "table",
        domain: tuple[float, float] | None = None,
        width: int = 220,
        show_axis: bool = True,
        axis_fmt: Format | None = None,
    ) -> CoefTable:
        """Append a forest-plot column bound to an existing estimate.

        Parameters
        ----------
        label
            Column header.
        of
            Label of the `Estimate` to visualise.
        ref
            Reference value for the dashed line and role resolution.
        scale
            Which set of bars share an x-domain.
        domain
            Explicit domain, overriding `scale`.
        width
            Bar width in pixels.
        show_axis
            Emit an axis row per distinct domain.
        axis_fmt
            Callable labelling axis ticks.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(
            Forest(
                label,
                of=of,
                ref=ref,
                scale=scale,
                domain=domain,
                width=width,
                show_axis=show_axis,
                axis_fmt=axis_fmt,
            )
        )

    def passthrough(self, label: str, column: str) -> CoefTable:
        """Append a column rendered verbatim from the frame.

        Parameters
        ----------
        label
            Column header.
        column
            Frame column to display.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(Passthrough(label, column))

    def header(self, title: str, subtitle: str = "") -> CoefTable:
        """Set the header text.

        Parameters
        ----------
        title
            Title line.
        subtitle
            Subtitle line.

        Returns
        -------
        CoefTable
            A new table with the header set.
        """
        return self._with(title=title, subtitle=subtitle)

    def with_theme(self, theme: Theme) -> CoefTable:
        """Replace the theme.

        Parameters
        ----------
        theme
            Theme to use.

        Returns
        -------
        CoefTable
            A new table using `theme`.
        """
        return self._with(theme=theme)

    def with_direction(
        self, direction: Direction | Mapping[str, Direction]
    ) -> CoefTable:
        """Replace the direction semantics.

        Parameters
        ----------
        direction
            Table-wide direction, or a mapping from row key to direction.

        Returns
        -------
        CoefTable
            A new table using `direction`.
        """
        return self._with(direction=direction)

    def direction_for(self, row_key: str) -> Direction:
        """Resolve the direction applying to a row key.

        Parameters
        ----------
        row_key
            Value of the `rows` column.

        Returns
        -------
        Direction
            The direction for that row, defaulting to ``"higher_is_better"``.
        """
        if isinstance(self.direction, str):
            return self.direction
        return self.direction.get(row_key, "higher_is_better")

    def gt(self) -> GT:
        """Render to a `great_tables` object.

        Returns
        -------
        GT
            The rendered table.
        """
        from coeftable.render import to_gt

        return to_gt(self)

    def _repr_html_(self) -> str:
        return self.gt()._repr_html_()
```

- [ ] **Step 4: Add the Task 7 placeholder**

Until Task 7 lands, `src/coeftable/render.py` does not exist and `.gt()` raises `ModuleNotFoundError`. That is acceptable — no Task 5 test calls `.gt()`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_spec.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/coeftable/spec.py tests/test_spec.py
git commit -m "feat: add column specifications and table builder"
```

---

### Task 6: Frame resolution

**Files:**
- Create: `src/coeftable/frame.py`
- Test: `tests/test_frame.py`

**Interfaces:**
- Consumes: everything from Tasks 2-5.
- Produces:
  - `Resolved` frozen dataclass with fields `frame: Any`, `display_columns: list[str]`, `labels: dict[str, str]`, `spanners: dict[str, list[str]]`, `group_column: str | None`, `band_rows: list[int]`, `divider_rows: list[int]`, `axis_rows: list[int]`, `markdown_columns: list[str]`
  - `resolve(table: CoefTable) -> Resolved`

Internal column naming: without `split_columns`, the output column name is the spec label. With `split_columns`, it is `f"{split_value}\u2009|\u2009{label}"`, and `labels` maps it back to `label` for `cols_label`, with `spanners[split_value]` listing its columns.

- [ ] **Step 1: Write the failing test**

`tests/test_frame.py`:

```python
import narwhals as nw
import pandas as pd
import polars as pl
import pytest

from coeftable.frame import resolve
from coeftable.spec import CoefTable, ColumnNotFoundError

RAW = {
    "area": ["Core", "Core", "Core", "Core"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}


def base(data, **kwargs):
    return CoefTable(data, rows="metric", nest="variant", **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


@pytest.fixture(params=["pandas", "polars", "dict"])
def data(request):
    if request.param == "pandas":
        return pd.DataFrame(RAW)
    if request.param == "polars":
        return pl.DataFrame(RAW)
    return dict(RAW)


def test_resolves_for_every_backend(data):
    out = resolve(base(data))
    assert out.display_columns
    assert len(nw.from_native(out.frame).rows()) == 4


def test_repeated_row_keys_are_blanked(data):
    out = resolve(base(data))
    frame = nw.from_native(out.frame)
    assert frame["metric"].to_list() == ["<b>Revenue</b>", "", "<b>Latency</b>", ""]


def test_row_order_follows_first_appearance(data):
    out = resolve(base(data))
    frame = nw.from_native(out.frame)
    assert frame["variant"].to_list() == ["B", "C", "B", "C"]


def test_sort_rows_orders_lexically(data):
    out = resolve(base(data, sort_rows=True))
    frame = nw.from_native(out.frame)
    assert frame["metric"].to_list()[0] == "<b>Latency</b>"


def test_banding_alternates_by_row_key(data):
    out = resolve(base(data))
    assert out.band_rows == [0, 1]


def test_divider_marks_each_new_row_key_after_the_first(data):
    out = resolve(base(data))
    assert out.divider_rows == [2]


def test_forest_adds_one_axis_row_for_a_table_scale(data):
    out = resolve(base(data).forest("Plot", of="Lift %", scale="table"))
    frame = nw.from_native(out.frame)
    assert len(out.axis_rows) == 1
    assert len(frame.rows()) == 5


def test_row_scale_adds_one_axis_row_per_row_key(data):
    out = resolve(base(data).forest("Plot", of="Lift %", scale="row"))
    assert len(out.axis_rows) == 2


def test_show_axis_false_emits_no_axis_row(data):
    out = resolve(base(data).forest("Plot", of="Lift %", show_axis=False))
    assert out.axis_rows == []
    assert len(nw.from_native(out.frame).rows()) == 4


def test_no_forest_means_no_axis_row(data):
    out = resolve(base(data))
    assert out.axis_rows == []


def test_split_columns_produces_spanners_and_widened_frame():
    raw = {
        "metric": ["Revenue", "Revenue"],
        "method": ["OLS", "DiD"],
        "rel": [3.4, 3.1],
        "rel_lb": [1.2, 1.0],
        "rel_ub": [5.7, 5.2],
    }
    table = CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    out = resolve(table)
    assert set(out.spanners) == {"OLS", "DiD"}
    assert len(nw.from_native(out.frame).rows()) == 1
    assert all(out.labels[c] == "Lift %" for cols in out.spanners.values() for c in cols)


def test_groups_column_is_reported():
    out = resolve(base(pl.DataFrame(RAW), groups="area"))
    assert out.group_column == "area"


def test_missing_value_column_raises_with_available_columns():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate("A", "nope")
    with pytest.raises(ColumnNotFoundError, match="nope"):
        resolve(table)


def test_missing_rows_column_raises():
    table = CoefTable(pl.DataFrame(RAW), rows="nope").estimate("A", "rel")
    with pytest.raises(ColumnNotFoundError, match="nope"):
        resolve(table)


def test_non_numeric_estimate_column_raises_type_error():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate("A", "variant")
    with pytest.raises(TypeError, match="variant"):
        resolve(table)


def test_direction_mapping_flips_bar_colour():
    from coeftable.theme import DEFAULT

    spec = base(pl.DataFrame(RAW), direction={"Latency": "lower_is_better"})
    out = resolve(spec.forest("Plot", of="Lift %"))
    frame = nw.from_native(out.frame)
    plots = frame["Plot"].to_list()
    assert DEFAULT.color("favorable") in plots[0]
    assert DEFAULT.color("unfavorable") in plots[3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_frame.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.frame'`

- [ ] **Step 3: Write `src/coeftable/frame.py`**

```python
"""Resolve a table specification and a frame into rendered cells."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import narwhals as nw

from coeftable.format import is_missing, render_interval
from coeftable.spec import (
    CoefTable,
    Column,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    validate_columns,
)
from coeftable.svg import forest_axis, forest_bar
from coeftable.theme import role_for

SPLIT_JOINER = "\u2009|\u2009"


@dataclass(frozen=True)
class Resolved:
    """A specification resolved against a frame, ready to render.

    Parameters
    ----------
    frame
        Native frame of rendered cell strings, in the caller's own backend.
    display_columns
        Output column names in display order, excluding layout columns.
    labels
        Mapping from output column name to the header text to show.
    spanners
        Mapping from split value to the output columns it spans.
    group_column
        Name of the row-group column, if any.
    band_rows, divider_rows, axis_rows
        Zero-based row indices for banding, dividers and axis rows.
    markdown_columns
        Output columns whose contents are HTML.
    """

    frame: Any
    display_columns: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    spanners: dict[str, list[str]] = field(default_factory=dict)
    group_column: str | None = None
    band_rows: list[int] = field(default_factory=list)
    divider_rows: list[int] = field(default_factory=list)
    axis_rows: list[int] = field(default_factory=list)
    markdown_columns: list[str] = field(default_factory=list)


def _required_columns(table: CoefTable) -> list[str]:
    names: list[str] = []
    for key in (table.rows, table.nest, table.groups, table.split_columns):
        if key is not None:
            names.append(key)
    for column in table.columns:
        if isinstance(column, Estimate):
            names.append(column.value)
            if column.ci is not None:
                names.extend(column.ci)
        elif isinstance(column, Passthrough):
            names.append(column.column)
    return names


def _check_columns(frame: nw.DataFrame, table: CoefTable) -> None:
    available = list(frame.columns)
    missing = [n for n in _required_columns(table) if n not in available]
    if missing:
        raise ColumnNotFoundError(
            f"Columns {missing} are not in the frame. Available columns: {available}."
        )


def _numeric(frame: nw.DataFrame, name: str) -> list[float | None]:
    values = frame[name].to_list()
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Column {name!r} must be numeric to be used as an estimate or bound; "
                f"found {value!r}."
            ) from exc
    return out


def _ordered_unique(values: list[Any], *, sort: bool) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return sorted(seen, key=str) if sort else seen


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


def _domain_key(column: Forest, row_key: Any, group: Any, split: Any) -> Any:
    match column.scale:
        case "table":
            return ("table",)
        case "row_group":
            return ("group", group)
        case "split_column":
            return ("split", split)
        case "row":
            return ("row", row_key)


def _pad_domain(values: list[float], ref: float) -> tuple[float, float]:
    if not values:
        return (ref - 1.0, ref + 1.0)
    low, high = min(values), max(values)
    low, high = min(low, ref), max(high, ref)
    if low == high:
        return (low - 1.0, high + 1.0)
    margin = (high - low) * 0.08
    return (low - margin, high + margin)


def resolve(table: CoefTable) -> Resolved:  # noqa: C901, PLR0912, PLR0915
    """Resolve `table` against its frame.

    Parameters
    ----------
    table
        The specification to resolve.

    Returns
    -------
    Resolved
        Rendered cells plus the layout metadata `render` needs.

    Raises
    ------
    ColumnNotFoundError
        When a named column is absent from the frame.
    TypeError
        When an estimate or bound column is not numeric.
    SpecError
        When the column specification is inconsistent.
    """
    validate_columns(table.columns)
    frame = nw.from_native(table.data, eager_only=True)
    _check_columns(frame, table)

    n = len(frame)
    row_keys = frame[table.rows].to_list() if table.rows else [""] * n
    nest_keys = frame[table.nest].to_list() if table.nest else [None] * n
    group_keys = frame[table.groups].to_list() if table.groups else [None] * n
    split_keys = frame[table.split_columns].to_list() if table.split_columns else [None] * n

    numeric: dict[str, list[float | None]] = {}
    for column in table.columns:
        if isinstance(column, Estimate):
            numeric[column.value] = _numeric(frame, column.value)
            if column.ci is not None:
                for name in column.ci:
                    numeric[name] = _numeric(frame, name)

    # Forest domains, keyed by (forest label, domain key).
    domains: dict[tuple[str, Any], tuple[float, float]] = {}
    estimates = {c.label: c for c in table.columns if isinstance(c, Estimate)}
    for column in table.columns:
        if not isinstance(column, Forest):
            continue
        source = estimates[column.of]
        assert source.ci is not None  # noqa: S101 - guaranteed by validate_columns
        low_name, high_name = source.ci
        buckets: dict[Any, list[float]] = {}
        for i in range(n):
            key = _domain_key(column, row_keys[i], group_keys[i], split_keys[i])
            bucket = buckets.setdefault(key, [])
            bucket.extend(
                _finite([numeric[source.value][i], numeric[low_name][i], numeric[high_name][i]])
            )
        for key, values in buckets.items():
            domains[(column.label, key)] = column.domain or _pad_domain(values, column.ref)

    # Output row identity: one output row per (row key, nest key).
    identities = [(row_keys[i], nest_keys[i]) for i in range(n)]
    unique_rows = _ordered_unique([r for r, _ in identities], sort=table.sort_rows)
    ordered: list[tuple[Any, Any]] = []
    for row_key in unique_rows:
        for identity in identities:
            if identity[0] == row_key and identity not in ordered:
                ordered.append(identity)

    splits = _ordered_unique(split_keys, sort=table.sort_rows) if table.split_columns else [None]
    source_index = {(identities[i], split_keys[i]): i for i in range(n)}

    def output_name(column: Column, split: Any) -> str:
        return column.label if split is None else f"{split}{SPLIT_JOINER}{column.label}"

    display_columns: list[str] = []
    labels: dict[str, str] = {}
    spanners: dict[str, list[str]] = {}
    for split in splits:
        for column in table.columns:
            name = output_name(column, split)
            display_columns.append(name)
            labels[name] = column.label
            if split is not None:
                spanners.setdefault(str(split), []).append(name)

    cells: dict[str, list[str]] = {name: [] for name in display_columns}
    layout_rows: list[str] = []
    layout_nest: list[str] = []
    layout_group: list[Any] = []
    band_rows: list[int] = []
    divider_rows: list[int] = []
    axis_rows: list[int] = []
    emitted_axis: set[tuple[str, Any]] = set()

    def blank_row() -> None:
        for name in display_columns:
            cells[name].append("")

    previous_row_key: Any = None
    for position, (row_key, nest_key) in enumerate(ordered):
        first_of_key = row_key != previous_row_key
        if first_of_key and previous_row_key is not None:
            divider_rows.append(len(layout_rows))
        if unique_rows.index(row_key) % 2 == 0:
            band_rows.append(len(layout_rows))
        layout_rows.append(f"<b>{row_key}</b>" if first_of_key else "")
        layout_nest.append("" if nest_key is None else str(nest_key))
        layout_group.append(group_keys[source_index[((row_key, nest_key), splits[0])]])
        previous_row_key = row_key

        direction = table.direction_for(str(row_key))
        for split in splits:
            index = source_index.get(((row_key, nest_key), split))
            for column in table.columns:
                name = output_name(column, split)
                if index is None:
                    cells[name].append("")
                elif isinstance(column, Passthrough):
                    cells[name].append(str(frame[column.column].to_list()[index]))
                elif isinstance(column, Estimate):
                    low, high = (None, None)
                    if column.ci is not None:
                        low = numeric[column.ci[0]][index]
                        high = numeric[column.ci[1]][index]
                    cells[name].append(
                        render_interval(
                            numeric[column.value][index],
                            low,
                            high,
                            fmt=column.fmt,
                            style=column.ci_style,
                            theme=table.theme,
                        )
                    )
                else:
                    source = estimates[column.of]
                    assert source.ci is not None  # noqa: S101
                    value = numeric[source.value][index]
                    low = numeric[source.ci[0]][index]
                    high = numeric[source.ci[1]][index]
                    if is_missing(value):
                        cells[name].append("")
                        continue
                    key = _domain_key(column, row_key, layout_group[-1], split)
                    domain = domains[(column.label, key)]
                    role = (
                        table.color_rule(value, low, high, column.ref)
                        if table.color_rule is not None
                        else role_for(low, high, column.ref, direction)
                    )
                    cells[name].append(
                        forest_bar(
                            value,
                            low,
                            high,
                            domain=domain,
                            ref=column.ref,
                            color=table.theme.color(role),
                            theme=table.theme,
                            width=column.width,
                        )
                    )

        # Emit axis rows after the last data row using each domain.
        pending: list[Forest] = []
        for column in table.columns:
            if not isinstance(column, Forest) or not column.show_axis:
                continue
            keys = {
                _domain_key(column, row_key, layout_group[-1], split) for split in splits
            }
            if any((column.label, k) in emitted_axis for k in keys):
                continue
            future = any(
                _domain_key(column, later_row, layout_group[-1], split) in keys
                for later_row, _ in ordered[position + 1 :]
                for split in splits
            )
            if not future:
                pending.append(column)
        if pending:
            blank_row()
            layout_rows.append("")
            layout_nest.append("")
            layout_group.append(layout_group[-1])
            axis_rows.append(len(layout_rows) - 1)
            for column in pending:
                source = estimates[column.of]
                for split in splits:
                    key = _domain_key(column, row_key, layout_group[-1], split)
                    emitted_axis.add((column.label, key))
                    cells[output_name(column, split)][-1] = forest_axis(
                        domain=domains[(column.label, key)],
                        ref=column.ref,
                        fmt=column.axis_fmt or source.fmt,
                        theme=table.theme,
                        width=column.width,
                    )

    data: dict[str, list[Any]] = {}
    if table.groups:
        data[table.groups] = layout_group
    if table.rows:
        data[table.rows] = layout_rows
    if table.nest:
        data[table.nest] = layout_nest
    for name in display_columns:
        data[name] = cells[name]

    leading = [c for c in (table.groups, table.rows, table.nest) if c]
    markdown = [c for c in (table.rows, table.nest) if c] + display_columns

    return Resolved(
        frame=nw.from_dict(data, backend=nw.get_native_namespace(frame)).to_native(),
        display_columns=[*leading[1:] if table.groups else leading, *display_columns],
        labels=labels,
        spanners=spanners,
        group_column=table.groups,
        band_rows=band_rows,
        divider_rows=divider_rows,
        axis_rows=axis_rows,
        markdown_columns=markdown,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_frame.py -v`
Expected: all PASS. If the axis-row lookahead or the `display_columns` assembly needs adjustment to satisfy the tests, adjust the implementation — the tests define the contract.

- [ ] **Step 5: Commit**

```bash
git add src/coeftable/frame.py tests/test_frame.py
git commit -m "feat: resolve specifications against frames"
```

---

### Task 7: Great Tables rendering

**Files:**
- Create: `src/coeftable/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Resolved` and `resolve` (Task 6), `CoefTable` (Task 5), `Theme` (Task 3).
- Produces: `to_gt(table: CoefTable) -> GT`. Called by `CoefTable.gt()`.

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:

```python
import polars as pl
from great_tables import GT

from coeftable.spec import CoefTable
from coeftable.theme import MONO

RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}


def table(**kwargs):
    return CoefTable(pl.DataFrame(RAW), rows="metric", nest="variant", **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


def test_gt_returns_a_great_tables_object():
    assert isinstance(table().gt(), GT)


def test_header_text_appears_in_html():
    html = table().header("Results", "Q3").gt().as_raw_html()
    assert "Results" in html
    assert "Q3" in html


def test_inline_svg_survives_rendering():
    html = table().forest("Plot", of="Lift %").gt().as_raw_html()
    assert "<svg" in html
    assert "<rect" in html


def test_interval_markup_survives_rendering():
    html = table().gt().as_raw_html()
    assert "+3.40%" in html
    assert "<br" in html


def test_table_without_forest_emits_no_svg():
    html = table().gt().as_raw_html()
    assert "<svg" not in html


def test_split_columns_emit_spanner_labels():
    raw = {
        "metric": ["Revenue", "Revenue"],
        "method": ["OLS", "DiD"],
        "rel": [3.4, 3.1],
        "rel_lb": [1.2, 1.0],
        "rel_ub": [5.7, 5.2],
    }
    html = (
        CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
        .as_raw_html()
    )
    assert "OLS" in html
    assert "DiD" in html


def test_groups_emit_section_headers():
    html = table(groups="area").gt().as_raw_html()
    assert "Core" in html
    assert "Ops" in html


def test_theme_colours_reach_the_html():
    html = table().with_theme(MONO).forest("Plot", of="Lift %").gt().as_raw_html()
    assert MONO.color("favorable").lstrip("#").lower() in html.lower()


def test_repr_html_delegates_to_gt():
    assert "<table" in table()._repr_html_()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coeftable.render'`

- [ ] **Step 3: Write `src/coeftable/render.py`**

```python
"""Turn a resolved specification into a great_tables object."""

from __future__ import annotations

from great_tables import GT, loc, style

from coeftable.frame import resolve
from coeftable.spec import CoefTable


def to_gt(table: CoefTable) -> GT:
    """Render `table` to a `great_tables` object.

    Parameters
    ----------
    table
        The specification to render.

    Returns
    -------
    GT
        A styled table; further native `great_tables` calls may be chained.
    """
    resolved = resolve(table)
    theme = table.theme

    gt = GT(
        resolved.frame,
        groupname_col=resolved.group_column,
    )

    if table.title:
        gt = gt.tab_header(title=table.title, subtitle=table.subtitle or None)
        gt = gt.tab_style(
            style=[
                style.text(color=theme.header_fg, weight="bold", size="26px", align="left"),
                style.fill(color=theme.header_bg),
            ],
            locations=loc.title(),
        )
        if table.subtitle:
            gt = gt.tab_style(
                style=[
                    style.text(color=theme.header_fg, size="16px", align="left"),
                    style.fill(color=theme.header_bg),
                ],
                locations=loc.subtitle(),
            )

    gt = gt.tab_style(
        style=[
            style.text(weight="bold", color=theme.header_fg, align="center", size="16px"),
            style.fill(color=theme.column_label_bg),
            style.borders(sides="bottom", color=theme.header_bg, weight="2px"),
        ],
        locations=loc.column_labels(),
    )

    for split_value, columns in resolved.spanners.items():
        gt = gt.tab_spanner(label=split_value, columns=columns)

    relabel = {name: resolved.labels[name] for name in resolved.labels}
    if relabel:
        gt = gt.cols_label(**relabel)

    gt = gt.fmt_markdown(columns=resolved.markdown_columns).cols_align(align="center")

    if resolved.band_rows:
        gt = gt.tab_style(
            style=style.fill(color=theme.band),
            locations=loc.body(rows=resolved.band_rows),
        )
    if resolved.divider_rows:
        gt = gt.tab_style(
            style=style.borders(sides="top", color=theme.header_bg, weight="2px"),
            locations=loc.body(rows=resolved.divider_rows),
        )
    if resolved.axis_rows:
        gt = gt.tab_style(
            style=[
                style.fill(color=theme.surface),
                style.borders(sides="top", color=theme.rule, weight="1px"),
                style.borders(sides="bottom", color=theme.surface, weight="0px"),
            ],
            locations=loc.body(rows=resolved.axis_rows),
        )
    if resolved.group_column:
        gt = gt.tab_style(
            style=[
                style.text(
                    weight="bold", color=theme.header_fg, size="16px", transform="uppercase"
                ),
                style.fill(color=theme.column_label_bg),
                style.css("letter-spacing: 0.8px;"),
            ],
            locations=loc.row_groups(),
        )

    return gt.tab_options(
        table_font_size=theme.table_font_size,
        column_labels_font_size="16px",
        data_row_padding="10px",
        column_labels_padding="12px",
        data_row_padding_horizontal="16px",
        column_labels_padding_horizontal="16px",
        table_border_top_color=theme.header_bg,
        table_border_top_style="solid",
        table_border_bottom_color=theme.header_bg,
        table_border_bottom_style="solid",
        table_border_left_color=theme.header_bg,
        table_border_left_style="solid",
        table_border_right_color=theme.header_bg,
        table_border_right_style="solid",
        table_body_border_bottom_color=theme.header_bg,
        table_body_border_bottom_style="solid",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render.py -v`
Expected: all PASS. `cols_label` on a column name containing the split joiner may need `**{name: label}` unpacking rather than keyword syntax — the code already builds a dict, so pass it as `gt.cols_label(**relabel)` and switch to `gt.cols_label(cases=relabel)` if great-tables rejects non-identifier keys.

- [ ] **Step 5: Commit**

```bash
git add src/coeftable/render.py tests/test_render.py
git commit -m "feat: render resolved tables with great tables"
```

---

### Task 8: Public API, smoke test and documentation

**Files:**
- Modify: `src/coeftable/__init__.py`
- Modify: `README.md`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: everything.
- Produces: the public surface — `CoefTable`, `Estimate`, `Forest`, `Passthrough`, `Number`, `Percent`, `Currency`, `CIStyle`, `Theme`, `DEFAULT`, `COLORBLIND`, `MONO`, `SpecError`, `ColumnNotFoundError`, `role_for`, `__version__`.

- [ ] **Step 1: Write the failing test**

`tests/test_public_api.py`:

```python
import pandas as pd
import polars as pl
import pytest

import coeftable as ct

RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "att": [12400.0, -3100.0, 40.0, 120.0],
    "att_lb": [4200.0, -9800.0, -80.0, 45.0],
    "att_ub": [20600.0, 3600.0, 160.0, 195.0],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}


@pytest.mark.parametrize("frame", [pd.DataFrame(RAW), pl.DataFrame(RAW)])
def test_full_experiment_table_renders(frame):
    html = (
        ct.CoefTable(frame, rows="metric", nest="variant", groups="area")
        .estimate("Lift Amount", "att", ci=("att_lb", "att_ub"), fmt=ct.Number(compact=True))
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), fmt=ct.Percent(signed=True))
        .forest("Lift Plot", of="Lift %", ref=0.0)
        .header("Experiment Results", "Q3 holdout")
        .with_direction({"Latency": "lower_is_better"})
        .gt()
        .as_raw_html()
    )
    assert "Experiment Results" in html
    assert "<svg" in html
    assert "12.4k" in html


def test_one_line_table_renders():
    html = ct.CoefTable(
        pl.DataFrame(RAW), rows="metric", estimate="rel", ci=("rel_lb", "rel_ub")
    ).gt().as_raw_html()
    assert "<table" in html


def test_every_public_symbol_is_exported():
    expected = {
        "CoefTable", "Estimate", "Forest", "Passthrough",
        "Number", "Percent", "Currency", "CIStyle",
        "Theme", "DEFAULT", "COLORBLIND", "MONO", "role_for",
        "SpecError", "ColumnNotFoundError", "__version__",
    }
    assert expected <= set(ct.__all__)
    for name in expected:
        assert hasattr(ct, name)


def test_package_does_not_import_matplotlib():
    import sys

    assert "matplotlib" not in sys.modules
    assert "plotnine" not in sys.modules
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: FAIL — `AttributeError: module 'coeftable' has no attribute 'CoefTable'`

- [ ] **Step 3: Rewrite `src/coeftable/__init__.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_public_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the README**

Replace the Task 1 stub with: the description; installation; a **Quick start** showing the one-line form; an **Experiment table** example reproducing the Task 8 test (two estimates, a forest column, groups and nesting); a **Comparing methods** example using `split_columns`; a **Theming** section showing `dataclasses.replace(ct.DEFAULT, favorable="#0072B2")`, the three built-in themes, and `with_direction` for `lower_is_better`; and a **Data shape** section stating the tidy-in-dimensions, wide-in-triples contract. Every code block must be runnable as written.

- [ ] **Step 6: Smoke test the README by hand**

Run each README example in `uv run python -` and confirm each produces HTML containing `<table`. This is the deliverable working end to end, not a test file.

- [ ] **Step 7: Run the full gate**

Run: `make tests && make prek`
Expected: every test passes; every hook passes.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: expose public API and document usage"
```

---

## Self-Review

**Spec coverage.** Core model, Task 5. API including both doors and the sugar, Task 5. Input contract and narwhals round-trip, Task 6 (`test_resolves_for_every_backend`). Layout axes, Task 6. Direction and theme, Task 3, applied in Task 6. Forest plots including scaling, clipping caps and axis rows, Tasks 4 and 6. Formatting, Task 2. Errors, Tasks 5 and 6. Module layout, all tasks. Testing strategy, each task's tests plus Task 8.

**Ordering.** Task 3 must precede Task 2 — `format` imports `Theme`. Tasks 2 through 4 are otherwise independent leaves. Task 5 needs 2 and 3; Task 6 needs 2 through 5; Task 7 needs 6; Task 8 needs everything.

**Type consistency.** `Format` is `Callable[[float], str]` throughout. `role_for(lower, upper, ref, direction)` keeps that argument order in `theme.py` and at its `frame.py` callsite. `forest_bar` and `forest_axis` both take `domain` as a `tuple[float, float]` and `theme` as a keyword. `Resolved` field names match their `render.py` uses exactly. `Estimate.ci` is `tuple[str, str] | None` in the spec, the builder and the resolver.

**Known risks, to be resolved during implementation against the tests:**
- `great_tables.GT.cols_label` may reject column names containing the split joiner as keyword arguments. Task 7 Step 4 names the fallback.
- The axis-row lookahead in `resolve` is the subtlest logic in the plan; Task 6 Step 4 states that its tests define the contract.
