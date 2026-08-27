"""Breakout switchers: swap a card subtree for an alternative decomposition.

A `Breakout` names one alternative view of a metric -- e.g. "by drivers" vs.
"by region" -- and the cards it contributes. `breakout_control` builds the
single `SelectControl` that switches between them; `partition_rules` builds
the state rules that hide every alternative except the selected one. Both
emit exactly the shape the graph kernel's shared-position proof requires: one
external keyed select whose option count matches the alternative count, and
one single-condition rule per option hiding every other option's cards.

`reject_nested_switchers` guards a shape the kernel proof does not yet cover:
a switcher nested inside another switcher's alternative, which would need a
hidden governing controller plus multi-condition partition rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from coeftable.cards import SelectControl
from coeftable.errors import SpecError
from coeftable.graph.model import Atom, ControlRef, StateRule

_OPS = ("x", "+")
type Op = Literal["x", "+"]


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


@dataclass(frozen=True, slots=True)
class Breakout:
    """One alternative decomposition: a label, its operator, and its cards."""

    key: str
    label: str
    op: Op
    children: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the breakout's identity, operator, and child cards."""
        _non_empty_str(self.key, name="Breakout.key")
        _non_empty_str(self.label, name="Breakout.label")
        if self.op not in _OPS:
            raise SpecError(f"Breakout.op must be one of {_OPS}, got {self.op!r}")
        children = _canonical(self.children, name="Breakout.children")
        if not children:
            raise SpecError("Breakout.children must not be empty")
        for index, child in enumerate(children):
            _non_empty_str(child, name=f"Breakout.children[{index}]")
        if len(set(children)) != len(children):
            raise SpecError("Breakout.children must not contain duplicates")
        object.__setattr__(self, "children", cast(tuple[str, ...], children))


def _option_label(breakout: Breakout) -> str:
    kind = "\u00d7 decomposition" if breakout.op == "x" else "+ slice"
    return f"{breakout.label} ({kind})"


def breakout_control(
    breakouts: Sequence[Breakout], *, label: str = "breakout", key: str
) -> SelectControl:
    """Build the single select that switches between `breakouts`.

    A lone alternative needs no switcher, so at least two are required.
    """
    breakouts = tuple(breakouts)
    if len(breakouts) < 2:
        raise SpecError("breakout_control requires at least two breakouts")
    options = tuple((breakout.key, _option_label(breakout)) for breakout in breakouts)
    return SelectControl(label, options, selected=breakouts[0].key, key=key)


def partition_rules(
    parent: str, key: str, breakouts: Sequence[Breakout], edges: Sequence[tuple[str, str]]
) -> tuple[StateRule, ...]:
    """Build one rule per breakout, hiding every other breakout's cards.

    Alternatives must be pairwise disjoint and equally sized: shared
    positions are proven per (layer, slot), so an overlapping or uneven
    alternative would leave a position unoccupied or doubly claimed. Hiding
    an alternative also hides everything beneath it: a child that is itself
    declared elsewhere in `edges` as having its own deeper decomposition
    does not survive as an orphan once its parent alternative is switched
    away -- unless that descendant is also reachable from the selected
    alternative (a diamond), in which case it stays visible through that
    live path.
    """
    breakouts = tuple(breakouts)
    seen: set[str] = set()
    for breakout in breakouts:
        overlap = seen & set(breakout.children)
        if overlap:
            raise SpecError(f"breakout alternatives must be disjoint, shared: {sorted(overlap)}")
        seen |= set(breakout.children)
    sizes = {len(breakout.children) for breakout in breakouts}
    if len(sizes) > 1:
        raise SpecError("breakout alternatives must have the same number of children")
    adjacency = _build_adjacency(edges)
    return tuple(
        StateRule(
            (Atom(ControlRef(parent, key), "option_checked", breakout.key),),
            hide_cards=_hidden_subtree(breakouts, index, adjacency),
        )
        for index, breakout in enumerate(breakouts)
    )


def _build_adjacency(edges: Sequence[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    """Group `edges` by source, preserving each source's per-node edge order."""
    adjacency: dict[str, list[str]] = {}
    for src, dst in edges:
        adjacency.setdefault(src, []).append(dst)
    return {node: tuple(children) for node, children in adjacency.items()}


def _reachable(start: str, adjacency: dict[str, tuple[str, ...]]) -> set[str]:
    """Return every node reachable from `start` by following directed edges."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for child in adjacency.get(node, ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _descendant_closure(
    children: Sequence[str], adjacency: dict[str, tuple[str, ...]]
) -> set[str]:
    """`children` plus everything transitively reachable from them."""
    closure: set[str] = set(children)
    for child in children:
        closure |= _reachable(child, adjacency)
    return closure


def _hidden_subtree(
    breakouts: tuple[Breakout, ...],
    selected_index: int,
    adjacency: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Descendants exclusive to unselected alternatives.

    A node reachable from an unselected alternative is only hidden if it has
    no live path from the selected alternative -- a node shared between
    alternatives (a diamond) keeps its visible path through the selection
    and must never be hidden.
    """
    visible = _descendant_closure(breakouts[selected_index].children, adjacency)
    hidden: list[str] = []
    seen: set[str] = set()
    for other_index, other in enumerate(breakouts):
        if other_index == selected_index:
            continue
        for node in _descendant_closure(other.children, adjacency):
            if node in visible or node in seen:
                continue
            seen.add(node)
            hidden.append(node)
    return tuple(hidden)


def reject_nested_switchers(
    parents_with_switchers: Sequence[str], edges: Sequence[tuple[str, str]]
) -> None:
    """Reject a breakout switcher nested inside another switcher's alternative.

    The kernel proof covers one switcher per shared-position group; a
    switcher nested inside another's alternative would additionally need a
    hidden governing controller and multi-condition partition rules, neither
    of which it provides. Switchers in disjoint branches are unaffected.
    """
    parents = tuple(parents_with_switchers)
    adjacency = _build_adjacency(edges)
    for outer in parents:
        reachable = _reachable(outer, adjacency)
        for inner in parents:
            if inner != outer and inner in reachable:
                raise SpecError(
                    "at most one breakout switcher may appear on any root-to-leaf path; "
                    f"{outer} and {inner} are nested"
                )
