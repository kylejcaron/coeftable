# Clip indicator redesign: proper boundary clipping + ghost trace + span cap

## Motivation

The shipped clip-indicator mechanism (Task 1 of `sparkline-zoom.md`) flags a
row whenever a point falls outside its plotted `domain` — but it has two
compounding problems, found by hands-on visual review of the shipped
behaviour with real-shaped A/B test data (noisy early days, converging over
time, with a visible CI ribbon):

1. **The line/ribbon geometry itself is distorted near a clip.** The current
   `_clamp(yi, low, high)` primitive (`src/coeftable/svg.py`) clamps each
   point's *y* independently while keeping its real *x* — it does not compute
   where the connecting line segment actually crosses the domain boundary.
   This produces a visibly wrong approach angle into the clip (the line looks
   like it glides gently up to the edge and just touches it, when the real
   data spiked sharply and left the visible domain much earlier). The same
   distortion applies to the ribbon fill.
2. **The triangle badge doesn't mark where anything happened.** It sits at a
   fixed x (the row's left margin), independent of where the actual clip
   occurred, and carries no information about the true excursion.

## Chosen design

Three coordinated changes to `sparkline_bar` (line + ribbon rendering):

### 1. Proper segment/polygon boundary clipping

Replace per-point `_clamp` with true line-rectangle intersection:

- **Line:** split each real segment at the exact point it crosses `low`/
  `high` (linear interpolation on the segment, not just clamping the
  endpoint), then group the resulting in-bounds sub-segments into
  *continuous* polylines. Drawing each clipped sub-segment as its own
  `<line>` element loses proper vertex joins and produces visible notch
  artifacts at every zigzag point in the data — sub-segments belonging to
  the same continuous in-bounds run must be re-joined into one `<polyline>`.
- **Ribbon:** clip the true (unclamped) band polygon against the domain
  rectangle with Sutherland-Hodgman polygon clipping, in *domain-value*
  space (not pixel space — projected pixel y is inverted relative to domain
  value, a real bug hit during prototyping: clipping in pixel space with a
  domain-space-oriented algorithm silently produces wrong results).
- Both are additionally hard-clipped to the domain rectangle via an SVG
  `clipPath` as a second guarantee against stroke-width miter overshoot at a
  sharp vertex (confirmed necessary: a real data point sitting exactly at
  the domain boundary at a sharp angle poked a visible sliver past the edge
  without it).

### 2. Ghost trace

Draw the *true* (unclamped) line + ribbon underneath the real one, at low
opacity (`stroke-opacity="0.35"` line, `fill-opacity="0.06"` ribbon),
bounded only by the SVG canvas itself (not the domain) — it simply keeps
going until it runs off the visible row. This is not synthetic: it uses the
exact same real data points as the main render, just without the domain
clamp. Because the real (clamped) render is *also* fixed to properly clip
right at the boundary (change 1), the ghost is a seamless continuation of
the same trajectory, not a mismatched line — this was verified explicitly:
before the segment-clipping fix, ghost and main visibly kinked apart at the
clip point (main's distorted approach angle vs ghost's true angle); after
the fix, they connect with zero visible discontinuity.

The ghost is real information: it shows the reader the true magnitude/shape
of what got clipped, rather than only the fact that clipping occurred.

### 3. Cap: span-based double-line, not a fixed-width tick

Replace the triangle badge with a thin double-line (`stroke-width="0.5"`,
two lines offset `±0.5` from the domain edge) that spans the **exact pixel
x-range of each contiguous clipped stretch** — from where the ribbon/line
enters out-of-bounds to where it exits — not a small fixed-width tick
centred on a single point. When several consecutive points all clip, the
spans naturally merge into one continuous bracket rather than a cluster of
overlapping ticks.

**Trigger: ribbon-aware (this part already worked).** The shipped
pre-redesign mechanism already set its clip flag from *both* the ribbon
bound (`lower`/`upper`) and the point value — checked directly against
`08ce866`'s `svg.py`, lines 546-547 (ribbon) and 563-564 (point). A ribbon
clamped to a sliver of its true width while the point estimate stays
comfortably inside the domain already raised a flag before this redesign.
What's genuinely new is *not* the trigger's ribbon-awareness — it's
preserving that correctness while reworking everything downstream of it
(the mark's shape and position, and the geometry it's drawn against). Get
this wrong during the rewrite (e.g. narrowing back to a point-only check
while restructuring the surrounding code) and the redesign silently
regresses a real, already-shipped guarantee.

**`show_clip_indicators=False` interaction with the ghost trace.**
Decided explicitly (this was underspecified in an earlier draft of this
plan): the flag controls the cap bracket only. Proper boundary clipping
(change 1) and the ghost trace (change 2) are unconditional — they run
regardless of the flag. This preserves the existing shipped guarantee that
nothing the *real* (opaque) layer draws ever escapes the row's canvas
bounds (the flag never re-introduces an off-canvas coordinate); the ghost
trace is a separate, always-faded, informational layer that also never
escapes the canvas (verified in a real browser, not just by inspecting
coordinates: raw out-of-domain ghost coordinates can be enormous, e.g.
y=-59985 in one constructed case, and the row still rendered cleanly
confined to its own cell with zero bleed into surrounding content, because
the outermost `<svg>` clips to its own viewport by default). Covered by a
dedicated test asserting flag-off output has zero cap elements while the
ghost layer and clipped real layer are both still present.

**Position: mark the true crossing, not the real data point.** The double
line's *x* extent is derived from the properly-clipped geometry (change 1),
so it sits exactly where the line/ribbon crosses the boundary — this loses
the property that the shipped triangle had (an exact, real day is marked),
but gains geometric accuracy (the mark corresponds to where clipping
genuinely begins/ends, matching what's visually drawn).

**Visual parameters, decided by iterating against real rendered output in
all three semantic colours (favorable/green, unfavorable/red,
inconclusive/gray) at real (~30px-tall) row scale, not zoomed screenshots:**

- Colour: same as the row's resolved theme colour (not a fixed neutral),
  at `stroke-opacity="0.45"` — full opacity read as too heavy/loud for a
  small multiple; a much lighter opacity (~0.10, "between the ribbon's
  0.15 fill-opacity and the ghost's 0.06") was tested and rejected as
  **illegible, especially in gray** (blends into the ribbon at real scale).
  0.45 is clearly visible in all three colours without dominating the row.
- Span: the exact clipped x-range, extended `+3px` past each end. Tested
  exact-match (no padding) vs `+3px` wider vs `+10px` fixed-width centred
  ticks (rejected — arbitrary, doesn't track the actual clipped extent, and
  looked shifted/disconnected from the shaded region when spans were short).
- The double-line sits *only* at the domain boundary (not bracketing the
  full margin down to the canvas edge — an "I-beam" variant with end-caps
  at both the domain edge and the canvas edge was tried and rejected as
  visually busier without adding real information).

## Alternatives considered and rejected

Explored and discarded during design iteration (kept here so a future
contributor doesn't re-litigate the same dead ends):

- **Magnitude/severity encoding inside the marker** (domain-compression so
  the y-domain itself signals how severe an excursion is; discrete tick
  tallies counting order-of-magnitude severity; a slice-cut triangle whose
  cut height encodes severity) — all six variants tried failed for the
  identical reason: **a ~3px-tall marker has no room for a second signal.**
  Confirmed repeatedly: sub-pixel distinctions that read clearly at 20-50x
  zoom are completely imperceptible at the real ~30px row height. This is a
  hard physical constraint of the current row geometry, not a tuning
  problem — solving it would require deliberately growing the row's clip
  margin (a real footprint tradeoff), which is out of scope here.
- **Fade-into-margin gradient** (ribbon bleeding into the row's outer pad
  as a soft gradient instead of a hard cap line) — same physical-size
  problem: `pad=3` gives only 3 real pixels of margin, nowhere near enough
  for a perceptible gradient at real scale, confirmed by direct comparison.
- **No cap mark at all**, relying purely on the opacity difference between
  the solid reading and the faded ghost — legible in isolation but
  meaningfully softer than an explicit boundary line across all three
  colours, and depends on the reader consciously noticing a continuous
  opacity shift while skimming many rows quickly. Rejected: the whole
  reason a clip indicator exists is to avoid a clipped point being silently
  under-communicated: a soft, easy-to-miss signal reintroduces a version of
  that problem.
- **Configurable cap style** (exposing the tested styles as a user-facing
  choice) — rejected. One of the styles (the very light stroke) is simply
  broken, not a legitimate style option; between the remaining two, the
  explicit double-line is reliably legible and the "no mark" option isn't a
  concrete use case anyone asked for. Adding a style enum here is
  unjustified API surface for a narrow rendering detail; `show_clip_indicators:
  bool` (already shipped) remains the only user-facing toggle.

## Composition (unchanged)

All of the above applies uniformly regardless of *why* a point is outside
`domain` — an explicit `domain=` override, a `max_domain=` ceiling, or an
`autoscale="robust"` fit. `sparkline_bar` remains domain-provenance-agnostic:
it never needs to know which of the three produced the final `(low, high)`
tuple it receives. This was re-verified against all three trigger paths
during design iteration, each producing a correctly-positioned cap.

## Task 1: Implement in `src/coeftable/svg.py`

- Replace `_clamp`-based line/ribbon drawing in `sparkline_bar` with proper
  segment/polygon boundary clipping (line via segment-split-and-regroup,
  ribbon via Sutherland-Hodgman polygon clip in domain-value space).
- Add the ghost trace (true trajectory, low opacity, canvas-bounded).
- Replace the triangle-badge `show_clip_indicators` block with the
  span-based double-line cap, ribbon-aware trigger, at the visual
  parameters above.
- Update `Sparkline`'s docstring and `CoefTable.sparkline()`'s docstring
  for `show_clip_indicators` to describe the new mark shape and the
  ribbon-aware trigger.
- **Verification:** rewrite the existing clip-indicator test suite
  (written against the old triangle-badge + per-point-clamp behaviour) to
  assert the new contract: continuous polyline output (no notch artifacts
  from separate `<line>` elements at zigzag points), correct crossing
  x-positions (verify against hand-computed segment-boundary intersections,
  not just "some clip happened"), ribbon-only clip detection (a case where
  the point stays in-bounds but the CI bound doesn't), span-merging when
  multiple consecutive points clip, and composition with each of
  `domain=`, `max_domain=`, `autoscale="robust"`.
- Global constraint: `uv run pytest` stays green throughout.
