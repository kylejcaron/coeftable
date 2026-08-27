"""``DriverTree``: the composition root assembling every R4 cluster.

This is the one module in the graph package allowed to import all of its
siblings. Honesty statistics (``honesty.py``), timeline fan-out
(``timeline.py``), breakout switching (``breakout.py``), and the report
composite (``report.py``) stay mutually independent -- ``DriverTree`` is
where their outputs meet, and nowhere else. Everything it does is glue over
already-public primitives: it derives a topology from ``breakouts``, applies
the honesty thresholds from ``coeftable.graph.honesty`` per decomposition,
formats one wire per real parent/child edge, lays every card out with the
same layered barycenter helpers ``MetricTree`` uses (giving every breakout
alternative's children the *same* (layer, slot) coordinates so the kernel's
shared-position proof accepts them), wires up ``breakout_control`` /
``partition_rules`` per switcher, and finally wraps the ``Graph`` in a
``GraphReport`` whose header is a timeline strip sized to the canvas.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from coeftable.cards import (
    DEFAULT_CHROME,
    Adornment,
    Badge,
    Callout,
    Card,
    CardChrome,
    Events,
    Metric,
    Region,
    SelectControl,
    TextBlock,
    Trend,
)
from coeftable.errors import SpecError
from coeftable.format import Format, Number
from coeftable.graph.breakout import (
    Breakout,
    breakout_control,
    partition_rules,
    reject_switcher_conjunctions,
)
from coeftable.graph.honesty import (
    RESIDUAL_FAIL,
    RESIDUAL_WARN,
    endpoint_interval,
    identity_gap,
    implied_series,
    log_ratio,
    ribbon_bounds,
    ribbon_domain,
    tradeoff_pairs,
)
from coeftable.graph.metric_tree import _label, _layers, _slots
from coeftable.graph.model import Graph, Slot, Slotted, StateRule, Wire
from coeftable.graph.report import GraphReport
from coeftable.graph.timeline import TimelineEvent, events_for, timeline_strip
from coeftable.graph.topology import check_acyclic, is_acyclic
from coeftable.theme import DEFAULT, Direction, Role, Theme, role_for

_DIRECTIONS: tuple[Direction, ...] = ("higher_is_better", "lower_is_better", "neutral")

# The card headline (Metric) always uses a fixed internal number format --
# it is not user-configurable. `fmt` formats edge contribution labels only;
# `level_fmt` (see `DriverTree`) formats the raw level shown by each card's
# sparkline trend and its endpoint label. Keeping the two distinct matters:
# `fmt` is commonly a percentage, and a level is dollars, users, or a ratio.
_HEADLINE_FORMAT = Number(decimals=1)

# `Trend.fmt`'s own default when a caller passes no `level_fmt`: a plain,
# unsigned number -- never a percentage, since the value it formats is a
# raw level, not a contribution share.
_LEVEL_FORMAT = Number(decimals=1)

_CARD_WIDTH = 300

# Wide enough that a moderate-length caller-supplied caption sentence does
# not awkwardly wrap after just a word or two. Applied only to a root card
# that actually carries a caption -- a root card with none stays the same
# width as every other card.
_ROOT_CARD_WIDTH = 560


def _render_caption(text: str, *, weeks: str) -> str:
    """Substitute a literal ``{weeks}`` placeholder into `text`.

    A caller-supplied caption is arbitrary text, not a template this
    module controls, so it must never be run through `str.format`: any
    other brace in it (say, a literal ``{`` the caller wants shown
    verbatim) would either raise or silently demand an unrelated
    substitution. Plain substring replacement only ever touches the one
    placeholder this module knows about and leaves everything else --
    including unrelated braces -- untouched.
    """
    return text.replace("{weeks}", weeks)


def _non_empty_str(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{name} must be a non-empty str")


def _canonical(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot an input sequence while presenting malformed inputs as specs."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise SpecError(f"{name} must be a finite number")
    return result


def _operator_badge_text(op: str) -> str:
    return "\u00d7 decomposition" if op == "x" else "+ slice"


@dataclass(frozen=True, slots=True)
class _Residual:
    """A computed, injected residual node: an accounting leftover, not data."""

    id: str
    values: tuple[float, ...]
    subtitle: str


@dataclass(slots=True)
class _Topology:
    """The node/edge shape derived from `breakouts`, built up incrementally."""

    parents: tuple[str, ...]
    breakout_map: dict[str, tuple[Breakout, ...]]
    node_order: list[str] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    roots: tuple[str, ...] = ()
    switcher_parents: tuple[str, ...] = ()

    def add_node(self, node_id: str) -> None:
        """Append `node_id` once, in first-seen order."""
        if node_id not in self.seen:
            self.seen.add(node_id)
            self.node_order.append(node_id)


@dataclass(slots=True)
class _HonestyOutcome:
    """Per-decomposition results of the honesty pass (cluster A)."""

    residuals: dict[tuple[str, str], _Residual] = field(default_factory=dict)
    gap_badges: dict[str, list[str]] = field(default_factory=dict)
    tradeoff_callouts: dict[str, list[str]] = field(default_factory=dict)


def _validate_scalars(
    series: object,
    titles: object,
    breakouts: object,
    fmt: object,
    level_fmt: object,
    direction: object,
    chrome: object,
    caption: object,
) -> None:
    if not isinstance(series, Mapping):
        raise SpecError("DriverTree.series must be a mapping")
    if not isinstance(titles, Mapping):
        raise SpecError("DriverTree.titles must be a mapping")
    if not isinstance(breakouts, Mapping):
        raise SpecError("DriverTree.breakouts must be a mapping")
    if not callable(fmt):
        raise SpecError("DriverTree.fmt must be callable")
    if not callable(level_fmt):
        raise SpecError("DriverTree.level_fmt must be callable")
    if direction not in _DIRECTIONS:
        raise SpecError("DriverTree.direction must be valid")
    if not isinstance(chrome, CardChrome):
        raise SpecError("DriverTree.chrome must be a CardChrome")
    if caption is not None and not isinstance(caption, str):
        raise SpecError("DriverTree.caption must be a str or None")


def _format_period_count(span: float) -> str:
    """Render a period span for a caption's `{weeks}` placeholder: whole numbers stay bare."""
    if span == int(span):
        return str(int(span))
    return f"{span:g}"


def _prepare_x(x: Sequence[float]) -> tuple[tuple[float, ...], tuple[float, float], float]:
    """Canonicalize and validate `DriverTree.x`.

    `x` must be strictly increasing -- duplicate or descending coordinates
    would silently disconnect the right-hand endpoint label from the last
    observation, so both are rejected outright rather than tolerated.
    `x` must also be evenly spaced: every credibility statistic downstream
    (`honesty.weekly_log_changes`, `level_noise`, `ribbon_bounds`, the
    trade-off and role checks built on them) treats each adjacent pair of
    observations as one equal period of a per-period multiplicative noise
    model, so unequal gaps would silently mis-scale that model rather than
    generalizing it. Irregular spacing is therefore rejected, naming the
    offending index and the two differing gaps, rather than accepted and
    mislabeled. Gaps are compared with a relative tolerance plus an
    absolute floor scaled to the coordinates' own floating-point
    resolution at that magnitude, rather than bit-for-bit or
    relative-only: mathematically uniform coordinates whose gaps differ
    only in the last bits of binary rounding (e.g. `0.1, 0.2, 0.3`) are
    still accepted, and so is that same uniformity after a large shift of
    origin, where subtracting two similarly large coordinates loses
    absolute precision that swamps a purely relative tolerance sized to
    the (small) gap alone. That absolute floor is a small multiple of
    `math.ulp(magnitude)` -- the local gap between representable floats
    at that magnitude -- not a fixed fraction of the magnitude itself:
    a fraction would grow linearly with the origin and eventually
    swallow real irregularity (at a magnitude of `1e9`, `1e-9 *
    magnitude` is about `1`, so gaps of `1` and `2` would compare equal),
    whereas `math.ulp` tracks only the cancellation error actually
    incurred by the subtraction. A gap that differs by more than that
    combined tolerance is real irregularity, not rounding. A caption's
    `{weeks}` placeholder, if used, substitutes the coordinates' own span
    (`x[-1] - x[0]`), measured directly from the endpoints rather than
    recomputed as `(len(x) - 1)` times the shared gap -- the two are only
    approximately equal once the tolerated per-gap rounding is accounted
    for, not exactly equal.
    """
    raw = _canonical(x, name="DriverTree.x")
    x_values = tuple(_finite(value, name="DriverTree.x") for value in raw)
    if len(x_values) < 3:
        raise SpecError("DriverTree.x must have at least 3 observations")
    gap = x_values[1] - x_values[0]
    magnitude = max(abs(value) for value in x_values)
    for index in range(1, len(x_values)):
        previous, current = x_values[index - 1], x_values[index]
        if current <= previous:
            raise SpecError(
                "DriverTree.x must be strictly increasing: "
                f"x[{index}]={current!r} is not greater than x[{index - 1}]={previous!r}"
            )
        this_gap = current - previous
        if not math.isclose(this_gap, gap, rel_tol=1e-9, abs_tol=4 * math.ulp(magnitude)):
            raise SpecError(
                "DriverTree.x must be evenly spaced: "
                f"x[{index}] - x[{index - 1}]={this_gap!r} differs from the first gap "
                f"x[1] - x[0]={gap!r}"
            )
    return x_values, (x_values[0], x_values[-1]), x_values[-1] - x_values[0]


def _build_breakout_map(
    breakouts: Mapping[str, Sequence[Breakout]],
) -> dict[str, tuple[Breakout, ...]]:
    breakout_map: dict[str, tuple[Breakout, ...]] = {}
    for parent in breakouts:
        _non_empty_str(parent, name="DriverTree.breakouts key")
        entries = _canonical(breakouts[parent], name=f"DriverTree.breakouts[{parent!r}]")
        if not entries:
            raise SpecError(f"DriverTree.breakouts[{parent!r}] must not be empty")
        for index, entry in enumerate(entries):
            if not isinstance(entry, Breakout):
                raise SpecError(f"DriverTree.breakouts[{parent!r}][{index}] must be a Breakout")
        breakout_map[parent] = cast(tuple[Breakout, ...], entries)
    return breakout_map


def _build_topology(breakout_map: dict[str, tuple[Breakout, ...]]) -> _Topology:
    topology = _Topology(parents=tuple(breakout_map), breakout_map=breakout_map)
    for parent in topology.parents:
        topology.add_node(parent)
        for breakout in breakout_map[parent]:
            for child in breakout.children:
                topology.add_node(child)

    all_children = {
        child
        for parent in topology.parents
        for breakout in breakout_map[parent]
        for child in breakout.children
    }
    topology.roots = tuple(
        node_id for node_id in topology.node_order if node_id not in all_children
    )
    if not topology.roots:
        raise SpecError("DriverTree topology has no root: every node is someone's child")
    topology.switcher_parents = tuple(
        parent for parent in topology.parents if len(breakout_map[parent]) >= 2
    )
    return topology


def _collect_node_series(
    topology: _Topology,
    series: Mapping[str, Sequence[float]],
    titles: Mapping[str, str],
    x_values: tuple[float, ...],
) -> dict[str, tuple[float, ...]]:
    for node_id in topology.node_order:
        if node_id not in series:
            raise SpecError(f"DriverTree.series is missing an entry for {node_id!r}")
        if node_id not in titles:
            raise SpecError(f"DriverTree.titles is missing an entry for {node_id!r}")

    node_series: dict[str, tuple[float, ...]] = {}
    for node_id in topology.node_order:
        name = f"DriverTree.series[{node_id!r}]"
        raw = _canonical(series[node_id], name=name)
        values = tuple(_finite(value, name=name) for value in raw)
        if len(values) != len(x_values):
            raise SpecError(f"DriverTree.series[{node_id!r}] must match DriverTree.x in length")
        node_series[node_id] = values
    return node_series


def _raw_edges(topology: _Topology) -> tuple[tuple[str, str], ...]:
    return tuple(
        (parent, child)
        for parent in topology.parents
        for breakout in topology.breakout_map[parent]
        for child in breakout.children
    )


def _build_rep_mapping(topology: _Topology) -> dict[str, str]:
    """Map every non-default alternative child to its default sibling.

    Alternative children of one breakout must occupy the *same* (layer,
    slot) position, so only the default alternative gets a real position;
    every other alternative's children resolve through this map to it.
    """
    rep: dict[str, str] = {}
    for parent in topology.parents:
        breakout_list = topology.breakout_map[parent]
        if len(breakout_list) < 2:
            continue
        default = breakout_list[0]
        for alt in breakout_list[1:]:
            if len(alt.children) != len(default.children):
                raise SpecError(
                    f"breakout alternatives for {parent!r} must have the same number of "
                    "children so they can share a position"
                )
            for index, child in enumerate(alt.children):
                rep[child] = default.children[index]
    return rep


def _resolve_rep(node_id: str, rep: dict[str, str]) -> str:
    current = node_id
    visited: set[str] = set()
    while current in rep:
        if current in visited:
            raise SpecError(f"breakout representative mapping cycles at {current!r}")
        visited.add(current)
        current = rep[current]
    return current


def _compute_node_roles(
    node_order: list[str], node_series: dict[str, tuple[float, ...]], direction: Direction
) -> dict[str, Role]:
    node_role: dict[str, Role] = {}
    for node_id in node_order:
        _, lower, upper = endpoint_interval(node_series[node_id])
        node_role[node_id] = role_for(lower, upper, 0.0, direction)
    return node_role


def _reserve_residual_id(
    resid_id: str,
    pair: tuple[str, str],
    seen_nodes: set[str],
    resid_ids: dict[str, tuple[str, str]],
) -> None:
    """Claim `resid_id` for `pair`, rejecting an id collision.

    Rejects collision with either a declared node or an earlier residual
    generated from a different pair. Ids are formed by joining a parent
    and a breakout key with `_`, so distinct pairs like `("a_b", "c")` and
    `("a", "b_c")` can collide on the same string; silently letting the
    second overwrite the first's card and series would be a
    data-integrity bug, not a shrug.
    """
    if resid_id in seen_nodes:
        raise SpecError(f"residual id {resid_id!r} collides with a declared node")
    prior = resid_ids.get(resid_id)
    if prior is not None:
        raise SpecError(
            f"residual id {resid_id!r} collides between breakouts {prior!r} and {pair!r}"
        )
    resid_ids[resid_id] = pair


def _endpoint_identity_gap(
    parent_series: Sequence[float], children_series: Sequence[Sequence[float]], op: str
) -> float:
    """Relative discrepancy between the parent and its implied children.

    Computed at the first and last observation only, the larger of the two.

    `identity_gap` averages that discrepancy over every observation, so a
    decomposition that tracks its parent closely for most of the window but
    diverges badly only at the endpoint still reports a small mean gap. The
    edge labels this gates are themselves computed from the endpoints alone
    (`log_ratio(child[-1], child[0])`), so whether to trust them has to be
    judged at the endpoints too, not smoothed away by an in-between average.
    """
    implied = implied_series(children_series, op)
    return max(
        abs(parent_series[0] - implied[0]) / abs(parent_series[0]),
        abs(parent_series[-1] - implied[-1]) / abs(parent_series[-1]),
    )


# Final rule (C3 + A3): a multiplicative breakout's identity gap is the
# *larger* of the mean relative discrepancy across the whole series
# (`identity_gap`) and the discrepancy at the endpoints alone
# (`_endpoint_identity_gap`). Either one exceeding `RESIDUAL_WARN` means the
# labels -- which describe the endpoint change specifically -- do not
# reconcile with the parent, so both scaling (`_compute_contributions`) and
# the badge (`_apply_breakout_honesty`) key off this same combined value:
# implied-identity scaling, and a clean unbadged card, require *both* the
# whole-series mean and the endpoints alone to agree with the parent.
def _multiplicative_identity_gap(
    parent_series: Sequence[float], children_series: Sequence[Sequence[float]]
) -> float:
    return max(
        identity_gap(parent_series, children_series, "x"),
        _endpoint_identity_gap(parent_series, children_series, "x"),
    )


def _apply_breakout_honesty(
    parent: str,
    breakout: Breakout,
    node_series: dict[str, tuple[float, ...]],
    node_role: dict[str, Role],
    titles: Mapping[str, str],
    seen_nodes: set[str],
    outcome: _HonestyOutcome,
    resid_ids: dict[str, tuple[str, str]],
) -> None:
    """Check one breakout's identity gap and trade-offs (cluster A3 + A4)."""
    parent_series = node_series[parent]
    children_series = [node_series[child] for child in breakout.children]
    gap = (
        _multiplicative_identity_gap(parent_series, children_series)
        if breakout.op == "x"
        else identity_gap(parent_series, children_series, breakout.op)
    )
    if gap > RESIDUAL_FAIL:
        coverage = (1.0 - gap) * 100.0
        raise SpecError(
            f"breakout {breakout.key!r} on {parent!r} explains {coverage:.1f}% of "
            f"{titles[parent]!r}; a decomposition explaining under 80% is not a decomposition"
        )
    if gap > RESIDUAL_WARN:
        if breakout.op == "+":
            implied = implied_series(children_series, "+")
            resid_id = f"resid_{parent}_{breakout.key}"
            _reserve_residual_id(resid_id, (parent, breakout.key), seen_nodes, resid_ids)
            resid_values = tuple(p - i for p, i in zip(parent_series, implied, strict=True))
            subtitle = f"identity residual ({gap:.0%} of {titles[parent]})"
            outcome.residuals[(parent, breakout.key)] = _Residual(resid_id, resid_values, subtitle)
        else:
            outcome.gap_badges.setdefault(parent, []).append(f"{breakout.key} gap {gap:.0%}")

    non_muted = [
        (child, node_series[child])
        for child in breakout.children
        if node_role[child] != "inconclusive"
    ]
    pairs = tradeoff_pairs(non_muted)
    if pairs:
        # Pairs are keyed by child id, not title: titles are not required to
        # be unique, so a title-keyed lookup could resolve a duplicate title
        # to the wrong sibling and host the warning on a non-participating
        # or muted card. Ids are resolved directly; titles are substituted
        # only when formatting the display text below.
        text = "\u26a0 trade-off: " + "; ".join(
            f"{titles[a]} \u2194 {titles[b]} (r={r:.2f})" for a, b, r in pairs
        )
        # Host the warning on a participating child, never on the parent. The
        # parent card is visible under every option, so a warning about one
        # alternative's siblings would survive a switch and keep naming cards
        # the reader can no longer see. A child hides and shows with its own
        # alternative, so the warning appears exactly when its subject does.
        host = pairs[0][0]
        outcome.tradeoff_callouts.setdefault(host, []).append(text)


def _apply_honesty(
    topology: _Topology,
    node_series: dict[str, tuple[float, ...]],
    node_role: dict[str, Role],
    titles: Mapping[str, str],
) -> _HonestyOutcome:
    outcome = _HonestyOutcome()
    resid_ids: dict[str, tuple[str, str]] = {}
    for parent in topology.parents:
        for breakout in topology.breakout_map[parent]:
            _apply_breakout_honesty(
                parent, breakout, node_series, node_role, titles, topology.seen, outcome, resid_ids
            )
    return outcome


def _validated_events(
    events: Sequence[TimelineEvent], *, known: set[str]
) -> tuple[TimelineEvent, ...]:
    """Snapshot events and reject references to nodes that do not exist."""
    canonical = _canonical(events, name="DriverTree.events")
    result: list[TimelineEvent] = []
    for index, event in enumerate(canonical):
        if not isinstance(event, TimelineEvent):
            raise SpecError(f"DriverTree.events[{index}] must be a TimelineEvent")
        unknown = sorted(set(event.affects) - known)
        if unknown:
            raise SpecError(
                f"DriverTree.events[{index}] ({event.label!r}) affects unknown nodes {unknown}"
            )
        result.append(event)
    return tuple(result)


def _register_residuals(
    topology: _Topology,
    outcome: _HonestyOutcome,
    node_series: dict[str, tuple[float, ...]],
    node_role: dict[str, Role],
) -> dict[str, _Residual]:
    """Fold injected residuals into the node set, and index them by id."""
    residual_by_id: dict[str, _Residual] = {}
    for resid in outcome.residuals.values():
        node_series[resid.id] = resid.values
        node_role[resid.id] = "inconclusive"
        topology.add_node(resid.id)
        residual_by_id[resid.id] = resid
    return residual_by_id


def _multiplicative_identity_delta(total_sum: float) -> float:
    """`100 * expm1(total_sum)`, the parent's change under an exact identity.

    Guards against a combined log ratio too large to express as a
    percentage without overflowing the exponential.
    """
    try:
        return 100.0 * math.expm1(total_sum)
    except OverflowError as exc:
        raise SpecError(
            f"a combined log ratio of {total_sum!r} is too large to express as a percentage"
        ) from exc


# `parent_delta / total_sum` spreads the parent's own observed percentage
# change across children in proportion to each child's share of the
# combined log change -- correct, and self-consistent (the shares always
# sum back to `parent_delta`), for any `total_sum != 0`. Two problems only
# show up as `total_sum` nears zero -- e.g. two factors that roughly offset
# (one doubling, another halving):
#
# 1. When the decomposition is genuinely *exact* (parent == product of
#    children at both endpoints), `parent_delta` is itself forced to
#    `100 * expm1(total_sum)`, so dividing two independently-observed
#    values that are both converging on zero amplifies float noise into
#    an unbounded share. `_multiplicative_identity_delta(total_sum) /
#    total_sum` sidesteps that: it is the same quantity in the
#    `expm1(total) / total -> 1` continuous-compounding limit, computed
#    from `total_sum` alone rather than from two near-zero observations,
#    so it stays smooth (no floor, no branch) across the *entire* range,
#    not just near zero.
# 2. When the decomposition is only *approximate* -- the factors' combined
#    log change cancels while the parent still moved for some other
#    reason -- that limit does not apply: forcing every share toward the
#    flat 100.0 collapses two real, offsetting moves down to a sum of
#    ~0%, silently misreporting a parent that plainly did move. In that
#    case the honest scale is still `parent_delta / total_sum`, however
#    large a number it produces, because it is the only value under which
#    the shares keep summing to what the parent actually did; the
#    decomposition's own identity gap -- the very same value that decides
#    `identity_holds` below and is reported on the parent as a badge --
#    is what tells the reader not to trust the individual factors' split.
def _multiplicative_scale(parent_delta: float, total_sum: float, identity_holds: bool) -> float:
    """Percentage-point scale applied to each child's log ratio (C3)."""
    if total_sum == 0.0:
        # The one true singularity: no finite scale can spread a nonzero
        # parent delta across children whose combined log change is
        # exactly zero. The identity's own limit is the least-wrong
        # answer available; the identity-gap badge (if the parent's
        # actual move disagrees) still surfaces the shortfall.
        return 100.0
    if identity_holds:
        return _multiplicative_identity_delta(total_sum) / total_sum
    return parent_delta / total_sum


def _compute_contributions(
    topology: _Topology,
    node_series: dict[str, tuple[float, ...]],
    residuals: dict[tuple[str, str], _Residual],
) -> dict[tuple[str, str], float]:
    """C3: additive slices vs. multiplicative log-share attribution."""
    contribution_by_edge: dict[tuple[str, str], float] = {}
    for parent in topology.parents:
        parent_series = node_series[parent]
        parent_delta = endpoint_interval(parent_series)[0]
        for breakout in topology.breakout_map[parent]:
            if breakout.op == "+":
                for child in breakout.children:
                    child_series = node_series[child]
                    contribution_by_edge[(parent, child)] = (
                        (child_series[-1] - child_series[0]) / parent_series[0] * 100.0
                    )
            else:
                children_series = [node_series[child] for child in breakout.children]
                totals = {
                    child: log_ratio(node_series[child][-1], node_series[child][0])
                    for child in breakout.children
                }
                total_sum = math.fsum(totals.values())
                # Consistency rule: implied-identity scaling and the gap badge
                # (`_apply_breakout_honesty`) are keyed off the *same*
                # `_multiplicative_identity_gap` value (see its own final-rule
                # comment), not two different discrepancy measures.
                # Implied-identity scaling is picked only when that combined
                # gap is small enough that no badge renders, so any mismatch
                # large enough to trigger the `parent_delta / total_sum`
                # fallback always surfaces the gap indicator too.
                gap = _multiplicative_identity_gap(parent_series, children_series)
                identity_holds = gap <= RESIDUAL_WARN
                scale = _multiplicative_scale(parent_delta, total_sum, identity_holds)
                for child in breakout.children:
                    contribution_by_edge[(parent, child)] = totals[child] * scale
            resid = residuals.get((parent, breakout.key))
            if resid is not None:
                contribution_by_edge[(parent, resid.id)] = (
                    (resid.values[-1] - resid.values[0]) / parent_series[0] * 100.0
                )
    return contribution_by_edge


def _build_wires(
    topology: _Topology,
    residuals: dict[tuple[str, str], _Residual],
    contribution_by_edge: dict[tuple[str, str], float],
    node_role: dict[str, Role],
    fmt: Format,
) -> list[Wire]:
    wires: list[Wire] = []

    def add_wire(src: str, dst: str) -> None:
        contribution = contribution_by_edge[(src, dst)]
        label = _label(fmt, contribution)
        role = node_role[dst]
        if role == "inconclusive":
            label = f"{label} \u00b7 ns"
        wires.append(Wire(id=f"w{len(wires)}", src=src, dst=dst, label=label, label_role=role))

    for parent in topology.parents:
        for breakout in topology.breakout_map[parent]:
            for child in breakout.children:
                add_wire(parent, child)
            resid = residuals.get((parent, breakout.key))
            if resid is not None:
                add_wire(parent, resid.id)
    return wires


def _cyclic_nodes(
    node_ids: tuple[str, ...], edges: tuple[tuple[str, str], ...]
) -> tuple[str, ...]:
    """Nodes that actually lie on a cycle (Kosaraju SCCs of size > 1, or a self-edge).

    Kahn's algorithm alone only identifies nodes that never reach indegree
    zero, which is every node stuck *downstream* of a cycle as well as the
    cycle's own members -- naming all of them would blame innocent
    descendants. Strongly connected components pin down only the nodes
    genuinely reachable from themselves.
    """
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for src, dst in edges:
        outgoing[src].append(dst)
        incoming[dst].append(src)

    finish_order: list[str] = []
    seen: set[str] = set()
    for start in node_ids:
        if start in seen:
            continue
        seen.add(start)
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(outgoing[start]))]
        while stack:
            node_id, children = stack[-1]
            child = next((c for c in children if c not in seen), None)
            if child is None:
                finish_order.append(node_id)
                stack.pop()
            else:
                seen.add(child)
                stack.append((child, iter(outgoing[child])))

    component: dict[str, str] = {}
    for root in reversed(finish_order):
        if root in component:
            continue
        component[root] = root
        frontier: list[str] = [root]
        while frontier:
            node_id = frontier.pop()
            for parent in incoming[node_id]:
                if parent not in component:
                    component[parent] = root
                    frontier.append(parent)

    self_loops = {src for src, dst in edges if src == dst}
    component_size: dict[str, int] = {}
    for root in component.values():
        component_size[root] = component_size.get(root, 0) + 1
    cyclic = {
        node_id
        for node_id in node_ids
        if component_size[component[node_id]] > 1 or node_id in self_loops
    }
    return tuple(sorted(cyclic))


def _check_layout_acyclic(
    canonical_ids: tuple[str, ...], canonical_edges: list[tuple[str, str, float | None]]
) -> None:
    """Validate the edges layout actually walks, not just the raw breakout ones.

    Collapsing a non-default alternative onto its default sibling (`rep`)
    can introduce a cycle the raw edges never had -- an alternative that
    decomposes into its own sibling's representative collapses to a
    self-edge. `_layers` recurses with no cycle guard of its own, so this
    must run before it does.
    """
    pairs = tuple((src, dst) for src, dst, _ in canonical_edges)
    if is_acyclic(canonical_ids, pairs):
        return
    cyclic = _cyclic_nodes(canonical_ids, pairs)
    raise SpecError(
        "breakout layout is cyclic once alternatives collapse to shared positions: "
        f"{', '.join(cyclic)}"
    )


def _compute_layout(
    topology: _Topology, rep: dict[str, str], residuals: dict[tuple[str, str], _Residual]
) -> tuple[Slot, ...]:
    """Reuse MetricTree's own layered barycenter helpers on the collapsed tree.

    Only the *default* alternative's children ever get a real position;
    every other alternative resolves through `rep` to it, so alternatives
    share a box by construction rather than by any hiding trick.
    """
    canonical_ids: list[str] = []
    canonical_seen: set[str] = set()
    canonical_edges: list[tuple[str, str, float | None]] = []

    def add_canonical(node_id: str) -> None:
        if node_id not in canonical_seen:
            canonical_seen.add(node_id)
            canonical_ids.append(node_id)

    for parent in topology.parents:
        rp = _resolve_rep(parent, rep)
        add_canonical(rp)
        default = topology.breakout_map[parent][0]
        for child in default.children:
            rc = _resolve_rep(child, rep)
            add_canonical(rc)
            canonical_edges.append((rp, rc, None))
        for breakout in topology.breakout_map[parent]:
            resid = residuals.get((parent, breakout.key))
            if resid is not None:
                add_canonical(resid.id)
                canonical_edges.append((rp, resid.id, None))

    _check_layout_acyclic(tuple(canonical_ids), canonical_edges)
    canonical_layers = _layers(tuple(canonical_ids), tuple(canonical_edges))
    canonical_slots = _slots(tuple(canonical_ids), tuple(canonical_edges), canonical_layers)
    canonical_position = {slot.card_id: slot for slot in canonical_slots}

    return tuple(
        Slot(
            node_id,
            canonical_position[_resolve_rep(node_id, rep)].layer,
            canonical_position[_resolve_rep(node_id, rep)].slot,
        )
        for node_id in topology.node_order
    )


def _residual_edges(
    residuals: dict[tuple[str, str], _Residual],
) -> tuple[tuple[str, str], ...]:
    """One `(parent, resid.id)` edge per injected residual, in registration order."""
    return tuple((parent, resid.id) for (parent, _breakout_key), resid in residuals.items())


def _build_switcher_state(
    topology: _Topology,
    residuals: dict[tuple[str, str], _Residual],
    edges: tuple[tuple[str, str], ...],
) -> tuple[list[StateRule], dict[str, SelectControl]]:
    rules: list[StateRule] = []
    select_controls: dict[str, SelectControl] = {}
    for parent in topology.switcher_parents:
        key = f"{parent}_breakout"
        breakout_list = topology.breakout_map[parent]
        select_controls[parent] = breakout_control(breakout_list, key=key)
        residual_children = {
            breakout.key: residuals[(parent, breakout.key)].id
            for breakout in breakout_list
            if (parent, breakout.key) in residuals
        }
        rules.extend(
            partition_rules(parent, key, breakout_list, edges, residual_children=residual_children)
        )
    return rules, select_controls


def _residual_domain(values: Sequence[float]) -> tuple[float, float]:
    """Pad a residual trend's own extent; no ribbon exists to derive it from.

    An injected residual is signed -- zero where children exactly explain the
    parent, negative where they over-explain it -- so `ribbon_bounds`'s
    multiplicative noise model (which works in log space and requires
    strictly positive input) is not defined for it. Mirror `ribbon_domain`'s
    own flat-series guard instead: a flat residual has zero span, so fall
    back to the level's own magnitude, then to 1.0 for a flat-at-zero
    residual.
    """
    lo_value = _finite(min(values), name="residual domain")
    hi_value = _finite(max(values), name="residual domain")
    span = (hi_value - lo_value) or abs(hi_value) or 1.0
    lo = _finite(lo_value - 0.1 * span, name="residual domain")
    hi = _finite(hi_value + 0.1 * span, name="residual domain")
    return (lo, hi)


def _build_card(
    node_id: str,
    *,
    topology: _Topology,
    node_series: dict[str, tuple[float, ...]],
    node_role: dict[str, Role],
    titles: Mapping[str, str],
    events: Sequence[TimelineEvent],
    x_values: tuple[float, ...],
    x_domain: tuple[float, float],
    direction: Direction,
    fmt: Format,
    level_fmt: Format,
    weeks: float,
    caption: str | None,
    select_controls: dict[str, SelectControl],
    outcome: _HonestyOutcome,
    residual_by_id: dict[str, _Residual],
    chrome: CardChrome,
) -> tuple[str, Card]:
    values = node_series[node_id]
    role = node_role[node_id]
    resid = residual_by_id.get(node_id)
    if resid is not None:
        # Signed by nature (see `_residual_domain`): no multiplicative
        # ribbon is defined for it, so the card renders the trend alone.
        lower_ribbon: tuple[float, ...] | None = None
        upper_ribbon: tuple[float, ...] | None = None
        domain = _residual_domain(values)
    else:
        lower_ribbon, upper_ribbon = ribbon_bounds(values)
        domain = ribbon_domain(values, lower_ribbon, upper_ribbon)
    node_events = events_for(events, node_id)
    annotations = Events(node_events).rules() if node_events else ()
    trend = Trend(
        x=x_values,
        y=values,
        x_domain=x_domain,
        domain=domain,
        lower=lower_ribbon,
        upper=upper_ribbon,
        fmt=level_fmt,
        direction=direction,
        role=role,
        annotations=annotations,
    )
    content: list[Region | Adornment] = [Metric(values[-1], _HEADLINE_FORMAT, role=role), trend]
    if node_events:
        content.append(Events(node_events, captions=True))
    if node_id in select_controls:
        content.append(select_controls[node_id])
    if node_id in topology.breakout_map and node_id not in topology.switcher_parents:
        op = topology.breakout_map[node_id][0].op
        content.append(Badge(_operator_badge_text(op), role="neutral"))
    for badge_text in outcome.gap_badges.get(node_id, ()):
        content.append(Badge(badge_text, role="unfavorable"))
    for callout_text in outcome.tradeoff_callouts.get(node_id, ()):
        content.append(Callout(callout_text, role="unfavorable"))
    has_caption = node_id in topology.roots and caption is not None
    if has_caption:
        content.append(
            TextBlock(
                _render_caption(caption, weeks=_format_period_count(weeks)),
                variant="caption",
                max_lines=8,
            )
        )
    if resid is not None:
        title, subtitle = "Unattributed", resid.subtitle
    else:
        title, subtitle = titles[node_id], None
    width = _ROOT_CARD_WIDTH if has_caption else _CARD_WIDTH
    return node_id, Card(
        title, content=tuple(content), subtitle=subtitle, width=width, chrome=chrome
    )


def _derive_layer_gap(wires: list[Wire], chrome: CardChrome) -> int:
    """Mirror `MetricTree`'s own derived gap so labeled wires always fit."""
    labeled_indegree: dict[str, int] = {}
    for wire in wires:
        if wire.label is not None:
            labeled_indegree[wire.dst] = labeled_indegree.get(wire.dst, 0) + 1
    max_stack = max(labeled_indegree.values(), default=1) - 1
    label_offset = chrome.caption_size + 2
    label_step = chrome.caption_size + 4
    return max(56, 18 + label_offset + chrome.caption_size + label_step * max_stack)


def DriverTree(
    series: Mapping[str, Sequence[float]],
    titles: Mapping[str, str],
    breakouts: Mapping[str, Sequence[Breakout]],
    fmt: Format,
    x: Sequence[float],
    events: Sequence[TimelineEvent] = (),
    direction: Direction = "higher_is_better",
    theme: Theme = DEFAULT,
    chrome: CardChrome = DEFAULT_CHROME,
    dom_prefix: str = "g0",
    level_fmt: Format = _LEVEL_FORMAT,
    caption: str | None = None,
) -> GraphReport:
    """Build a complete driver-tree report from level series and breakouts.

    The whole topology is derived from ``breakouts``: every parent maps to
    one or more :class:`Breakout` alternatives, and the node set is every
    parent plus every alternative's children. A parent with exactly one
    breakout gets a plain, unswitched decomposition; two or more make it a
    switcher, rendered as a native ``<select>`` with every alternative's
    children sharing one (layer, slot) position so only one subtree is ever
    visible at a time -- proven by the kernel's shared-slot rules, not by
    hiding logic this module invents.

    ``fmt`` formats edge contribution labels (commonly a percentage share
    of the parent's change). ``level_fmt`` formats each card's own raw
    level -- the value plotted by its sparkline trend and its endpoint
    label -- and defaults to a plain, unsigned number since a level is
    dollars, users, or a ratio, never a contribution share.

    ``x`` must be strictly increasing and evenly spaced (no duplicate,
    descending, or irregular coordinates): a caller-supplied caption's
    ``{weeks}`` placeholder, if used, describes the realized change over
    ``x[-1] - x[0]`` "weeks", and every credibility statistic downstream
    treats each adjacent pair as one equal noise-model period, so unevenly
    spaced ``x`` would silently mis-scale those statistics rather than
    generalizing them, and is rejected instead.

    ``caption`` is optional text placed on the root card. It defaults to
    ``None``, so nothing renders unless a caller supplies one -- this
    module ships no built-in wording of its own. A supplied string renders
    verbatim. A ``{weeks}`` placeholder in it is substituted with the
    observed period count (by plain substring replacement, never
    `str.format`, so any other brace in the string is left untouched
    rather than risking a format error).

    Every decomposition is checked against ``coeftable.graph.honesty``'s
    identity-gap thresholds: additive shortfalls above ``RESIDUAL_WARN`` get
    an injected ``"Unattributed"`` residual card, multiplicative shortfalls
    are reported on a badge instead (a ratio gap has no subtraction fix), and
    anything above ``RESIDUAL_FAIL`` refuses to build. Every edge label's
    role comes from the *child's own* noise-aware interval, never from the
    raw contribution sign, so a confident-looking number backed by noisy
    data still renders muted with a ``" · ns"`` marker.
    """
    _validate_scalars(series, titles, breakouts, fmt, level_fmt, direction, chrome, caption)
    x_values, x_domain, weeks = _prepare_x(x)

    breakout_map = _build_breakout_map(breakouts)
    topology = _build_topology(breakout_map)
    node_series = _collect_node_series(topology, series, titles, x_values)
    edges = _raw_edges(topology)

    # Cheapest possible failure first: the layered-barycenter layout below
    # walks parent chains recursively and never terminates on a cycle, so
    # this must run before any statistics or layout work touches `edges`.
    check_acyclic(topology.node_order, edges)

    # `reject_switcher_conjunctions` runs before any honesty arithmetic, so
    # the clearest error (naming the descendant and its two independent
    # gating switchers) surfaces first. Ordinary nesting is supported: an
    # ancestor's own rule already covers a nested switcher whenever its
    # excluding option is the branch carrying it. What still gets refused
    # is a card whose visibility depends on two switcher gates that
    # neither one subsumes -- unrelated switchers or a nested switcher
    # reached through some other branch of its own ancestor alike.
    reject_switcher_conjunctions(topology.breakout_map, edges)

    rep = _build_rep_mapping(topology)
    node_role = _compute_node_roles(topology.node_order, node_series, direction)
    outcome = _apply_honesty(topology, node_series, node_role, titles)
    residual_by_id = _register_residuals(topology, outcome, node_series, node_role)

    contribution_by_edge = _compute_contributions(topology, node_series, outcome.residuals)
    wires = _build_wires(topology, outcome.residuals, contribution_by_edge, node_role, fmt)
    final_slots = _compute_layout(topology, rep, outcome.residuals)

    # Residual nodes joined the topology already, in `_register_residuals`.
    # `_build_wires` and `_compute_layout` above each already constructed
    # their own parent-to-residual edges (for rendering and for layout,
    # respectively); this builds a third copy scoped just to switcher
    # descendant traversal, so a nested descendant's own residual does not
    # leak as a visible orphan once its owner is switched away.
    switcher_edges = edges + _residual_edges(outcome.residuals)
    rules, select_controls = _build_switcher_state(topology, outcome.residuals, switcher_edges)

    # Validate events only now: the node set is not final until residuals have
    # been registered, and an event may legitimately target one. A misspelled
    # id would otherwise leave the event on the shared strip while silently
    # dropping its card marker and caption, which reads as missing data.
    events = _validated_events(events, known=set(topology.node_order))

    cards = [
        _build_card(
            node_id,
            topology=topology,
            node_series=node_series,
            node_role=node_role,
            titles=titles,
            events=events,
            x_values=x_values,
            x_domain=x_domain,
            direction=direction,
            fmt=fmt,
            level_fmt=level_fmt,
            weeks=weeks,
            caption=caption,
            select_controls=select_controls,
            outcome=outcome,
            residual_by_id=residual_by_id,
            chrome=chrome,
        )
        for node_id in topology.node_order
    ]

    graph = Graph(
        nodes=tuple(cards),
        layout=Slotted(final_slots),
        wires=tuple(wires),
        rules=tuple(rules),
        theme=theme,
        chrome=chrome,
        dom_prefix=dom_prefix,
        layer_gap=_derive_layer_gap(wires, chrome),
    )

    # The strip is sized to the graph's own measured width, after the graph
    # exists -- it cannot be known any earlier.
    strip = timeline_strip(events, x_domain=x_domain, width=graph.measure().width, theme=theme)
    return GraphReport(graph, header=(strip,))
