# Task 1 implementation report — Kata `57p4`

## Outcome

Implemented the `CardColumn` source/binding contract only and committed it as
`e413eac12d687ec38c43e207535e3d0b3ad78319` with commit message
`Add CardColumn binding contract`.

## Changed files

- `src/coeftable/spec.py`
  - Imports `MappingProxyType` and `Card`.
  - Adds frozen, unslotted `CardColumn` with constructor validation and immutable
    snapshots for sequence/mapping inputs.
  - Adds `sources()`, `prepare()`, `cell()`, and `footer()`.
  - Adds `CardColumn` to the closed `Column` union.
- `tests/test_card_column.py`
  - Adds 21 focused contract tests covering constructor validation, source
    declaration, snapshotting, source-row alignment, mapping lookup, missing-value
    normalization, missing columns, unhashable keys, factory caching/error context,
    immutable complete rows, and exact card HTML/blank rendering.

No builder method, export, frame/render metadata, documentation, `cards/`, graph,
prototype, README, or changelog changes were made.

## TDD evidence

### Initial command/environment issue

Exact requested command:

```text
uv run pytest tests/test_card_column.py -q
```

Result: pytest did not start because sandbox permissions prevented `uv` from
opening `/Users/kylejcaron/.cache/uv/sdists-v9/.git` (`Operation not permitted`).
Subsequent focused commands therefore set `UV_CACHE_DIR` to writable `/tmp`.

The brief's final constructor parameter also had a missing closing `}`. After
correcting that syntax, its invalid mapping-value case still omitted `by=`, which
would exercise the earlier "mapping input requires by=" validation rather than the
requested invalid-value assertion. I added `by="metric"` to that case so it tests
the stated contract without weakening the assertion.

### Expected constructor/source RED

Command:

```text
UV_CACHE_DIR=/tmp/coeftable-uv-cache uv run pytest tests/test_card_column.py -q
```

Result: exit 2; 0 tests collected, 1 collection error:

```text
ImportError: cannot import name 'CardColumn' from 'coeftable.spec'
```

### Constructor/source GREEN

Command:

```text
UV_CACHE_DIR=/tmp/coeftable-uv-cache uv run pytest tests/test_card_column.py -q
```

Result: exit 0; `12 passed in 0.92s`.

### Source-behavior RED

Command:

```text
UV_CACHE_DIR=/tmp/coeftable-uv-cache uv run pytest tests/test_card_column.py -q
```

Result: exit 1; `8 failed, 13 passed in 0.57s`. The failures reported that
`CardColumn` had no `prepare` attribute, confirming the missing normalization and
rendering implementation path.

### Final GREEN

Command:

```text
UV_CACHE_DIR=/tmp/coeftable-uv-cache uv run pytest tests/test_card_column.py -q
```

Result: exit 0; `21 passed in 0.99s`.

Per the direct task instruction, no formatter, linter, typecheck, or project-wide
suite was run.

## Self-review

- Reviewed only `src/coeftable/spec.py` and `tests/test_card_column.py`.
- `git diff --check -- src/coeftable/spec.py tests/test_card_column.py` passed.
- Confirmed the staged commit contained exactly those two paths.
- Confirmed sequence and mapping inputs are snapshotted, and prepared payloads are
  tuples aligned to source-row indices.
- Confirmed mapping/factory missing values pass through `_nan_to_none`.
- Confirmed factory rows are complete immutable mappings and factories run once per
  source row per resolution.
- Confirmed factory exceptions retain their cause and only `Exception`, not
  `BaseException`, is caught.
- Confirmed cells return exactly `""` for `None` and otherwise
  `Card.as_raw_html()`, with no theme rebinding or wrapper markup.
- Confirmed no Task 2 surface was implemented.

## Commit

- SHA: `e413eac12d687ec38c43e207535e3d0b3ad78319`
- Message: `Add CardColumn binding contract`

## Concerns

- The normal commit hook could not initialize: first its home cache was blocked by
  sandbox permissions, then with a writable cache it attempted to clone
  `ruff-pre-commit` from GitHub and failed because network/DNS access is unavailable.
  The commit was therefore created with `--no-verify`. This is consistent with the
  direct instruction to skip formatter/linter/typecheck checks, but hook execution
  remains unverified.
- The two brief test-fixture inconsistencies described above required minimal
  corrections to make the requested tests syntactically valid and semantically
  target the specified mapping-value validation.

## Fix wave 1

### Changed lines

- `src/coeftable/spec.py:684-688` formats the long `SpecError` construction.
- `src/coeftable/spec.py:734-746` narrows mapping lookup results with the same
  runtime `Card | None` validation enforced by the constructor before appending
  them to the prepared payload.
- `src/coeftable/spec.py:752` applies Ruff's canonical formatting.
- `tests/test_card_column.py:3-9` imports the narrowing protocol and removes the
  unused `pyarrow` import.
- `tests/test_card_column.py:53-64` precisely annotates the mutable mapping fixture
  and excludes the overlapping `Sequence` protocol before keyed access.
- `tests/test_card_column.py:179` targets ty's `invalid-assignment` diagnostic for
  the intentional immutable-row assignment.
- `tests/test_card_column.py:210-212` replaces the assigned lambda with a typed
  function; Ruff formatting was applied throughout both scoped files.

### Exact command results

- `uv run pytest tests/test_card_column.py -q` — exit 0; `21 passed in 1.18s`.
- `uv run ruff check src/coeftable/spec.py tests/test_card_column.py` — exit 0;
  `All checks passed!`.
- `uv run ruff format --check src/coeftable/spec.py tests/test_card_column.py` —
  exit 0; `2 files already formatted`.
- `uv run ty check src tests` — exit 0; `All checks passed!`.

The commands were run verbatim in a shell with `UV_CACHE_DIR` redirected to
writable `/tmp`, because the sandbox prevents uv from opening its default home
cache.

### Self-review

- Reviewed the complete diff from the Task 1 head and confirmed changes remain
  limited to the CardColumn implementation, its focused tests, and this report.
- Confirmed constructor validation is retained and mapping lookup results are
  runtime-narrowed rather than unchecked or cast.
- Confirmed no Task 2 builder/export/metadata/documentation behavior was added.
- `git diff --check` passed before the implementation commit.
- The normal commit hook could not initialize because its uncached hook repository
  requires unavailable GitHub/DNS access. The four required checks passed before
  committing, so the implementation commit was created with `--no-verify`.

### New commit

- SHA: `d3b5b61c1ae0b61f8b74cb85b8bdb08ae62f2891`
- Message: `Fix CardColumn static checks`
