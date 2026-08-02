# Sparkline column: inline line plots with uncertainty

Tracking issue: https://github.com/kylejcaron/coeftable/issues/9

## Context

`coeftable` visualises a *single* estimate + interval per row via `Forest` /
`forest_bar`. There is no way to show how an estimate **moved over time**.
The motivating case: percent lift over the course of an experiment, where the
credible interval funnel narrows as sample accumulates and the series crosses
zero at some point.

### Why not `great_tables.fmt_nanoplot()`

great_tables ships nanoplots, which cover trend *shapes* well. Users who want
only a shape should be pointed at `.gt().fmt_nanoplot(...)` — we should
document that escape hatch, not reimplement it. But it structurally cannot do
what this feature is about. Verified against `great_tables==0.22.0`:

- **No per-point uncertainty band.** `_generate_nanoplot()` accepts only
  `y_vals`, `x_vals`, `all_y_vals`, and *scalar* reference values.
  `reference_area` sounds like the ribbon but is a **rectangle** spanning the
  full x-range at two constant y values (`_utils_nanoplots.py:1351-1356`:
  `p_ul = f"{data_x_points[0]},{data_y_ref_area_u}"`).
  `nanoplot_options.data_area_fill_color` is area-under-line, also not a band.
- **No per-row semantic colour.** `coeftable` colours marks via `role_for()` /
  `direction`, a per-row decision. `fmt_nanoplot` applies one `options=` per
  call; per-row colour needs one call per row via `rows=`, post-hoc on the `GT`.
- **`autoscale` is a bool** — all rows share a y-domain or none.
  `coeftable`'s `Scale` already has four levels.
- **Pipeline friction.** `Resolved.frame` is all pre-rendered strings
  (`frame.py`, `cells: dict[str, list[str]]`). A nanoplot column would need raw
  list data to survive `resolve()` untouched into `render.py`.

Not a blocker, contrary to the 0.4.0 blog post: 0.22.0 emits **inline `<svg>`**,
not base64 `<img>` (verified via `as_raw_html()` on a polars List column — zero
`data:image/svg+xml;base64` occurrences). The blog is stale there.

Conclusion: write our own emitter, but **match nanoplot's input conventions**
(polars `List` columns, `{"x": [...], "y": [...]}`-shaped data) so muscle
memory transfers.

### Why the refactor comes first

Adding a fourth column kind touches `resolve()` in five places:
`_required_columns`, the extraction block, the domain pass, cell emission, and
the footer/axis lookahead at the tail of `resolve()`. The last is
the real problem — it is O(rows² × splits) and hardcodes *footer =
`forest_axis`*. A sparkline footer is a different shape (dates, not y-ticks).

Every column kind already has the same three-phase lifecycle, hand-inlined per
type. Task 1 names those seams so Task 5 is additive.

## Global Constraints

- **Scope knife.** In: per-point CI ribbon, per-row favorability colour, shared
  y-domain via the existing four-level `Scale`, dashed reference line, footer
  date axis, endpoint value label. Out: bar plots, hover interactivity, a large
  options struct, multiple guide lines per cell — defer all to `fmt_nanoplot`.
- Task 1 is a **behaviour-preserving no-op**. The existing 238-line
  `tests/test_frame.py` and the rest of the suite must pass **unmodified**. If a
  test needs changing, the refactor is wrong.
- `type Format = Callable[[float], str]` (`format.py:12`) stays float-only. Date
  axis labelling gets a **sibling** `TimeFormat` type — widening `Format` would
  touch `Number`/`Percent`/`Currency`/`CIStyle` for no gain.
- `nice_ticks()` (`svg.py:13-37`) is decimal-only (`_TICK_STEPS = (1.0, 2.0,
  2.5, 5.0, 10.0)` × powers of ten) and stays that way for numeric x. Calendar
  ticks need a separate generator — month/quarter/year boundaries are not
  decimal steps.
- x values project onto the **true axis**, never index position. Unevenly spaced
  dates must render unevenly; a data gap must be visible, not silently closed.
- Backend-agnostic via `narwhals`, same as the rest of the package: pandas,
  polars, pyarrow. No polars-only code paths.
- Commit messages: no internal tooling jargon, per standing repo convention.

## Design

### Column kind

```python
@dataclass(frozen=True)
class Sparkline:
    label: str
    value: str                                   # list-valued column (y)
    ci: tuple[str, str] | None = None            # list-valued bounds
    x: str | None = None                         # list-valued x; None -> index
    data: Any | None = None                      # long companion frame (sugar)
    ref: float = 0.0
    scale: Scale = "row"                         # y-domain sharing
    domain: tuple[float, float] | None = None    # explicit y-domain
    width: int = 220
    height: int | None = None                    # None -> layout-derived
    show_axis: bool = True                       # footer x-axis row
    show_endpoint: bool = True                   # endpoint value label
    endpoint_width: int = 44                     # FIXED reserve, see Task 3
    fmt: Format = _DEFAULT_FMT                   # formats endpoint label
    axis_fmt: Format | TimeFormat | None = None  # x tick labels
```

Unlike `Forest`, `Sparkline` does **not** bind to an `Estimate` via `of=`. A
series has no scalar `Estimate` to bind to, so it declares its own columns.

### Two front doors, one path

- **List columns (core contract).** `value` / `ci` / `x` name list-valued
  columns in the main frame. One frame row stays one table row.
- **Long companion frame (sugar).** When `data=` is given, `value` / `ci` / `x`
  name *scalar* columns in that frame, which is grouped by the table's
  `rows` (+ `nest`, + `split_columns`) keys and collapsed into the list form.
  Implemented as a pre-pass so there is exactly one downstream code path.

### Scales

- **y** — governed by `scale=`, default **`"row"`**. This is deliberately the
  opposite of `Forest`'s `"table"` default: forest columns usually share a unit
  (all lift %), whereas sparkline rows are typically different metrics in
  different units. A shared y across dollars and milliseconds renders every
  small-magnitude metric as a flat line at the bottom of its cell.

  `_domain_key` returns `("row", row_key)`, keyed on the
  **`rows`** value and not the nest — so with `nest="variant"`, Revenue/B and
  Revenue/C automatically share a domain while Latency gets its own. Correct
  semantics for free.

- **x** — **always shared table-wide.** Dates must align across rows; a per-row
  time axis is almost never wanted. Not configurable, so `scale=` unambiguously
  means y.

Cell height is a fixed pixel constant (`height=30`, matching nanoplot's `2em`
default). `scale` changes only which value range maps onto those pixels.

### Colour

`role_for(low, high, ref, direction)` takes one interval, but a series has N.
The colour comes from the **last point's interval** — the experiment's current
state. Consistent with the endpoint label, and `role_for`'s existing
`inconclusive` role (interval straddles `ref`) lands exactly right for a
not-yet-significant experiment.

### Reference line

`ref: float = 0.0`, single-valued, mirroring `Forest.ref`. For `Forest` the
estimate lives on x so `ref` is a *vertical* dashed line; for `Sparkline` the
estimate lives on y so the identical `ref` is *horizontal*. Same `theme.axis`
colour, same `2,2` dash. One line per row.

`_pad_domain(values, ref, *, symmetric=False)` already forces `ref` into the
domain, so a lift series sitting entirely above zero still renders with the zero
line visible instead of cropped.

### Missing values

A `None`/NaN in the series breaks both the line and the ribbon into segments (a
gap). No option — matches nanoplot's `missing_vals="gap"` default.

## Task 1: Extract a column protocol; split layout out of `frame.py`

**Change:** Behaviour-preserving refactor of the existing three column kinds.

- New `src/coeftable/grid.py`: row identity, ordering, `source_index`, banding,
  divider rows, and footer *scheduling* (the generic "emit when no later row
  shares this domain key" rule at the tail of `resolve()`). **Zero column
  knowledge** — no `isinstance` on any column kind.
- New protocol, in `spec.py` beside the dataclasses:
  ```python
  class ColumnKind(Protocol):
      label: str
      def sources(self) -> Iterable[str]: ...          # frame columns needed
      def prepare(self, scan: Scan) -> Prepared: ...   # shared domains
      def cell(self, ctx: Cell) -> str: ...            # one rendered cell
      def footer(self, ctx: Footer) -> str | None: ... # axis row, or None
  ```
  These name seams that already exist inside `resolve()`: the domain pass, the
  cell `if/elif/else`, and the footer lookahead, in that order.
- `Estimate`, `Forest`, `Passthrough` implement it. `Estimate` and
  `Passthrough` return `None` from `footer()`. `resolve()` shrinks to: build
  grid → `prepare` each column → `cell` per (row, split, column) → run the
  shared footer pass.
- The O(rows² × splits) lookahead moves into `grid.py` as-is. Optimising it is
  **not** in scope — port the logic unchanged so the no-op claim holds.

**Verification:** `uv run pytest` — the full suite passes with **no test file
modified** (`git diff --stat tests/` is empty). This is the whole point of the
task; a changed test means changed behaviour.

## Task 2: Resolve series data from both front doors

**Change:** New `src/coeftable/series.py`.

- `Series` value object: parallel `x`, `y`, `lower`, `upper` lists, already
  coerced to `float | None`, `None` for missing. Reuses `_numeric`'s missing
  sentinel handling (`<NA>`, `NaT`) from `_numeric` — lift that helper
  into a shared spot rather than duplicating it.
- List-column path: read a list-valued column across pandas / polars / pyarrow
  via narwhals; validate that `value`, each `ci` bound, and `x` have equal
  length per row, raising `SpecError` naming the offending row key when not.
- Companion-frame path: group `data` by the table's `rows` (+ `nest` +
  `split_columns`) keys, sort by `x`, and emit the same `Series`. A row key
  present in the main frame but absent from `data` yields an empty `Series`
  (renders as a blank cell, consistent with how `resolve` blanks a missing
  split when `index is None`).
- `x=None` falls back to positional index `0..n-1`.
- Temporal `x` (date / datetime / pyarrow timestamp) is normalised to a float
  epoch for projection, with the original dtype retained so the axis knows to
  use calendar ticks.

**Verification:** New `tests/test_series.py` covering, for all three backends:
list columns round-trip; the companion frame produces the same `Series` as the
equivalent list columns (the "one path" claim, asserted directly); ragged
lengths raise `SpecError`; missing row keys give an empty `Series`; NaN and
`<NA>`/`NaT` sentinels become `None`; temporal x normalises with correct
relative spacing for an uneven series.

## Task 3: `sparkline_bar` SVG emitter

**Change:** Add to `src/coeftable/svg.py`, beside `forest_bar`, reusing
`_projector` and `_svg`.

Draw order (back to front):
1. **Ribbon** — one `<polygon>` per contiguous non-missing run, tracing the
   upper path then the lower path reversed, `fill-opacity` ~0.15.
2. **Reference line** — horizontal dashed `<line>` at `ref`, `theme.axis`,
   `stroke-dasharray="2,2"`, drawn only when `ref` is inside the y-domain
   (mirroring the same guard in `forest_bar`).
3. **Series line** — `<polyline>` per contiguous run, `stroke-width` 1.5.
4. **Endpoint dot** — small filled `<circle>` at the last non-missing point.
5. **Endpoint label** — `<text>` right of the dot when `show_endpoint`,
   formatted with `fmt`, right-aligned within the reserved strip.

**The endpoint reserve must be a fixed pixel constant, never derived from the
formatted string.** `forest_bar` and `forest_axis` line up only because both
build `_projector(domain, width, pad)` with identical `width` and `pad`. If the
plot area shrinks by a text-dependent amount, two guarantees break at once:
the footer ticks stop sitting under their data points, and — because the
reserve would differ per row — rows stop aligning with each other, destroying
the "x always shared table-wide" property that is the whole reason the x-domain
is not configurable.

So: `endpoint_width` is a config constant, and **both** `sparkline_bar` and
`sparkline_axis` project over the same reduced inner width
(`width - 2*pad - endpoint_width` when `show_endpoint`, else `width - 2*pad`).
A value too long for the strip is clipped, not allowed to widen it.

Colour is a single resolved `color` argument, as `forest_bar` already takes —
role resolution stays in the caller.

**Verification:** New cases in `tests/test_svg.py` (mirroring its existing
style): ribbon polygon point count matches series length for a clean series;
a NaN mid-series produces two polygons and two polylines, not one spanning the
gap; `ref` outside the domain omits the dashed line; `show_endpoint=False` emits
no `<text>`; an all-missing series emits a valid empty `<svg>` rather than
raising; unevenly spaced x produces non-uniform point spacing (asserted on the
projected coordinates, this is the anti-index-spacing guard).

**The alignment invariant gets its own test, in both directions.** Render two
rows whose endpoint labels format to very different string lengths (e.g. `1%`
and `-12,345%`) and assert their first and last *data* x-coordinates are
identical — proving the reserve is text-independent. Then assert
`sparkline_axis`'s tick x-coordinates coincide with `sparkline_bar`'s projected
point x-coordinates for the same domain and `show_endpoint` setting. This is
the regression guard for the failure mode where ticks drift out from under
their points.

## Task 4: Calendar ticks, `TimeFormat`, and `sparkline_axis`

**Change:**

- `format.py`: add `type TimeFormat = Callable[[float], str]` distinct from
  `Format` by intent, plus a `DateAxis` formatter that renders an epoch float as
  a short label whose granularity follows the tick step (`Jan`, `Q1`, `2026`).
  `Format` itself is untouched.
- `svg.py`: add `calendar_ticks(low, high, target)` returning epoch floats on
  real month / quarter / year boundaries, selecting a step from a fixed ladder
  (day, week, month, quarter, year). `nice_ticks` is untouched and still serves
  numeric x.
- `svg.py`: add `sparkline_axis(...)`, structurally parallel to `forest_axis`
  (baseline, tick marks, labels) but choosing `calendar_ticks` +
  `TimeFormat` for temporal domains and `nice_ticks` + `Format` for numeric
  ones.

**Verification:** New cases in `tests/test_svg.py`: `calendar_ticks` over a
14-month span lands on month boundaries (assert each tick is the 1st of a
month); over a 5-year span lands on year boundaries; a sub-month span falls back
to day/week steps; a degenerate span (`low == high`) returns a single tick,
matching `nice_ticks`'s existing behaviour; `sparkline_axis` on a numeric domain
produces the same tick positions as `forest_axis` would.

## Task 5: Wire `Sparkline` into the pipeline

**Change:**

- `spec.py`: add the `Sparkline` dataclass per the Design section; add to the
  `Column` union; add a `.sparkline(...)` builder method following the existing
  `.forest(...)` shape; extend `validate_columns` — `ci` bounds must be given as
  a pair, and `data=` and list-column mode are mutually exclusive. `domain=`
  overrides `scale=`, matching `Forest`'s documented behaviour — not an error.
- Implement `sources` / `prepare` / `cell` / `footer` for `Sparkline` against
  the Task 1 protocol:
  - `prepare` — bucket **y** values (including `lower`/`upper`) by
    `_domain_key`, pad with `_pad_domain(values, ref)`; compute the single
    table-wide **x** domain separately.
  - `cell` — resolve role from the last point's interval, call `sparkline_bar`.
  - `footer` — call `sparkline_axis` with the x domain.
- `frame.py`: no new `isinstance` branches. If Task 5 requires one, Task 1 was
  done wrong.
- Row height: follow `Forest`'s existing pattern rather than a bare constant.
  `Forest.height` is `int | None`, resolved by `_forest_height()` against
  `_LAYOUT_HEIGHTS` (`{"stacked": 48, "inline": 34, "value_only": 34}`) so the
  bar fills the row its CI layout produces. `Sparkline.height` takes the same
  `int | None` shape with its own default; it is **not** taller than a forest
  row by default, which an earlier draft of this plan wrongly assumed.
- `Resolved.forest_columns` drives a padding trim in `render.py` (`padding-top:
  2px; padding-bottom: 2px`) so the SVG reaches the row's true edges. Sparkline
  output columns **must join that set** — generalise the field to
  `plot_columns` (updating `Forest`'s use) rather than adding a sibling.
  Without it the SVG sits inside text-sized vertical padding.

**Verification:** New `tests/test_sparkline.py`: end-to-end render of the
motivating experiment table (lift % over dates, `ref=0`, `nest="variant"`,
`groups="area"`); `scale="row"` gives each metric its own y-domain while nested
variants of one metric share one (assert on distinct projected extents);
`scale="table"` gives all rows one domain; exactly one footer axis row is
emitted for the column, since x is always shared table-wide; a row whose last
interval straddles `ref` renders in the
`inconclusive` colour, one clearly above renders `favorable`, and the same row
under `lower_is_better` flips to `unfavorable`. Plus a smoke test that
`.gt().as_raw_html()` contains the expected `<svg>` count.

## Task 6: Public API, docs, and example

**Change:**

- `__init__.py`: export `Sparkline` (and `TimeFormat` / `DateAxis` if they are
  part of the public surface) alongside the existing names.
- `README.md`: a "Trend over time" section after "Experiment table", showing the
  motivating lift-over-experiment table. Document both front doors (list columns
  and companion frame). Add a short note pointing users who want a plain trend
  shape with no uncertainty at `.gt().fmt_nanoplot(...)` instead — the scope
  knife, stated for users.
- Extend the "Data shape" section: series columns are the one place the
  tidy-wide-in-triples rule bends, and explain why.

**Verification:** `uv run pytest tests/test_public_api.py` (it already asserts
the export surface — extend it for the new names). Every README code block runs
as written; execute each one against a real frame and confirm it renders. Visual
check of the rendered table via `.gt().save()` before closing.
