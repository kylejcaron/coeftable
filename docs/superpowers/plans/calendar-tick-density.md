# Calendar tick rung selection can yield a near-empty axis

Tracking issue: kata `w1wv`

## Context

`sparkline_axis` renders a single tick for several ordinary date spans, which is
effectively no axis at all. Reproduced on **clean** data — no gaps, no missing
values, no outliers:

```
low = 2024-01-01, high = 2024-01-30      # 29-day span
sparkline_axis(x_domain=(low, high), fmt=DateAxis(), temporal=True)
-> tick labels: ['Jan']
```

`_select_calendar_step(span, target)` computes `raw = span / target` and returns
the finest ladder rung whose *average length* is `>= raw`:

```
raw   = 29 days / 4 = 7.25 days
week  =  7.00 days -> 7.25 > 7.00, rejected
month = 30.44 days -> accepted
```

A 29-day window contains exactly one month boundary. The heuristic optimises
average **step length** against ideal spacing and never checks how many ticks
the chosen rung will actually **produce** over this domain.

Measured across the ladder (`target=4`), there are two distinct degenerate
regions, not one:

| span | rung | ticks |
|---|---|---|
| 3d | day | 4 |
| **6d** | **week** | **1** |
| **7d** | **week** | **1** |
| 10d | week | 2 |
| 25d | week | 4 |
| 28d | week | 4 |
| **29d** | **month** | **1** |
| 31d | month | 2 |
| 60d | month | 3 |
| 200d | quarter | 3 |
| 400d | year | 2 |

The 6–7 day cliff matters at least as much as the 29-day one that prompted the
report: a one-week experiment window is an entirely ordinary thing to plot.

The cliff is sharp — one step in `target_ticks` swings the 29-day case from 1
tick to 4 (`target=5` selects week instead of month).

### Two things already ruled out

- **Not related to missing data.** First noticed on a series with scattered
  `None`/`NaN` points, which made it look like ticks were dropped where data was
  missing. The reproduction above is fully clean. `_line_runs` / `_band_runs`
  are uninvolved and correct — do not go looking there.
- **`nice_ticks` (numeric path) is clean.** Swept `(0,1)` through `(0,1000)`;
  it never produced fewer than 3 ticks. Its ladder
  (`1, 2, 2.5, 5, 10 ×` powers of ten) is dense enough to bound the overshoot
  from the analogous "smallest step ≥ ideal spacing" rule. No action needed.

## Global Constraints

- `nice_ticks` stays untouched — verified clean above, and it is shared with
  `forest_axis`.
- Calendar ticks must continue to land on **real** calendar boundaries. Fixing
  density by falling back to evenly-spaced epoch offsets would defeat the
  purpose of `calendar_ticks` existing separately from `nice_ticks`.
- `DateAxis(step=...)` currently does **not** override the rung —
  `sparkline_axis` deliberately replaces a `DateAxis`'s step with whichever rung
  `calendar_ticks` picked, so labels always match the ticks drawn. Pinned by
  `test_sparkline_axis_temporal_labels_adapt_to_a_coarser_step_than_fmt_default`.
  Changing this is one candidate fix, but it is a behaviour change with an
  existing test — decide deliberately, do not drift into it.
- Commit messages: no internal tooling jargon.

## Task 1: Make rung selection density-aware

**Change:** Fix `_select_calendar_step` / `calendar_ticks` so no ordinary span
renders a near-empty axis.

Candidate approaches, pick one:
- **Step down on underflow.** Keep the current rule as a first guess, then count
  the ticks the chosen rung actually yields; if below a floor (2? 3?), step back
  down the ladder. Most direct, smallest change.
- **Select by resulting count.** Evaluate candidate rungs and pick the one whose
  actual tick count lands closest to `target`. Cleaner in principle, larger
  change, and needs a tie-break rule.
- **Let `DateAxis(step=...)` force the rung** when explicitly set. Does not fix
  the default path on its own, so at best a complement — and it contradicts an
  existing documented behaviour and its test.

Whatever is chosen, state the floor (minimum acceptable tick count) explicitly
in the code, as a named constant rather than a literal.

**Verification:** New cases in `tests/test_svg.py` asserting **tick count**, not
just position. The existing `calendar_ticks` tests all assert boundary alignment
and gap spacing, and this bug passes every one of them cleanly — count is the
property that was never checked.

Sweep spans straddling each ladder boundary (at minimum: 3, 6, 7, 10, 25, 28,
29, 31, 60, 90, 200, 400, 1000 days) and assert every one yields at least the
floor. Keep an alignment assertion alongside, so a fix that achieves density by
abandoning real calendar boundaries fails.

Also assert the two originally-reported cases directly — a 6–7 day span and a
29-day span — so the regressions are named, not merely covered by the sweep.
