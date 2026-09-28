# Task 2 Report: Table sparkline y-axis integration

## Implementation summary
- Added `Sparkline.show_y_axis` (default `False`) and `Sparkline.y_axis_fmt` (default `None`), plus `_SparklineState.y_axis_gutter`.
- Imported and reused Task 1's `_sparkline_y_axis_gutter` measurement helper.
- Computed one gutter from all resolved column domains when the in-cell y-axis is enabled, preserving shared x alignment across rows.
- Forwarded `show_y_axis`, `y_axis_fmt`, and the shared private gutter through the single-trace, explicit one-trace multi, and overlaid-series multi renderer paths.
- Added matching `CoefTable.sparkline` builder keywords and documented that `show_axis` controls the shared x footer while `show_y_axis` controls the in-cell value scale.
- Added table behavior tests for opt-in compatibility, shared gutter alignment, formatter independence, and overlaid rendering.

## Changed files
- `src/coeftable/spec.py`
- `tests/test_sparkline.py`
- `.superpowers/sdd/task-2-report.md`

## TDD RED/GREEN evidence
- RED command: `uv run pytest tests/test_sparkline.py -q -k "table_y_axis or overlaid_table_sparkline_renders_one_y_axis"`
- RED result: 4 failed, 137 deselected. Failures were the expected `TypeError: CoefTable.sparkline() got an unexpected keyword argument 'show_y_axis'`.
- GREEN command: same focused command after implementation.
- GREEN result: 4 passed, 137 deselected.

## Regression and final tests
- `uv run pytest tests/test_sparkline.py tests/test_frame.py tests/test_collapsible.py -q` — 231 passed.
- `uv run pytest -q` — 1633 passed.

## Self-review
- Confirmed disabled y-axis output remains byte-identical through the new opt-in test.
- Confirmed the widest formatted label produces one column-wide gutter and equal first/last polyline x coordinates across rows.
- Confirmed y-axis formatting is independent from endpoint and x-axis formatters.
- Confirmed all three table cell rendering paths receive the shared gutter and y-axis settings.
- Confirmed existing annotation-domain and overlay tests remain green after restoring their original forwarding paths.

## Concerns
- None identified. The required `roborev` workflow is controller-owned and was not run per assignment instructions.
