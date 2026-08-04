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

## Trend over time

![Rendered experiment results table with a 30-day trend column showing favorable, unfavorable, and inconclusive series with narrowing uncertainty bands](docs/images/trend-example.png)

Add a `.sparkline(...)` column to plot a metric's trajectory next to its
point estimate: an inline SVG line with a shaded credible interval and a
dashed reference line (pass `show_endpoint=True` to also label the last
value). Below, `ref=0.0` draws the reference line that Latency's series
crosses as its credible interval narrows over three weeks of data:

There are two front doors for the series data, the same list-columns vs.
companion-frame choice used elsewhere in coeftable:

**A long companion frame** — the shape most real series data already
arrives in: a SQL export, a dbt model, an experimentation platform's daily
metrics table. Pass `data=` a separate frame with one row per point, and
`value` / `ci` / `x` name *scalar* columns on it. coeftable groups the
companion frame by the table's `rows` (+ `nest`, + `split_columns`) keys
and collapses each group into a series internally:

```python
import datetime as dt
import pandas as pd
import polars as pl
import coeftable as ct

dates = [dt.date(2024, 1, 1), dt.date(2024, 1, 8), dt.date(2024, 1, 15)]

trend = pl.DataFrame(
    {
        "metric": ["Revenue", "Latency"],
        "lift": [3.4, 0.5],
        "lift_lb": [1.2, -1.0],
        "lift_ub": [5.7, 2.0],
    }
)

history = pd.DataFrame(
    {
        "metric": ["Revenue", "Revenue", "Revenue", "Latency", "Latency", "Latency"],
        "date": dates + dates,
        "lift": [1.5, 2.4, 3.4, -1.0, 0.2, 1.5],
        "lift_lb": [0.3, 1.4, 2.6, -2.5, -0.6, 1.0],
        "lift_ub": [2.7, 3.4, 4.2, 0.5, 1.0, 2.0],
    }
)

(
    ct.CoefTable(trend, rows="metric")
    .estimate("Lift %", "lift", ci=("lift_lb", "lift_ub"), fmt=ct.Percent(signed=True))
    .sparkline(
        "Trend",
        value="lift",
        ci=("lift_lb", "lift_ub"),
        x="date",
        data=history,
        ref=0.0,
        axis_fmt=ct.DateAxis(),
    )
)
```

**List columns on the main frame** — if the series is already collapsed
onto its row (e.g. from a prior `.group_by(...).agg(...)`, or a source that
natively stores arrays), `value` / `ci` / `x` can instead name columns
whose cells each hold one list of points per row:

```python
import datetime as dt
import polars as pl
import coeftable as ct

dates = [dt.date(2024, 1, 1), dt.date(2024, 1, 8), dt.date(2024, 1, 15)]

trend = pl.DataFrame(
    {
        "metric": ["Revenue", "Latency"],
        "lift": [3.4, 0.5],
        "lift_lb": [1.2, -1.0],
        "lift_ub": [5.7, 2.0],
        "history": [
            [1.5, 2.4, 3.4],
            [-1.0, 0.2, 1.5],
        ],
        "history_lb": [
            [0.3, 1.4, 2.6],
            [-2.5, -0.6, 1.0],
        ],
        "history_ub": [
            [2.7, 3.4, 4.2],
            [0.5, 1.0, 2.0],
        ],
        "date": [dates, dates],
    }
)

(
    ct.CoefTable(trend, rows="metric")
    .estimate("Lift %", "lift", ci=("lift_lb", "lift_ub"), fmt=ct.Percent(signed=True))
    .sparkline(
        "Trend",
        value="history",
        ci=("history_lb", "history_ub"),
        x="date",
        ref=0.0,
        axis_fmt=ct.DateAxis(),
    )
)
```

Both render the same column. Reach for the companion frame first — it
matches how most series data actually arrives, one row per observation.
Reach for list columns only when the series is already collapsed onto its
row.

Since `x` is always shared table-wide (dates must line up across rows), a
series with fewer points than its neighbours visibly occupies only part of
its cell's width rather than stretching to fill it — this is intentional,
not a bug: `x` position reflects where a point falls in the shared domain,
never the row's own extent.

Want a plain trend line with no uncertainty band — no `ci`, no ribbon?
great_tables' own `.gt().fmt_nanoplot(...)` covers that directly.
`.sparkline(...)` exists specifically for the estimate-with-interval case.

**Shaping the y-axis.** Each row's domain fits tightly to its own data by
default (`scale="row"`, `autoscale="tight"`). Four ways to change that,
shown together against the same noisy series:

```python
import polars as pl
import coeftable as ct

trend = pl.DataFrame(
    {
        "metric": ["Revenue"],
        "lift": [[1.0, 1.05, 0.95, 1.02, 0.98, 300.0]],
    }
)

(
    ct.CoefTable(trend, rows="metric")
    # Default: fits tightly to this row's own min/max. A single outlier
    # like the 300.0 here dominates and flattens the rest of the series.
    .sparkline("Tight (default)", value="lift", ref=1.0)
    # autoscale="robust" fits an IQR/Tukey fence instead of raw min/max,
    # so the outlier doesn't flatten the rest. It still draws -- clipped
    # to the domain edge and flagged with a clip-cap marker, never hidden.
    .sparkline("Robust", value="lift", ref=1.0, autoscale="robust")
    # max_ylim=N narrows whatever domain scale/autoscale would have
    # produced -- clamping to `ref +/- N`, only if the natural domain
    # would have exceeded that ceiling. Composes with autoscale.
    .sparkline("Ceiling", value="lift", ref=1.0, max_ylim=0.5)
    # ylim=(lo, hi) is an absolute override, replacing scale/autoscale/
    # max_ylim entirely.
    .sparkline("Override", value="lift", ref=1.0, ylim=(0.9, 1.1))
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

**Series columns bend this rule.** A point estimate is one number (plus
bounds), so a triple of scalar columns holds it. A `.sparkline(...)` series
is N points, not one -- most naturally via the companion-frame door, a
separate long frame with one row per point, joined by the table's row/nest/
split keys. Or, when the series is already collapsed onto its row, its
`value` / `ci` columns can instead hold a *list* per row directly. Either
way a row of the table is still one row; the series column just carries
more data per row than an estimate column does. See
[Trend over time](#trend-over-time) for both shapes.
