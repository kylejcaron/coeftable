# coeftable Design

**Status:** approved
**Date:** 2026-07-27

## Purpose

Make statistical summary tables easy to build. The unit of interest is an
estimate with uncertainty — a `(value, lower, upper)` triple — and the package
exists to turn columns of those triples into a publication-quality table, with
optional inline forest plots, flexible grouping, and configurable semantics.

Ported and generalized from a private `tables/` module that was welded to one
experiment-results schema. Everything domain-specific is dropped; the shapes
that made it useful are kept.

## Non-Goals

- Computing estimates or confidence intervals. Input is already-estimated.
- Statistical inference of any kind.
- Non-HTML output targets (LaTeX, typst). `great_tables` offers some of this
  downstream; we neither add nor block it.
- Interactive/JS tables.

## Core Model

A table is a **list of column specs** over a frame. The estimate is a property
of a *column*, not of the table — that is what allows several estimate columns
(each with its own `(value, lower, upper)` triple and its own formatting) to
coexist, and what makes the forest plot optional rather than special.

Three column types:

| Spec | Renders |
|---|---|
| `Estimate(label, value, ci=(lo, hi), fmt=...)` | `1.2k` over a muted `[1.1k, 1.4k]` |
| `Forest(label, of="<estimate label>", ref=0.0)` | an inline SVG interval bar |
| `Passthrough(label, column)` | the frame column verbatim |

`Forest` binds to an already-declared `Estimate` **by label**. This avoids
re-wiring the same three column names twice and guarantees plot and text agree.
A `Forest` whose `of=` does not name a declared `Estimate` is a spec error. A
`Forest` bound to an `Estimate` with `ci=None` is a spec error (nothing to plot).

Column order in the rendered table is declaration order.

## API

Two doors to the same underlying tuple of column specs. `.estimate()`,
`.forest()` and `.passthrough()` are thin appenders, not a second abstraction.

```python
import coeftable as ct

# Simplest case — constructor sugar, equivalent to a single
# .estimate("Estimate", "mean", ci=("lb", "ub")) call.
ct.CoefTable(df, rows="metric", estimate="mean", ci=("lb", "ub"))

# Chained: two estimate triples, a forest bound to one of them.
(
    ct.CoefTable(df, rows="metric", nest="variant", groups="area")
    .estimate("Lift Amount", "att", ci=("att_lb", "att_ub"), fmt=ct.Number(compact=True))
    .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), fmt=ct.Percent(signed=True))
    .forest("Lift Plot", of="Lift %", ref=0.0)
    .header("Experiment Results", "Q3 holdout")
)

# Declarative: identical object, order explicit, buildable in a loop.
ct.CoefTable(
    df,
    rows="metric",
    nest="variant",
    columns=[
        ct.Estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), fmt=ct.Percent()),
        ct.Forest("Lift Plot", of="Lift %", ref=0.0),
    ],
)

# Two methods side by side, no forest plot at all.
(
    ct.CoefTable(df, rows="metric", split_columns="method")
    .estimate("Estimate", "value", ci=("lb", "ub"))
)
```

`CoefTable` is a frozen dataclass; every chain method returns a new instance via
`dataclasses.replace`. `.gt()` returns the raw `great_tables.GT` so native GT
calls can continue the chain. `_repr_html_` delegates to `.gt()`, so a bare
`CoefTable` renders in a notebook.

`columns=` and the chain methods compose: chain methods append to whatever
`columns=` supplied, in call order. The `estimate=` / `ci=` constructor sugar is
itself an append and is prepended before any `columns=` entries; supplying
`estimate=` and a `columns=` entry with the same label is a duplicate-label
`SpecError`.

## Input Contract

**Tidy in the grouping dimensions, wide in the estimate triples.** One row per
`(rows, nest, split_columns)` combination, with `att / att_lb / att_ub` and
`rel / rel_lb / rel_ub` as sibling columns. This is what lets N estimate columns
share a row.

Read through `narwhals`, so pandas / polars / pyarrow all work with no
conversion. The output frame handed to `great_tables` is rebuilt with
`nw.from_dict(..., backend=nw.get_native_namespace(input))`, so the caller's own
frame library is used and neither pandas nor polars is a hard dependency.
(Verified against narwhals 2.24.0 for both pandas and polars.)

`ci=` is optional per estimate. A bare point estimate renders without brackets
and cannot back a `Forest`.

## Layout Axes

| Axis | Argument | Effect |
|---|---|---|
| Rows | `rows="metric"` | one row per key; label blanked on repeat rows |
| Nest | `nest="variant"` | stacks under each row key — variants against a control |
| Split | `split_columns="method"` | repeats the value + plot columns side by side under a GT spanner |
| Groups | `groups="area"` | `great_tables` `groupname_col` section headers |

Rows and nest keys keep **first-appearance order** from the input frame, which
is stable and lets the caller control ordering by sorting upstream.
`sort_rows=True` opts into lexical ordering instead.

`split_columns` pivots: for each distinct value of the split key, the full set
of declared columns is emitted with a `tab_spanner` carrying that value as the
label. (`tab_spanner(label, columns=...)` verified present in great-tables
0.22.0.)

## Direction and Theme

Colour roles are named by **meaning**, never by colour:
`favorable`, `unfavorable`, `inconclusive`, `neutral`.

```python
direction="higher_is_better" | "lower_is_better" | "neutral"   # table-wide
direction={"latency_p99": "lower_is_better", "revenue": "higher_is_better"}  # per row key
color_rule=lambda estimate, lower, upper, ref: "favorable"     # escape hatch
```

Role resolution:

- `direction="neutral"` always yields `neutral` — one colour, no judgement
  rendered. This is why `neutral` is a distinct role rather than a reuse of
  `inconclusive`; a table that makes no directional claim should not look like a
  table full of null results.
- Otherwise: interval entirely above `ref` yields `favorable` under
  `higher_is_better` and `unfavorable` under `lower_is_better`; entirely below,
  the reverse; spanning `ref` yields `inconclusive`.
- One-sided intervals are well defined: `upper is None` tests only
  `lower > ref`; `lower is None` tests only `upper < ref`.
- `color_rule`, when supplied, wins outright.

`Theme` is a frozen dataclass of colour, typography and chrome slots, so
`dataclasses.replace(ct.DEFAULT, favorable="#0072B2")` produces a variant
cheaply. Built-ins: `DEFAULT` (seaborn-deep derived), `COLORBLIND` (Okabe-Ito),
`MONO` (single ink — deliberately encodes no significance).

**Pydantic is deliberately not used.** Every spec object is hand-written Python
checked by `ty`, so a `Literal`-typed frozen dataclass catches typo'd
`direction` values and wrong `ci` arity *at edit time*, strictly earlier than a
runtime validator would. The two failures that actually bite — a `value=` naming
a column absent from the frame, and a `Forest(of=)` naming an undeclared
estimate — need frame and spec-graph context that pydantic cannot supply, so
they are custom checks either way (see Errors). Adding `pydantic-core`, a
multi-MB compiled wheel, would therefore buy a strict subset of existing static
coverage at real weight cost. If configuration-file themes are added later, that
*is* a trust boundary, and pydantic belongs there — confined to the loader,
behind an optional `coeftable[config]` extra, leaving the core dependency-light.

## Forest Plots

Rendered as **hand-written inline SVG**. No matplotlib, no plotnine. The prior
implementation built a plotnine `ggplot` per row and base64-embedded a 400-dpi
PNG: one full raster render per table row, blurry when zoomed, fat HTML, two
heavy hard dependencies. Inline SVG is vector-crisp, dramatically smaller, has
no plotting dependency, and themes via plain attributes. Verified that inline
`<svg>` survives `great_tables.GT.fmt_markdown` unmodified in 0.22.0.

The cost accepted is writing our own nice-number tick algorithm (~40 lines).

**Scaling.** `scale="table" | "row_group" | "split_column" | "row"` selects the
domain shared by a set of bars, generalizing the prior hard-coded per-RoAS /
per-CPiC bounds. One axis row is emitted per distinct domain, immediately after
the last data row using that domain. `domain=(lo, hi)` overrides explicitly;
`show_axis=False` suppresses the axis row.

**Unbounded and clipped intervals.** An interval extending past the domain edge
(including `upper is None`) draws to the edge with a triangular cap, so
clipping is visible rather than silently misleading. The text cell for the same
estimate renders `[lo, ∞)` — note the asymmetric bracket.

## Formatting

`Format` implementations are frozen dataclasses: `Number` (decimals, `compact`
for `1.4k` / `2.3M`, `signed`, `prefix`, `suffix`, thousands separators),
`Percent` (with `scale` to accept either fractions or percentage points), and
`Currency`. The old RoAS / CPiC special-casing collapses to
`Number(prefix="$")` and `Number(suffix="x")`.

`CIStyle` controls assembly: `layout="stacked"` (large value over muted
interval — the default), `"inline"` (`1.2 [1.1, 1.4]`), or `"value_only"`.
Missing values render `Theme.na_text` (`—`).

## Errors

Validation that carries its weight, all frame- or graph-dependent:

- `ColumnNotFoundError` — a `value`, `ci`, `rows`, `nest`, `groups` or
  `split_columns` name absent from the frame. Message lists available columns.
- `SpecError` — `Forest(of=)` naming an undeclared estimate; `Forest` bound to a
  CI-less estimate; duplicate column labels; no columns declared.
- Non-numeric estimate or bound column raises `TypeError` at resolve time,
  naming the column.

Errors raise at `.gt()` / resolve time, not at spec construction, so a spec can
be assembled before its frame is in hand.

## Module Layout

```
src/coeftable/
  __init__.py   public re-exports, __version__
  spec.py       CoefTable, Estimate, Forest, Passthrough
  format.py     Number, Percent, Currency, CIStyle, interval assembly
  theme.py      Theme, Role, Direction, role resolution, built-in themes
  svg.py        forest bar + axis emitters, nice-number ticks
  frame.py      narwhals ingest, validation, ordering, split pivot, domains
  render.py     resolved frame + spec -> great_tables.GT
```

Runtime dependencies: `great-tables`, `narwhals`. Nothing else.

Each module is independently testable: `format`, `theme` and `svg` are pure
functions over scalars and need no frame; `frame` is testable without
`great_tables`; `render` is the only module touching GT.

## Dropped From The Port

`results_to_summary_df`, `results_to_ratio_df`, `ratio_summary_gt`,
`experiment_summary_gt`, the `KPI` enum, `EstimateKind`, `ratio_kind`
(`roas`/`cpic`), post-treatment flags, and the `_label_fn` registry. All were
domain-specific coupling to one results schema. Their generic content survives
as: declared columns, `Number` prefix/suffix, per-scale forest domains, and the
unbounded-interval rendering.

## Testing Strategy

- `format`, `theme`, `svg`: pure unit tests over scalars, including boundary
  cases — interval touching `ref` exactly, one-sided intervals, zero-width
  domain, `NaN` and `None`.
- `frame`: ordering stability, blanking of repeated row keys, split pivot
  shape, domain computation per `scale`, and each error above.
- `render`: assert on the emitted HTML for the three canonical shapes (nested
  rows, split columns, no forest) rather than pixel snapshots.
- Round-trip both pandas and polars inputs through the same assertions to hold
  the narwhals contract.
