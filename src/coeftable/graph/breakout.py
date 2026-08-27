"""Breakout switchers: swap a card subtree for an alternative decomposition.

A `Breakout` names one alternative view of a metric -- e.g. "by drivers" vs.
"by region" -- and the cards it contributes. `breakout_control` builds the
single `SelectControl` that switches between them; `partition_rules` builds
the state rules that hide every alternative except the selected one. Both
emit exactly the shape the graph kernel's shared-position proof requires: one
external keyed select whose option count matches the alternative count, and
one single-condition rule per option hiding every other option's cards.

`reject_nested_switchers` guards two shapes the kernel proof does not cover:
a switcher nested inside another switcher's alternative, which would need a
hidden governing controller plus multi-condition partition rules; and a
descendant whose only paths run through two or more independent switchers,
which no single switcher's own liveness proof can see.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
    parent: str,
    key: str,
    breakouts: Sequence[Breakout],
    edges: Sequence[tuple[str, str]],
    *,
    residual_children: Mapping[str, str] | None = None,
) -> tuple[StateRule, ...]:
    """Build one rule per breakout, hiding every other breakout's cards.

    Alternatives must be pairwise disjoint and equally sized: shared
    positions are proven per (layer, slot), so an overlapping or uneven
    alternative would leave a position unoccupied or doubly claimed. Hiding
    an alternative also hides everything beneath it -- including a node
    declared elsewhere in `edges` as its own deeper decomposition -- unless
    that node stays reachable from one of the graph's roots along some path
    that survives this option: a diamond through the selected alternative,
    an unrelated always-visible branch, or another switcher's own default
    path all count as a live path and keep the node visible.

    `residual_children` maps a breakout's own key to an injected residual
    node hanging directly off `parent` (never a declared child of any
    breakout, so its ownership must be named explicitly); a nested
    descendant's own residual needs no such entry -- it is discovered like
    any other node, through `edges`.
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
    roots = _graph_roots(edges)
    resolved_residuals = residual_children or {}
    return tuple(
        StateRule(
            (Atom(ControlRef(parent, key), "option_checked", breakout.key),),
            hide_cards=_hidden_subtree(
                parent, breakouts, index, adjacency, roots, resolved_residuals
            ),
        )
        for index, breakout in enumerate(breakouts)
    )


def _graph_roots(edges: Sequence[tuple[str, str]]) -> frozenset[str]:
    """Nodes with no incoming edge in `edges`: the graph's own entry points."""
    nodes: set[str] = set()
    dsts: set[str] = set()
    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
        dsts.add(dst)
    return frozenset(nodes - dsts)


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
    parent: str,
    breakouts: tuple[Breakout, ...],
    selected_index: int,
    adjacency: dict[str, tuple[str, ...]],
    roots: frozenset[str],
    residual_children: Mapping[str, str],
) -> tuple[str, ...]:
    """Descendants with no live path left once this option hides its siblings.

    A node stays visible if it is still reachable from some graph root once
    every unselected alternative's own direct targets (and any injected
    residual) are cut out of the graph entirely -- not just detached from
    `parent`, but stripped of their own outgoing edges too, since this
    option forcibly hides them regardless of how else they're reached.
    Judging liveness against every surviving path, not just the selected
    alternative's own closure, is what lets a diamond or an unrelated
    always-visible branch keep a shared descendant on screen; refusing to
    walk through a forcibly hidden node is what stops a descendant whose
    only surviving route runs through one of them from being left behind,
    visible and orphaned, once that node disappears.

    That exemption never applies to an unselected alternative's own direct
    children (or its injected residual) themselves: those define the shared
    position opposite the selected alternative's own child, so they must
    always be hidden here regardless of what else can reach them. Sparing
    one would leave the position with two visible occupants. Only their
    deeper descendants are eligible for the liveness exemption.
    """
    unselected_direct: set[str] = set()
    for other_index, other in enumerate(breakouts):
        if other_index == selected_index:
            continue
        unselected_direct.update(other.children)
        resid_id = residual_children.get(other.key)
        if resid_id is not None:
            unselected_direct.add(resid_id)

    pruned_adjacency = {
        node: () if node in unselected_direct else targets for node, targets in adjacency.items()
    }
    visible = set(roots)
    for root in roots:
        visible |= _reachable(root, pruned_adjacency)

    hidden: list[str] = []
    seen: set[str] = set()
    for other_index, other in enumerate(breakouts):
        if other_index == selected_index:
            continue
        direct = set(other.children)
        resid_id = residual_children.get(other.key)
        if resid_id is not None:
            direct.add(resid_id)
        closure = _descendant_closure(other.children, adjacency)
        if resid_id is not None:
            closure.add(resid_id)
        for node in closure:
            if node in seen:
                continue
            if node not in direct and node in visible:
                continue
            seen.add(node)
            hidden.append(node)
    return tuple(hidden)


def _child_closures(
    parents: Sequence[str], adjacency: dict[str, tuple[str, ...]]
) -> dict[str, dict[str, frozenset[str]]]:
    """Map each real switcher parent to `{direct child: that child's closure}`.

    A parent with fewer than two direct children is not a real fork --
    `breakout_control` requires at least two options -- so it cannot gate
    anything and is left out entirely.
    """
    closures: dict[str, dict[str, frozenset[str]]] = {}
    for parent in parents:
        children = adjacency.get(parent, ())
        if len(children) < 2:
            continue
        closures[parent] = {
            child: frozenset({child}) | _reachable(child, adjacency) for child in children
        }
    return closures


def _grouping_spares(order: Sequence[str], reaching: frozenset[str]) -> bool:
    """Whether some equal-sized contiguous split leaves every group a reaching child.

    The real option boundaries never reach this far -- only the switcher's
    flattened, order-preserving direct-children list does -- but every
    breakout requires at least two alternatives of equal size, so the true
    grouping is necessarily one of the equal-sized contiguous splits of
    `order` (children are wired to their parent option by option, each
    option's own children in order). If even one such split leaves every
    group with at least one reaching child, the true grouping might be
    that split, in which case every selectable option keeps `node` alive
    through it and no selection could ever exclude it.
    """
    total = len(order)
    return any(
        total % size == 0
        and all(
            any(child in reaching for child in order[start : start + size])
            for start in range(0, total, size)
        )
        for size in range(1, total // 2 + 1)
    )


def _reaching_children(node: str, per_child: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """Return `node`'s reaching direct children, unless some grouping spares it.

    A parent whose children unanimously reach `node` -- or unanimously miss
    it -- cannot gate it: every option would carry the same verdict, so no
    selection changes anything (this is the `size == 1` split
    `_grouping_spares` finds trivially, since every singleton group either
    is or isn't the sole reaching child). Beyond that, `node` is only
    provably excludable by *some* selection when every equal-sized
    contiguous grouping of the children -- every candidate for the real
    option boundaries -- has at least one group with no reaching child at
    all: only then is picking that group's option guaranteed to exclude
    `node`, regardless of which grouping the switcher actually uses. A
    reaching child in every candidate group proves the opposite: `node`
    would survive any real selection, so the switcher is no gate.
    """
    reaching = frozenset(child for child, closure in per_child.items() if node in closure)
    if not reaching or _grouping_spares(tuple(per_child), reaching):
        return frozenset()
    return reaching


def _gating_switchers(
    node: str, closures: Mapping[str, Mapping[str, frozenset[str]]]
) -> dict[str, frozenset[str]]:
    """Map every switcher that gates `node` to its reaching direct children."""
    gates: dict[str, frozenset[str]] = {}
    for parent, per_child in closures.items():
        reaching = _reaching_children(node, per_child)
        if reaching:
            gates[parent] = reaching
    return gates


def _reject_orphanable_descendants(
    parents: Sequence[str],
    edges: Sequence[tuple[str, str]],
    adjacency: dict[str, tuple[str, ...]],
) -> None:
    """Reject a descendant whose only paths depend on two or more switchers.

    `partition_rules` proves liveness one switcher at a time: a descendant
    still reachable through some other, currently-unpruned path is judged
    safe by that switcher's own rule -- correctly, from its own narrow
    view. When that "other path" is itself only live because a *different*
    switcher's alternative happens to be selected, every contributing
    switcher's rule independently declines to hide the descendant, yet the
    combination that excludes all of them at once leaves it with nothing
    pointing at it. Each contributing switcher is identified at the option
    level, by every one of its direct children that reaches the
    descendant -- but only once no equal-sized grouping of those children
    could leave every option with a reaching child, since such a grouping
    would mean some option always keeps the descendant alive regardless of
    the selection. Pruning all of the identified children together (not
    just one) is what correctly simulates the exclusion, however many
    children the excluding option contributes. Finding the descendant
    still unreachable from every root after pruning proves the orphaning
    combination is real and selectable.
    """
    closures = _child_closures(parents, adjacency)
    if len(closures) < 2:
        return
    roots = _graph_roots(edges)
    candidates = {node for edge in edges for node in edge} - roots
    for node in sorted(candidates):
        gates = _gating_switchers(node, closures)
        if len(gates) < 2:
            continue
        pruned = {
            src: tuple(dst for dst in dsts if dst not in gates.get(src, frozenset()))
            for src, dsts in adjacency.items()
        }
        visible = set(roots)
        for root in roots:
            visible |= _reachable(root, pruned)
        if node not in visible:
            switchers = ", ".join(sorted(gates))
            raise SpecError(
                f"{node!r} visibility depends on more than one breakout switcher: {switchers}"
            )


def reject_nested_switchers(
    parents_with_switchers: Sequence[str], edges: Sequence[tuple[str, str]]
) -> None:
    """Reject a breakout switcher shape the kernel proof cannot cover.

    The kernel proof covers one switcher per shared-position group; a
    switcher nested inside another's alternative would additionally need a
    hidden governing controller and multi-condition partition rules,
    neither of which it provides. A descendant governed by two or more
    independent switchers is rejected too, for the reasons in
    `_reject_orphanable_descendants`. Switchers in disjoint branches that
    do not share a descendant are unaffected.
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
    _reject_orphanable_descendants(parents, edges, adjacency)
