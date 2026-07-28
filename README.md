# coeftable

Lightweight, report-ready summary tables for estimates with uncertainty. Renders
inline forest plots, builds on great_tables HTML output, and works with pandas,
polars, or pyarrow frames.

![Rendered experiment results table with grouped sections, nested variants, and an inline forest plot](docs/images/example.png)

## Installation

```bash
uv add coeftable
```

## Quick start

The one-line form declares a table with a single estimate column:

```python
import polars as pl
import coeftable as ct

df = pl.DataFrame(
    {
        "metric": ["Revenue", "Latency"],
        "est": [3.4, 0.5],
        "lb": [1.2, -1.0],
        "ub": [5.7, 2.0],
    }
)

ct.CoefTable(df, rows="metric", estimate="est", ci=("lb", "ub"))
```

A `CoefTable` renders itself in marimo, Jupyter, and any other `_repr_html_`-aware viewer —
leave it as the last expression in a cell, no extra call needed. Outside a notebook, use
`.gt()` to reach the underlying [great_tables](https://posit-dev.github.io/great-tables/)
object: `table.gt().as_raw_html()` for an HTML string, `table.gt().save("t.png")` for an
image, `table.gt().tab_options(...)` to keep styling with great_tables' own API.

## Experiment table

Build a complete experiment results table with multiple estimates, a forest
plot column, grouped row sections, nested variants, and direction hints:

```python
import polars as pl
import coeftable as ct

experiment = pl.DataFrame(
    {
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
)

(
    ct.CoefTable(experiment, rows="metric", nest="variant", groups="area")
    .estimate("Lift Amount", "att", ci=("att_lb", "att_ub"), fmt=ct.Number(compact=True))
    .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), fmt=ct.Percent(signed=True))
    .forest("Lift Plot", of="Lift %", ref=0.0, symmetric=True)
    .header("Experiment Results", "Example Experiment")
    .with_direction({"Latency": "lower_is_better"})
)
```

## Comparing methods

Use `split_columns` to compare multiple methods side by side. Each value in the
split column produces its own set of estimate / forest columns:

```python
import polars as pl
import coeftable as ct

methods = pl.DataFrame(
    {
        "metric": ["Revenue", "Revenue", "Latency", "Latency"],
        "method": ["A", "B", "A", "B"],
        "est": [3.4, 3.1, 0.5, 0.6],
        "lb": [1.2, 1.0, -1.0, -0.8],
        "ub": [5.7, 5.2, 2.0, 2.1],
    }
)

(
    ct.CoefTable(
        methods, rows="metric", split_columns="method", estimate="est", ci=("lb", "ub")
    )
    .header("Cohort Revenue by Method")
)
```

## Theming

Four built-in themes are available from `coeftable.theme`:

```python
from coeftable.theme import BLUE, COLORBLIND, DEFAULT, MONO, TEXTUAL

DEFAULT       # Alias for TEXTUAL -- what CoefTable uses if you don't set a theme
TEXTUAL       # Minimal, publication-style: muted colours, light chrome
BLUE          # The original blue-grey palette
COLORBLIND    # Colourblind-safe palette
MONO          # Grayscale for mono journals
```

Apply one with `.with_theme(...)`:

```python
table.with_theme(BLUE)
```

Customise a theme with `dataclasses.replace`:

```python
from dataclasses import replace

my_theme = replace(BLUE, favorable="#0072B2")
```

Use `with_direction` to mark rows where lower values are favourable (reusing
the `df` frame from [Quick start](#quick-start)):

```python
table = (
    ct.CoefTable(df, rows="metric", estimate="est", ci=("lb", "ub"))
    .with_direction({"Latency": "lower_is_better"})
)
```

## Data shape

coeftable expects a dataframe where every row is a single comparison. The
resolution logic maps pairs of upper / lower bound columns to each estimate, so
your data should be **wide in triples** — one point-estimate column and (when
applicable) its lower and upper bound columns — rather than in long format with
a `parameter` column.

**Dimensions:**
- `rows` — the label for each row in the table (e.g. a metric name).
- `nest` — an optional secondary label stacked below each row.
- `groups` — an optional column whose values produce section headers.
- `split_columns` — an optional column whose values produce repeated column
  groups side by side, useful for comparing methods.
