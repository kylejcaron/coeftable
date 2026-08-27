# Task 1 report

## Status
Complete. Commit: `e7beb44 feat: single-source card geometry through a chrome object`.

## TDD evidence
1. Appended the chrome contract tests from the brief.
2. Before implementation, ran `uv run pytest tests/test_cards.py -v`; collection failed as expected with `ModuleNotFoundError: No module named 'coeftable.cards.chrome'`.
3. Created `src/coeftable/cards/chrome.py` and replaced `src/coeftable/cards/fragments.py` with the specified chrome-aware renderer.
4. Ran `uv run pytest tests/test_cards.py -v`: 113 passed.
5. Ran `uv run pytest`: 651 passed.
6. Commit hooks passed: ruff check, ruff format, ty, branch guard, debug-statement, whitespace, EOF, TOML/YAML, and large-file checks.

## Repaired assertions
Removed exactly two parameterizations (`value-size`, `ci-size`) from `test_every_rendered_theme_value_is_escaped`. This is a legitimate clean-cutover repair: `MetricValue` font sizes now originate from integer `CardChrome.value_size` and `CardChrome.ci_size`, so `Theme.value_size` and `Theme.ci_size` are no longer renderer interpolation sites and there is no theme value to escape. Every remaining theme-field matrix case and the all-slot hostile-theme/no-ID sweep remain unchanged.

## Self-review
- `CardChrome`, `DEFAULT_CHROME`, and `line_height` follow the supplied contract; validation raises `SpecError` for invalid geometry.
- Fragments accept `chrome`, source measured geometry from it, and use exact integer line heights.
- Existing renderer invariants remain: inline styles, escaped text/theme values, no emitted DOM IDs, deterministic output, verbatim `InlineSvg`, and absolutely positioned popovers.
- The required `CardChrome.__post_init__` docstring was added solely to satisfy the repository's ruff D105 pre-commit rule.

## Chrome cutover completion
- Corrected `CardChrome` validation to use the declared float fields (`char_width_ratio`, `data_char_width_ratio`, and `leading`), while rejecting booleans and fractional integer geometry.
- Added configurable swatch thickness and gap-based label spacing; retained popover border/padding and pill radius as documented overlay-only or paint-only constants.
- Added exact item-row font sizes and integer line heights for key/value popovers.
- Added single-line ellipsis clipping for metric values and badges.
- Test evidence: `uv run pytest tests/test_cards.py -v` — 117 passed.
