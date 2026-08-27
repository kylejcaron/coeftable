# Task 2 — Panel composition layer report

## Delivered

- Added `coeftable.cards.panel` with frozen, slotted `Row`, `Pane`, `Panel`, and
  `MeasuredPanel` dataclasses.
- `Row` snapshots sequence inputs, validates exact `(item, width)` tuple cells,
  rejects nested rows and non-positive/bool widths or gaps, and caches composed
  per-cell render rows, declared row width, and max cell height during Panel
  construction.
- `Pane` and `Panel` snapshot public sequences and validate titles, widths,
  duplicate pane names, content types, shell gap, chrome, and theme at
  construction.
- `Panel.__post_init__` performs a deterministic one-shot traversal in
  header → pane heading/content/cells → footer order. Regions resolve only at
  their actual full-inner, pane, or cell width. The cached layout is consumed
  by both `measure()` and HTML rendering; `with_theme()` reconstructs and
  re-resolves the panel.
- Implemented the specified derived shell width and conditional header/footer
  dividers/spacing box model. HTML is deterministic, inline-style-only,
  overflow-visible at the shell, and uses fixed-width, top-aligned row cells.
- Moved the card render-row wrapper into `cards.fragments._wrap`; CardTemplate
  and Panel share it, preserving popover overflow and SVG line-height behavior.
- Re-exported the four panel names from `coeftable.cards` (30 exports).
- Added `tests/test_panel.py` covering construction validation, tuple
  canonicalization, frozen/slots contracts, width/height derivation, row fit
  in pane/header/footer, multi-row cell stacking, traversal ordering and
  `with_theme`, raw adornments, wrapper behavior, determinism, and layering.

## TDD evidence

1. Wrote the new panel contract tests before production implementation.
2. Ran `uv run pytest tests/test_panel.py -q`; the expected RED failure was the
   missing public `Pane` export.
3. Implemented the panel layer and wrapper extraction.
4. GREEN: `uv run pytest tests/test_panel.py tests/test_card_entry.py -q` →
   49 passed.

## Adaptations

- The shipped `fragments.py` serializer is the existing cards-internal home for
  the extracted wrapper, so `_wrap` was placed there rather than introducing a
  new internal module. This keeps the dependency graph acyclic and preserves
  the exact Card wrapper markup.
- The internal cache uses `_ResolvedContent`, `_ResolvedEntry`,
  `_ResolvedPane`, and `_PanelLayout` frozen/slotted records to keep plain
  render rows and composed-row cell tuples together without recomputing
  geometry in either public output path.
- Pane headings are represented by generated `TextBlock` declarations, while
  user declarations remain canonical fields; this provides the specified
  title/subtitle heading stack without adding a redundant `Panel.title`.

## Self-review and verification

- `uv run ruff check src/coeftable/cards/panel.py src/coeftable/cards/fragments.py
  src/coeftable/cards/template.py src/coeftable/cards/__init__.py
  tests/test_panel.py` → all checks passed.
- `uv run ty check src/coeftable/cards/panel.py src/coeftable/cards/fragments.py
  src/coeftable/cards/template.py src/coeftable/cards/__init__.py` → all checks
  passed.
- `uv run pytest tests/test_panel.py tests/test_card_entry.py -q` → 49 passed.
- Verified the default 430/442 pane width law manually: measured width is 942.
- No `coeftable.plots` import exists in `panel.py`; no top-level package or
  changelog files were modified.
- Full-suite validation and branch-level review remain the controller's final
  integration step because other Task 2/3 workers are changing the same branch.
