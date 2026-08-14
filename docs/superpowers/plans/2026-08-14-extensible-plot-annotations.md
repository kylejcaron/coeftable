# Extensible Plot Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed rule and band annotations to forest plots and sparklines, including row-specific field binding, automatic-domain participation, and deterministic underlay/overlay composition.

**Architecture:** Public immutable declarations live in `coeftable.annotations`; preparation resolves literals and main-frame fields once into per-row numeric marks. `Forest` and `Sparkline` add eligible coordinates to their existing domains, while `svg.py` owns projection, clipping, escaping, and layer composition. Existing reference semantics remain separate and unchanged.

**Tech Stack:** Python 3.12+, dataclasses, Narwhals, inline SVG, Great Tables, pytest, Polars/Pandas test backends.

**Design:** `docs/superpowers/specs/2026-08-14-extensible-plot-annotations-design.md`

## Global Constraints

- Support Python `>=3.12`; add no runtime dependency.
- Preserve output and behavior when `annotations=()`; existing `ref`, `show_ref`, semantic colors, axes, legends, clipping, and domain defaults must not change.
- Use one shared `annotations=` parameter on `forest()` and `sparkline()`; do not add plot-specific rule/band parameters.
- Ship only typed `Rule` and `Band` marks. No labels, points, selectors, callbacks, arbitrary SVG, numeric z-index, or annotation legends.
- Annotation strings always name scalar columns in the main `CoefTable` frame. Numeric/date/datetime values are literals. Missing field values omit that row's mark.
- Forest accepts x annotations only; sparkline accepts x and y annotations. Multi-series sparklines draw annotations once per cell.
- Included annotations expand automatic domains after robust filtering. Forest symmetry then applies; sparkline `max_ylim` and explicit `ylim` remain authoritative.
- Public annotations render only in cells with base data. Underlays precede all existing plot content; overlays follow it.
- Keep frame values and temporal coordinates prepared once. SVG emitters receive resolved numeric marks only.
- Use existing `SpecError` and `ColumnNotFoundError` behavior. Errors identify the plot label and annotation index; row-dependent failures include row identity.
- No tooling names in source comments, README, changelog, or commit messages.

## File Structure

- Create `src/coeftable/errors.py`: cycle-free home for existing public specification errors.
- Create `src/coeftable/_axis.py`: shared temporal-axis detection and epoch conversion used by series and annotations.
- Create `src/coeftable/annotations.py`: public declarations, private resolved marks, source resolution, validation, and domain-contribution helpers.
- Modify `src/coeftable/series.py`: consume shared temporal helpers without changing series behavior.
- Modify `src/coeftable/spec.py`: attach annotations to plot specifications, prepare them, and include their coordinates in domains.
- Modify `src/coeftable/svg.py`: project and emit rules/bands around existing plot content.
- Modify `src/coeftable/__init__.py`: export `Rule` and `Band`; preserve error exports.
- Create `tests/test_annotations.py`: declaration, source-resolution, coercion, and validation contracts.
- Modify `tests/test_series.py`: temporal-helper extraction regression coverage.
- Modify `tests/test_svg.py`: annotation geometry, clipping, styling, and layer-order contracts.
- Modify `tests/test_frame.py`: forest integration and shared-domain behavior.
- Modify `tests/test_sparkline.py`: numeric/temporal x and y integration, companion frames, and multi-series behavior.
- Modify `tests/test_public_api.py`: public export contract.
- Modify `README.md`: user-facing annotation examples and row-targeting explanation.
- Modify `CHANGELOG.md`: unreleased feature entry.

---

### Task 1: Typed annotation declarations and preparation

**Files:**
- Create: `src/coeftable/errors.py`
- Create: `src/coeftable/_axis.py`
- Create: `src/coeftable/annotations.py`
- Create: `tests/test_annotations.py`
- Modify: `src/coeftable/series.py:13-22,76-121,176-184`
- Modify: `src/coeftable/spec.py:48-53`
- Modify: `src/coeftable/__init__.py:1-45`
- Modify: `tests/test_series.py`
- Modify: `tests/test_public_api.py:75-95`

**Interfaces:**
- Consumes: `coeftable.format.coerce_numeric`; Narwhals `DataFrame`; existing date/datetime epoch semantics.
- Produces:
  - `Rule`, `Band`, `Annotation`, `Axis`, `AxisKind`, `Layer`.
  - `ResolvedRule`, `ResolvedBand`, `ResolvedAnnotation`, `PreparedAnnotations`.
  - `annotation_sources(annotations) -> tuple[str, ...]`.
  - `prepare_annotations(annotations, frame, *, axis_kinds, plot_label, row_identities) -> PreparedAnnotations`.
  - `domain_values(marks, *, axis) -> list[float]`.

- [ ] **Step 1: Locate exported-error call sites before moving their definitions**

Use LSP references for `SpecError` and `ColumnNotFoundError` in `src/coeftable/spec.py`. Record every source/test import that must continue working. The move is complete only when `coeftable.SpecError`, `coeftable.ColumnNotFoundError`, and imports through `coeftable.spec` remain valid.

- [ ] **Step 2: Write failing declaration and resolution tests**

Create `tests/test_annotations.py` with focused contracts:

```python
import datetime as dt

import narwhals as nw
import polars as pl
import pytest

from coeftable.annotations import (
    Band,
    Rule,
    annotation_sources,
    domain_values,
    prepare_annotations,
)
from coeftable.errors import SpecError


def _frame(**columns):
    return nw.from_native(pl.DataFrame(columns))


def test_annotation_sources_are_deduplicated_in_declaration_order():
    marks = (Rule("target", axis="x"), Band("low", "target", axis="x"))
    assert annotation_sources(marks) == ("target", "low")


def test_prepare_numeric_field_omits_missing_row_and_preserves_order():
    prepared = prepare_annotations(
        (Rule("target", axis="x"), Band(0.5, 1.5, axis="x")),
        _frame(target=[2.0, None]),
        axis_kinds={"x": "numeric"},
        plot_label="Plot",
        row_identities=[("A", None, None, None), ("B", None, None, None)],
    )
    assert [type(mark).__name__ for mark in prepared.by_row[0]] == [
        "ResolvedRule",
        "ResolvedBand",
    ]
    assert [type(mark).__name__ for mark in prepared.by_row[1]] == ["ResolvedBand"]
    assert domain_values(prepared.by_row[0], axis="x") == [2.0, 0.5, 1.5]


def test_prepare_temporal_literal_uses_epoch_seconds():
    prepared = prepare_annotations(
        (Rule(dt.date(1970, 1, 2), axis="x"),),
        _frame(metric=["A"]),
        axis_kinds={"x": "temporal"},
        plot_label="Trend",
        row_identities=[("A", None, None, None)],
    )
    assert prepared.by_row[0][0].at == 86_400.0


def test_reversed_field_band_names_plot_annotation_and_row():
    with pytest.raises(
        SpecError,
        match=r"Plot.*annotation 0.*row.*A.*start.*end",
    ):
        prepare_annotations(
            (Band("low", "high", axis="x"),),
            _frame(low=[2.0], high=[1.0]),
            axis_kinds={"x": "numeric"},
            plot_label="Plot",
            row_identities=[("A", None, None, None)],
        )
```

Add parametrized tests for invalid layer, dash, opacity, non-positive rule width, unsupported axis, numeric/temporal mismatch, one missing band endpoint, `affect_domain=False`, non-finite values, and duplicate/coincident marks.

- [ ] **Step 3: Run the new tests and verify the missing-module failure**

Run: `uv run pytest tests/test_annotations.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'coeftable.annotations'`.

- [ ] **Step 4: Extract cycle-free errors and temporal helpers**

Move the existing error classes without changing their messages or public identity:

```python
# src/coeftable/errors.py
class SpecError(ValueError):
    """Raised when a table specification is internally inconsistent."""


class ColumnNotFoundError(KeyError):
    """Raised when a specification names a column absent from the frame."""
```

Import them into `spec.py`, `series.py`, and `__init__.py`. Because `spec.py` imports the names, existing `from coeftable.spec import SpecError` callers continue to work.

Move `_epoch_seconds`, `_detect_temporal`, and `_coerce_temporal` from `series.py` into `src/coeftable/_axis.py`; import them back into `series.py`. Preserve timezone-aware UTC conversion, naive elapsed-time conversion, `NaT` handling, and the existing `Series.x_temporal` result exactly. Add a `tests/test_series.py` regression for aware and naive datetimes producing the same relative spacing as before.

- [ ] **Step 5: Implement immutable declarations and prepared marks**

Use these exact shapes in `annotations.py`:

```python
from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import narwhals as nw

from coeftable._axis import _coerce_temporal
from coeftable.errors import SpecError
from coeftable.format import coerce_numeric

type Axis = Literal["x", "y"]
type AxisKind = Literal["numeric", "temporal"]
type Layer = Literal["underlay", "overlay"]
type Dash = Literal["solid", "dashed", "dotted"]
type AnnotationSource = int | float | dt.date | dt.datetime | str


@dataclass(frozen=True)
class Rule:
    at: AnnotationSource
    axis: Axis
    layer: Layer = "overlay"
    affect_domain: bool = True
    color: str | None = None
    opacity: float = 1.0
    width: float = 1.0
    dash: Dash = "dashed"


@dataclass(frozen=True)
class Band:
    start: AnnotationSource
    end: AnnotationSource
    axis: Axis
    layer: Layer = "underlay"
    affect_domain: bool = True
    color: str | None = None
    opacity: float = 0.12


type Annotation = Rule | Band


@dataclass(frozen=True)
class ResolvedRule:
    at: float
    axis: Axis
    layer: Layer
    affect_domain: bool
    color: str | None
    opacity: float
    width: float
    dash: Dash


@dataclass(frozen=True)
class ResolvedBand:
    start: float
    end: float
    axis: Axis
    layer: Layer
    affect_domain: bool
    color: str | None
    opacity: float


type ResolvedAnnotation = ResolvedRule | ResolvedBand


@dataclass(frozen=True)
class PreparedAnnotations:
    by_row: tuple[tuple[ResolvedAnnotation, ...], ...]
```

Validate declaration-only fields in `Rule.__post_init__` and `Band.__post_init__`. Reject booleans as coordinate literals even though `bool` subclasses `int`. `prepare_annotations` must:

1. Validate each mark's axis exists in `axis_kinds`.
2. Expand a literal to all frame rows or read a named field once.
3. Coerce by axis kind using `coerce_numeric` or `_coerce_temporal`.
4. Skip missing rules and bands with either endpoint missing.
5. Reject reversed present bands with plot, annotation index, and row identity.
6. Append resolved marks in declaration order.

`annotation_sources` returns unique strings in declaration order. `domain_values` returns the rule position or both band endpoints only when `affect_domain=True` and the axis matches.

- [ ] **Step 6: Export the public declarations and verify compatibility**

Export `Rule` and `Band` from `coeftable.__init__`; update `tests/test_public_api.py` expected names. Keep `SpecError` and `ColumnNotFoundError` exported under their current names.

Run: `uv run pytest tests/test_annotations.py tests/test_series.py tests/test_public_api.py -q`

Expected: all selected tests pass; existing temporal series and public error imports remain unchanged.

- [ ] **Step 7: Commit the model**

```bash
git add src/coeftable/errors.py src/coeftable/_axis.py src/coeftable/annotations.py \
  src/coeftable/series.py src/coeftable/spec.py src/coeftable/__init__.py \
  tests/test_annotations.py tests/test_series.py tests/test_public_api.py
git commit -m "feat: add typed plot annotations"
```

---

### Task 2: Shared SVG annotation composition

**Files:**
- Modify: `src/coeftable/svg.py:211-229,772-862,1115-1424`
- Modify: `tests/test_svg.py:54-90,1573-1615`

**Interfaces:**
- Consumes: `ResolvedRule`, `ResolvedBand`, `ResolvedAnnotation`, `Layer` from Task 1.
- Produces:
  - Private `_PlotArea` carrying domains, projectors, and pixel bounds.
  - `_annotation_fragments(marks, *, area, layer, theme) -> list[str]`.
  - Optional `annotations: Sequence[ResolvedAnnotation] = ()` on `forest_bar`, `sparkline_multi`, and `sparkline_bar`.

- [ ] **Step 1: Write failing SVG geometry and ordering tests**

Add tests using explicit colors to distinguish custom annotations from data/reference marks:

```python
from coeftable.annotations import ResolvedBand, ResolvedRule


def _rule(*, at, axis="x", layer="overlay", color="#123456"):
    return ResolvedRule(
        at=at,
        axis=axis,
        layer=layer,
        affect_domain=True,
        color=color,
        opacity=1.0,
        width=1.0,
        dash="dashed",
    )


def test_forest_annotations_render_under_and_over_existing_bar():
    svg = forest_bar(
        1.0,
        0.5,
        1.5,
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000000",
        theme=DEFAULT,
        annotations=(
            ResolvedBand(0.25, 0.75, "x", "underlay", True, "#abcdef", 0.2),
            _rule(at=1.25),
        ),
    )
    assert svg.index("#abcdef") < svg.index("#000000") < svg.index("#123456")
    assert '<rect x="' in svg


def test_sparkline_supports_x_rule_and_y_band_once():
    svg = sparkline_bar(
        [0.0, 1.0, 2.0],
        [1.0, 1.5, 1.0],
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000000",
        fmt=Number(),
        annotations=(
            _rule(at=1.0, axis="x"),
            ResolvedBand(0.8, 1.2, "y", "underlay", True, "#abcdef", 0.2),
        ),
    )
    assert svg.count("#123456") == 1
    assert svg.count("#abcdef") == 1
```

Also test horizontal rule geometry, vertical band geometry, partial band clipping, fully out-of-domain omission, declaration order, dotted/solid/dashed mapping, opacity/width, `color=None` theme fallback, and quote escaping in custom color attributes.

- [ ] **Step 2: Run focused tests and verify the signature failure**

Run: `uv run pytest tests/test_svg.py -q`

Expected: new tests fail because plot emitters do not accept `annotations`.

- [ ] **Step 3: Implement one private annotation emitter**

Add a private pixel-space module in `svg.py`:

```python
@dataclass(frozen=True)
class _PlotArea:
    x_domain: tuple[float, float] | None
    y_domain: tuple[float, float] | None
    project_x: Callable[[float], float] | None
    project_y: Callable[[float], float] | None
    left: float
    right: float
    top: float
    bottom: float


_DASH_ARRAY = {"solid": None, "dashed": "2,2", "dotted": "1,2"}


def _annotation_fragments(
    marks: Sequence[ResolvedAnnotation],
    *,
    area: _PlotArea,
    layer: Layer,
    theme: Theme,
) -> list[str]:
    """Project and emit one annotation layer inside `area`."""
```

For each matching-layer mark:

- Select axis domain/projector; missing projector means the plot does not support that axis and is an internal error.
- Rule: omit when outside the domain; emit a vertical or horizontal `<line>`.
- Band: intersect `[start, end]` with the domain; omit when empty; emit a `<rect>` spanning the other axis's full plot bounds.
- Escape custom colors with `html.escape(color, quote=True)`.
- Preserve declaration order by appending exactly once in input order.
- Never add clip indicators or labels for annotations.

- [ ] **Step 4: Compose annotations around existing plot content**

Add `annotations=()` to the three public-internal SVG functions without changing existing positional parameters.

- Forest `_PlotArea`: x domain/projector, `left=inset`, `right=width-inset`, `top=0`, `bottom=height`.
- Sparkline `_PlotArea`: shared x and y projectors, `left=inset`, `right=plot_width-inset`, `top=top_edge`, `bottom=bottom_edge`.
- Build `body` as `underlay_fragments + existing_body + overlay_fragments`.
- Keep the built-in reference code at its existing insertion point. Do not route it through public layer defaults.
- When `annotations` is empty, construct the same SVG body in the same order as before.
- `sparkline_bar` must forward annotations exactly once to `sparkline_multi`.

- [ ] **Step 5: Run renderer tests**

Run: `uv run pytest tests/test_svg.py -q`

Expected: all SVG tests pass, including existing clipping, ghost trace, reference, endpoint, legend, and axis tests.

- [ ] **Step 6: Commit SVG composition**

```bash
git add src/coeftable/svg.py tests/test_svg.py
git commit -m "feat(svg): compose plot annotations"
```

---

### Task 3: Forest annotation integration

**Files:**
- Modify: `src/coeftable/spec.py:443-557,1084-1163,1302-1362`
- Modify: `tests/test_frame.py:298-365`

**Interfaces:**
- Consumes: Task 1 preparation/domain helpers; Task 2 `forest_bar(..., annotations=...)`.
- Produces: `Forest.annotations: tuple[Annotation, ...]`; `CoefTable.forest(..., annotations: Sequence[Annotation] = ())`.

- [ ] **Step 1: Write failing forest integration tests**

Add a two-row end-to-end contract:

```python
from coeftable import Band, Rule


def test_forest_field_rule_targets_exactly_one_row():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue", "Latency"],
            "est": [1.0, 1.0],
            "low": [0.5, 0.5],
            "high": [1.5, 1.5],
            "target": [1.25, None],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest(
            "Plot",
            of="Effect",
            annotations=(Rule("target", axis="x", color="#123456"),),
            show_axis=False,
        )
    )
    plots = nw.from_native(resolve(table).frame)["Plot"].to_list()
    assert "#123456" in plots[0]
    assert "#123456" not in plots[1]
    assert all(plot.count("stroke-dasharray") >= 1 for plot in plots)
```

Add tests that:

- `Forest.sources()` exposes annotation fields so a missing source raises `ColumnNotFoundError` before preparation.
- `axis="y"` raises `SpecError` naming forest label and annotation index.
- A literal band appears in every non-empty row.
- `affect_domain=True` expands table/row-group/split-column/row buckets.
- `affect_domain=False` does not expand a bucket.
- `symmetric=True` covers the annotation symmetrically around `ref`.
- Explicit `ylim` wins and clips/omits marks beyond it.
- Missing estimates remain empty even when annotations are present.

- [ ] **Step 2: Run the focused forest tests and verify the builder failure**

Run: `uv run pytest tests/test_frame.py -q`

Expected: new calls fail because `CoefTable.forest()` has no `annotations` parameter.

- [ ] **Step 3: Attach prepared annotations to forest state**

Update the specification shapes:

```python
@dataclass(frozen=True)
class _ForestState:
    domains: dict[Any, tuple[float, float]]
    source: Estimate
    value: list[float | None]
    low: list[float | None]
    high: list[float | None]
    annotations: PreparedAnnotations


@dataclass(frozen=True)
class Forest:
    # existing fields unchanged
    annotations: tuple[Annotation, ...] = ()
```

`Forest.sources()` returns `annotation_sources(self.annotations)`. `CoefTable.forest()` accepts `annotations: Sequence[Annotation] = ()` and stores `tuple(annotations)`.

In `Forest.prepare`:

1. Build row identities from `scan.row_keys`, `scan.nest_keys`, `scan.group_keys`, and `scan.split_keys`.
2. Call `prepare_annotations(..., axis_kinds={"x": "numeric"}, plot_label=self.label, ...)`.
3. For each row with a non-missing estimate, append `domain_values(row_marks, axis="x")` to that row's existing bucket inputs.
4. Keep `self.ylim` as the absolute override and apply `symmetric` to the combined automatic inputs.
5. Store prepared marks in `_ForestState`.

In `Forest.cell`, retain the early blank-cell return, then pass `state.annotations.by_row[ctx.index]` to `forest_bar`.

- [ ] **Step 4: Validate forest annotations with the existing column pass**

Extend `validate_columns` only for declaration/plot compatibility that does not require frame values. Do not add a second standalone validation pass. Errors must be:

```text
Forest column 'Plot' annotation 0 uses axis='y'; forest plots support axis='x' only.
```

Field existence remains handled through `sources()` and `_check_columns`.

- [ ] **Step 5: Run forest and shared renderer tests**

Run: `uv run pytest tests/test_frame.py tests/test_svg.py tests/test_annotations.py -q`

Expected: all selected tests pass; the original unannotated forest tests remain unchanged.

- [ ] **Step 6: Commit forest support**

```bash
git add src/coeftable/spec.py tests/test_frame.py
git commit -m "feat(forest): add rule and band annotations"
```

---

### Task 4: Sparkline annotation integration

**Files:**
- Modify: `src/coeftable/spec.py:369-391,593-600,631-1078,1381-1530`
- Modify: `tests/test_sparkline.py`

**Interfaces:**
- Consumes: Task 1 preparation/domain helpers; Task 2 sparkline emitter parameters.
- Produces: `Sparkline.annotations: tuple[Annotation, ...]`; `CoefTable.sparkline(..., annotations: Sequence[Annotation] = ())`; `_bucket_domain(..., required=())`.

- [ ] **Step 1: Write failing sparkline integration tests**

Add numeric x/y and row-specific tests:

```python
from coeftable import Band, Rule


def test_sparkline_field_annotations_target_one_row_and_both_axes():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue", "Latency"],
            "value": [[1.0, 1.5, 2.0], [1.0, 0.8, 0.6]],
            "x_rule": [1.0, None],
            "guard_low": [0.9, None],
            "guard_high": [1.1, None],
        }
    )
    table = CoefTable(raw, rows="metric").sparkline(
        "Trend",
        value="value",
        annotations=(
            Rule("x_rule", axis="x", color="#123456"),
            Band("guard_low", "guard_high", axis="y", color="#abcdef"),
        ),
        show_axis=False,
    )
    plots = nw.from_native(resolve(table).frame)["Trend"].to_list()
    assert "#123456" in plots[0] and "#abcdef" in plots[0]
    assert "#123456" not in plots[1] and "#abcdef" not in plots[1]
```

Add tests for:

- Temporal literal and main-frame field x annotations align with date-series points.
- Numeric annotation on temporal x, and temporal annotation on numeric x, raise `SpecError`.
- Included x annotations expand the table-wide x domain.
- Included y annotations expand the correct row/table/group/split y bucket.
- Robust autoscaling cannot discard an included y annotation.
- `max_ylim` and explicit `ylim` can clip a distant annotation.
- Companion-frame series read annotation fields only from the main frame.
- Multi-series cells emit each annotation once, not once per arm.
- Empty single- and multi-series cells remain blank and do not contribute annotations to domains.

- [ ] **Step 2: Run focused sparkline tests and verify the builder failure**

Run: `uv run pytest tests/test_sparkline.py -q`

Expected: new calls fail because `CoefTable.sparkline()` has no `annotations` parameter.

- [ ] **Step 3: Add required-value expansion to y-domain resolution**

Change `_bucket_domain` without altering the empty-required path:

```python
def _bucket_domain(
    values: list[float],
    ref: float | None,
    *,
    override: tuple[float, float] | None,
    max_domain: float | None,
    autoscale: Autoscale,
    required: Sequence[float] = (),
) -> tuple[float, float]:
    if override is not None:
        return override
    domain = _robust_domain(values, ref) if autoscale == "robust" else _pad_domain(values, ref)
    finite_required = _finite(list(required))
    if finite_required:
        domain = _pad_domain([domain[0], domain[1], *finite_required], ref)
    return _clamp_domain(domain, ref, max_domain) if max_domain is not None else domain
```

The exact no-annotation branch must return the current domain byte-for-byte. Required values expand after robust filtering and before `max_ylim` clamps.

- [ ] **Step 4: Prepare annotations after determining sparkline x kind**

Extend `_SparklineState` with `annotations: PreparedAnnotations` and `Sparkline` with `annotations: tuple[Annotation, ...] = ()`. `Sparkline.sources()` adds main-frame annotation fields regardless of whether series data comes from list columns or `data=`.

After `series_list` determines `x_temporal`:

1. Resolve with `axis_kinds={"x": "temporal" if x_temporal else "numeric", "y": "numeric"}`.
2. Mark a row renderable when at least one arm has `_last_point(series) is not None`.
3. Add eligible x values only from renderable rows to `x_values` before resolving `x_domain`.
4. Add eligible y values only from renderable rows to a parallel required-values bucket.
5. Call `_bucket_domain(..., required=...)` for each y bucket.
6. Store prepared marks.

Keep x annotation coordinates at the shared x-domain edge when they establish a new minimum/maximum; x-domain calculation currently has no padding and remains otherwise unchanged.

- [ ] **Step 5: Pass one annotation set through each cell renderer**

Retain existing empty-cell returns. For a non-empty cell, bind:

```python
annotations = state.annotations.by_row[ctx.index]
```

Pass that tuple once to `sparkline_bar` or `sparkline_multi`. In the multi-series path, do not attach annotations to each `Trace`.

`CoefTable.sparkline()` accepts `annotations: Sequence[Annotation] = ()`, snapshots to a tuple, and documents main-frame field binding plus axis support.

- [ ] **Step 6: Run sparkline, SVG, and annotation tests**

Run: `uv run pytest tests/test_sparkline.py tests/test_svg.py tests/test_annotations.py -q`

Expected: all selected tests pass, including all existing series overlay, clipping, reference, date-axis, and domain tests.

- [ ] **Step 7: Commit sparkline support**

```bash
git add src/coeftable/spec.py tests/test_sparkline.py
git commit -m "feat(sparkline): add plot annotations"
```

---

### Task 5: Documentation and end-to-end verification

**Files:**
- Modify: `README.md:199-386`
- Modify: `CHANGELOG.md:1-15`
- Test: full repository suite and browser-rendered HTML smoke scenario.

**Interfaces:**
- Consumes: complete forest and sparkline annotation interface from Tasks 1-4.
- Produces: runnable user examples and release-facing behavior description.

- [ ] **Step 1: Add a runnable README section**

Add `## Plot annotations` after the trend examples. Document:

```python
annotated = pl.DataFrame(
    {
        "metric": ["Revenue", "Latency"],
        "estimate": [1.2, -0.4],
        "lower": [0.8, -0.8],
        "upper": [1.6, 0.1],
        # Only Revenue receives the second vertical rule.
        "target": [1.5, None],
        "trend": [[1.0, 1.2, 1.4], [-0.1, -0.3, -0.4]],
        "guard_low": [0.9, -0.6],
        "guard_high": [1.6, 0.0],
    }
)

(
    ct.CoefTable(annotated, rows="metric")
    .estimate("Effect", "estimate", ci=("lower", "upper"))
    .forest(
        "Effect plot",
        of="Effect",
        annotations=(ct.Rule("target", axis="x"),),
    )
    .sparkline(
        "Trend",
        value="trend",
        annotations=(ct.Band("guard_low", "guard_high", axis="y"),),
    )
)
```

Explain literal versus field sources, missing-value row targeting, forest/sparkline axes, underlay/overlay, `affect_domain`, and why annotations do not replace `ref`.

- [ ] **Step 2: Add an unreleased changelog entry**

Prepend:

```markdown
## Unreleased

### Features
- Add typed rule and band annotations to forest plots and sparklines, including row-specific field binding and domain-aware layering.
```

Do not modify released sections.

- [ ] **Step 3: Run targeted documentation example as code**

Run the README example in Python and call `._repr_html_()`.

Expected: no exception; returned HTML contains inline SVG for both plot columns and contains the custom rule/band colors when explicit colors are supplied.

- [ ] **Step 4: Run complete automated verification once**

Run:

```bash
make lint
make typecheck
make tests-all
```

Expected: Ruff check/format and `ty` pass; pytest passes on Python 3.12, 3.13, and 3.14 with no newly uncovered changed branches.

- [ ] **Step 5: Render and inspect the user scenario in Chromium**

Generate `/tmp/coeftable-annotation-smoke.html` from a real table containing:

- two forest rows sharing a domain;
- built-in `ref=0` on both;
- a field-bound custom x rule populated only on the first row;
- a sparkline y band and x rule;
- one underlay and one overlay with contrasting explicit colors.

Open the HTML in Chromium and verify visually:

1. First forest row has two vertical rules; second has only the built-in reference.
2. Forest interval bars remain legible and aligned to the shared footer axis.
3. Sparkline band sits behind the trajectory; overlay rule sits above it.
4. X/y annotations align with the corresponding ticks and do not enter endpoint-label space.
5. No mark escapes its SVG bounds or obscures axis labels.

Delete the temporary HTML after capture/inspection.

- [ ] **Step 6: Final review gate**

Review the complete diff against all ten acceptance criteria in the design spec. Confirm every call site, public export, test, README example, and changelog entry is updated; confirm no compatibility shim, raw-SVG escape hatch, placeholder, or unused scaffold remains.

- [ ] **Step 7: Commit docs**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: explain plot annotations"
```
