# Final-review fixes evidence

## Scope

Branch `feature/visible-sparkline-y-axis`, starting at `093ea3014980d0eb8e53ad3d0ac3b34f79116efa`.

## RED evidence

- `test_table_sparkline_footer_shares_y_axis_gutter[True]` and `[False]` failed before the source fix: footer tick minimum was `3.0` while the plotted polyline began at `25.2` after the y-axis gutter.
- `test_table_sparkline_positional_legacy_fields_still_render` failed before field reordering: the legacy positional `endpoint_width=55` was bound to `Sparkline.show_endpoint`.
- `test_trend_positional_legacy_fields_still_render` failed before field reordering: the legacy positional `temporal=False` was bound to `Trend.y_axis_fmt`, producing `SpecError` (`must be callable`).
- `test_sparkline_axis_zero_gutter_preserves_disabled_footer_bytes` failed before serialization compatibility was restored: disabled footer output contained `x1="3.0"` instead of the legacy `x1="3"`.

## GREEN implementation

- `Sparkline.footer()` now forwards the prepared shared `state.y_axis_gutter` through the reviewed private `_x_gutter` axis geometry. Table-level assertions cover endpoint visible and hidden paths, plus the overlaid/legend path.
- New `Sparkline` fields (`show_y_axis`, `y_axis_fmt`) and new `Trend` fields (`show_y_axis`, `y_axis_fmt`) now follow all legacy positional fields, preserving existing constructor indexes.
- `sparkline_axis()` uses the exact legacy integer inset serialization when `_x_gutter == 0.0`; nonzero gutter continues to project the baseline from the shared gutter.

## Verification

Focused regressions and relevant suites:

```text
uv run pytest -q tests/test_sparkline.py tests/test_regions.py tests/test_svg.py
421 passed
```

Quality hooks:

```text
uv run ruff check ...
All checks passed!
uv run ruff format --check ...
6 files already formatted
uv run ty check
All checks passed!
```

Full suite:

```text
uv run pytest -q
1646 passed
```
