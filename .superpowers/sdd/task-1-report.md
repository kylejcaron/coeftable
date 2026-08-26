# Task 1 report — card regions

## TDD evidence

1. Added `tests/test_regions.py` before production implementation.
2. `uv run pytest tests/test_regions.py -v` initially failed during collection with the expected `ModuleNotFoundError: coeftable.cards.regions`.
3. Implemented Task 1 non-plot regions and dispatch, then exported the public names and updated the exact-export contract.
4. A targeted run found one real regression: `Metric.ref` validation was omitted during a type-safety refactor; restored it and reran green.

## Amendment applications

- Public collection fields are `Sequence`-annotated and canonicalized to tuples: `Metric.ci`, `Diagnostics.items`, and `Events.events`.
- `Event.dash` uses `coeftable.annotations.Dash` rather than `str`.
- Added `_canonical`, which translates non-iterable container `TypeError`s into contextual `SpecError`s. Tests cover malformed `Metric.ci`, `Diagnostics.items`/item, and `Events.events` containers.
- Added the required `Events` caller-list mutation snapshot test. The original brief test list was adjusted to include the amendment-mandated malformed-container and Events snapshot cases.

## Results

- `uv run pytest tests/test_regions.py tests/test_cards.py -v`: 216 passed.
- `uv run pytest`: 754 passed.
- `uv run ruff check src/coeftable/cards/regions.py src/coeftable/cards/__init__.py tests/test_regions.py tests/test_cards.py`: passed.
- `uv run ty check src/coeftable/cards/regions.py`: passed.

## Self-review

`resolve_content` preserves adornment identity, accepts structural runtime `Region`s, and reports invalid item index/type. All region dataclasses are frozen and slotted; sequence inputs are snapshotted before validation; no plot-region scope was introduced.
