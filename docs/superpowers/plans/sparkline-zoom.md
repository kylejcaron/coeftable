# Sparkline zooming: domain ceiling and outlier-robust auto-scaling

Tracking issue: kata `pcrb`

## Context

`Sparkline` (shipped, see `sparkline-column.md`) fits each row's y-domain to its
own data via `_pad_domain`. A single extreme point therefore swallows the rest
of the series: a stress test with one 300% day against an otherwise ~+5% series
rendered the spike as an isolated needle and everything else as a flat line.

The only existing lever is `domain=`, and it is too blunt for this. From
`Sparkline.prepare`:

```python
domains = {
    key: self.domain or _pad_domain(vals, self.ref) for key, vals in buckets.items()
}
```

When `domain=` is set it wins for **every** bucket key, so `scale=` is fully
overridden and the per-row computation never runs. Setting it to zoom one noisy
row also squashes every well-behaved row in the column onto that same range.

Compounding this: points outside the domain are **not** clipped visibly. They
project to their true off-canvas coordinate and are cut off by the SVG boundary.
Verified — a `y=300` point against `domain=(0, 20)` on a 30px canvas emits
`<polyline points="3.00,21.00 88.00,-333.00 173.00,19.80" .../>`. `forest_bar`
already solves exactly this for its own out-of-domain bounds with triangular
caps, "so that clipping is visible rather than silently misleading" (its
docstring). `sparkline_bar` has no equivalent.

## Global Constraints

- **Clip visibility is a precondition, not a nicety.** Both features below
  deliberately push points out of range. Neither may ship before out-of-domain
  points are visibly marked, or the feature actively lies: the user asks to zoom
  and data silently disappears.
- The current tight-fit-to-data behaviour stays the **default**. Robust scaling
  is opt-in. Silently hiding data by default is the wrong trade for a package
  whose purpose is honest uncertainty display.
- `domain=` keeps its current meaning — an absolute override. Existing callers
  must not change behaviour.
- Backend-agnostic via narwhals; no polars-only paths.
- Commit messages: no internal tooling jargon.
- `uv run pytest` must stay green throughout.

## Task 1: Visible clip indicators for out-of-domain points

kata `bbcp`. Blocks Tasks 2 and 3.

**Change:** Mark points falling outside `domain` in `sparkline_bar`, adapting
`forest_bar`'s triangular-cap treatment to the y axis and to a series rather
than a single interval.

Decide and document:
- Cap per clipped point, or one cap per contiguous clipped run?
- Ribbon behaviour when only one bound is out of domain versus both.
- Whether the line should be truncated at the domain boundary rather than drawn
  to an off-canvas coordinate. Today it is drawn off-canvas and relies on SVG
  boundary clipping, which is what produces the jagged edge artifact.
- A clipped point is **not** a gap. Do not route it through `_line_runs` /
  `_band_runs` run-splitting; a gap means "no data here", a clip means "data
  exists, off-scale". Conflating them would misreport missing data.

**Verification:** New cases in `tests/test_svg.py`. A series with a point above
the domain emits a cap; below the domain likewise; a series entirely inside the
domain emits none. Assert on the emitted marker, not merely that the SVG parses.
Include a series that both clips *and* has a genuine gap, asserting the two are
rendered distinguishably.

## Task 2: `max_domain` ceiling

kata `54tv`. Blocked by Task 1.

**Change:** A ceiling on the auto-computed domain. Compute the row's natural
domain as today, then clamp to `max_domain`; if the natural domain is already
tighter, keep the tighter one. **Never widens.**

This is what makes a single column-wide setting safe where `domain=` is not: a
precise metric keeps its own tight domain untouched, while a noisy one is reined
in. It applies to the **auto path only** (the `_pad_domain` branch), per bucket,
so it composes with `scale=` instead of overriding it.

Decide and document:
- Precedence against `domain=`. Proposal: `domain=` remains an absolute override
  and wins; `max_domain` constrains only the auto path. Setting both should be
  an explicit decision — error, or documented precedence — never silently
  ignored.
- Shape: `(low, high)` tuple, or a scalar half-width around `ref`
  (`max_domain=20` meaning `ref ± 20`)? The scalar reads better for lift-style
  series centred on zero and pairs with `_pad_domain`'s existing `symmetric=`
  keyword, which `Sparkline` has never adopted. The tuple is more general.
- Ordering against `_pad_domain`'s ref-forcing and padding — clamping after
  padding risks the padding pushing back outside the ceiling.

**Verification:** New cases in `tests/test_sparkline.py`. The motivating
two-row case is the key test: a precise row and a noisy row in one column, with
`max_domain` set — assert the precise row's projected extent is **unchanged**
from the no-`max_domain` render, while the noisy row's is clamped. Also: a
natural domain already tighter than the ceiling is left alone; `max_domain`
composes with each `scale=` value rather than overriding it.

## Task 3: Optional outlier-robust auto-domain

kata `9pyx`. Blocked by Task 1. Independent of Task 2.

**Change:** An opt-in auto-domain strategy for series where a few extreme points
make the rest unreadable.

Candidate strategies, none yet chosen — evaluate and pick one:
- Percentile domain, e.g. `[q05, q95]` of pooled `y`/`lower`/`upper`.
- IQR / Tukey fence (`q1 - k*IQR`, `q3 + k*IQR`), adapting to spread rather than
  assuming a fixed tail fraction.
- Trimmed extremes: drop the *n* most extreme points, fit the remainder.

Evaluate each against:
- **Short series.** A 3-point series has no meaningful `q05`.
- **Outlier as the last point.** Verified false alarm: `role_for` resolves the
  row's colour from the last valid point's raw value directly, never from the
  plotted domain, so excluding that point from the domain does not miscolour
  the row — it clips at the domain edge and is flagged via the existing
  clip-indicator mechanism (Task 1) instead. Not a design constraint; still
  worth an explicit test so a future change doesn't accidentally couple the
  two.
- All-identical values (degenerate spread, zero IQR).
- Whether `ref` must still be forced into the domain, as `_pad_domain` does now.

Shape: prefer a named strategy over a bool, e.g.
`autoscale="tight"` (default) `| "robust"`, so it stays extensible — a bool
forces a second bool later.

Composition: robust domain first, then Task 2's ceiling clamps it.

**Verification:** New cases in `tests/test_sparkline.py`. The 300%-spike series
renders with the bulk of the series legible (assert the projected extent of the
non-outlier points spans a meaningful fraction of the cell, not a flat line);
the default stays tight-fit and unchanged; each edge case above is covered;
composition with `max_domain` clamps as expected.

## Out of scope

Log scaling, per-row `domain=` overrides, and interactive/hover zoom. Each is a
separate design decision, not a side effect of this work.
