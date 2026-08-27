"""Breakout switchers: swap a card subtree for an alternative decomposition.

A `Breakout` names one alternative view of a metric -- e.g. "by drivers" vs.
"by region" -- and the cards it contributes. `breakout_control` builds the
single `SelectControl` that switches between them; `partition_rules` builds
the state rules that hide every alternative except the selected one. Both
emit exactly the shape the graph kernel's shared-position proof requires: one
external keyed select whose option count matches the alternative count, and
one single-condition rule per option hiding every other option's cards.

A switcher nested inside another switcher's alternative is ordinary and
supported: when the ancestor's own excluding option is the branch that
carries the nested switcher, the ancestor's rule alone already hides the
nested switcher's parent -- and everything beneath it, including its own
alternatives -- without needing the nested switcher's cooperation.
Nesting grants no blanket exemption, though: `reject_switcher_conjunctions`
still refuses a card whose visibility depends on two switcher gates that
neither one subsumes, whether those two switchers sit in unrelated
branches or one is nested inside the other but reachable through some
*other*, non-excluded branch of its ancestor -- a genuine conjunction no
single switcher's own liveness proof can see.

Invariant: a topology is refused only when some selectable combination of
switcher choices leaves a card actually rendered -- never force-hidden as
some switcher's own direct child -- while no path from any graph root to
that card survives the same combination. A card that disappears together
with its own unselected alternative is hidden, not orphaned, however many
other switchers or unconditional branches also happen to reach it.
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
    """Label plus a bare operator glyph -- the fullest text a select can afford.

    A parenthetical like "(x decomposition)" reads well but doubles the
    width a select needs; the glyph alone keeps the operator visible (the
    reason it was there) at roughly 60% of that width.
    """
    glyph = "\u00d7" if breakout.op == "x" else "+"
    return f"{breakout.label} {glyph}"


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


def _visible_from_roots(roots: frozenset[str], adjacency: dict[str, tuple[str, ...]]) -> set[str]:
    """Every node reachable from some root, roots themselves included."""
    visible = set(roots)
    for root in roots:
        visible |= _reachable(root, adjacency)
    return visible


def _prune_forced_hidden(
    adjacency: dict[str, tuple[str, ...]], forced_hidden: frozenset[str]
) -> dict[str, tuple[str, ...]]:
    """Zero every forced-hidden node's own outgoing edges.

    Blocks traversal through a forced-hidden node regardless of how else it
    is reached -- the exact rule `_hidden_subtree` applies to an unselected
    alternative's own direct children, shared here so the switcher
    subsumption model in `_drop_subsumed_gates` and
    `_reject_orphanable_descendants` cannot disagree with what rule
    emission actually hides again.
    """
    return {node: () if node in forced_hidden else targets for node, targets in adjacency.items()}


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

    forced_hidden = frozenset(unselected_direct)
    visible = _visible_from_roots(roots, _prune_forced_hidden(adjacency, forced_hidden))

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


def _real_option_children(
    breakout_map: Mapping[str, Sequence[Breakout]],
) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Map each real switcher parent to its real per-option child tuples.

    A parent with fewer than two breakouts is not a real switcher --
    `breakout_control` requires at least two alternatives -- so it cannot
    gate anything and is left out entirely.
    """
    groups: dict[str, tuple[tuple[str, ...], ...]] = {}
    for parent, breakouts in breakout_map.items():
        breakouts = tuple(breakouts)
        if len(breakouts) < 2:
            continue
        groups[parent] = tuple(breakout.children for breakout in breakouts)
    return groups


def _child_closures(
    option_children: Mapping[str, tuple[tuple[str, ...], ...]],
    adjacency: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, frozenset[str]]]:
    """Map each real switcher parent to `{direct child: that child's closure}`."""
    return {
        parent: {
            child: frozenset({child}) | _reachable(child, adjacency)
            for group in groups
            for child in group
        }
        for parent, groups in option_children.items()
    }


def _reaching_children(
    node: str, per_child: Mapping[str, frozenset[str]], groups: Sequence[Sequence[str]]
) -> frozenset[str]:
    """Return `node`'s reaching direct children, unless every real option reaches it.

    A parent whose children unanimously reach `node` -- or unanimously miss
    it -- cannot gate it: every option would carry the same verdict, so no
    selection changes anything. Beyond that, `node` is only provably
    excludable by *some* selection when at least one real option -- a
    `Breakout`'s own declared children, the actual boundary, never a
    guess at where it might fall -- has no reaching child at all: only
    then is picking that option guaranteed to exclude `node`. A reaching
    child in every real option proves the opposite: `node` would survive
    any selection, so the switcher is no gate.
    """
    reaching = frozenset(child for child, closure in per_child.items() if node in closure)
    if not reaching:
        return frozenset()
    if all(any(child in reaching for child in group) for group in groups):
        return frozenset()
    return reaching


def _gating_switchers(
    node: str,
    closures: Mapping[str, Mapping[str, frozenset[str]]],
    option_children: Mapping[str, tuple[tuple[str, ...], ...]],
) -> dict[str, frozenset[str]]:
    """Map every switcher that gates `node` to its reaching direct children."""
    gates: dict[str, frozenset[str]] = {}
    for parent, per_child in closures.items():
        reaching = _reaching_children(node, per_child, option_children[parent])
        if reaching:
            gates[parent] = reaching
    return gates


def _prune_gate_edges(
    adjacency: dict[str, tuple[str, ...]], gates: Mapping[str, frozenset[str]]
) -> dict[str, tuple[str, ...]]:
    """Block traversal through every gate's reaching children.

    A reaching child is a direct child of some option that keeps the node
    it gates reachable. What excludes the node is SELECTING one of the
    switcher's non-reaching options, which force-hides every reaching
    alternative at once -- not merely leaving one reaching option
    unselected, since another reaching option could still be chosen when
    several of them reach the node.

    Those force-hidden positions are exactly what `_hidden_subtree` hides,
    regardless of any other incoming edge. Zeroing each one's own outgoing
    edges here, rather than only removing the edge from its switcher
    parent, is what keeps this reachability model from disagreeing with
    what `_hidden_subtree` actually emits: a reaching child with a second
    incoming edge from elsewhere must not read as leaving some still-live
    path past it.
    """
    forced_hidden: set[str] = set()
    for reaching in gates.values():
        forced_hidden.update(reaching)
    return _prune_forced_hidden(adjacency, frozenset(forced_hidden))


def _converge_gates(
    node: str,
    option_children: Mapping[str, tuple[tuple[str, ...], ...]],
    adjacency: dict[str, tuple[str, ...]],
) -> dict[str, frozenset[str]]:
    """Find every switcher gating `node`, including one masked by another.

    A switcher's own child can reach `node` by passing through a position
    that belongs to a *different*, nested switcher -- a position that
    switcher's own worst option would hide. Judged against the raw graph,
    that route reads as unconditional and hides the outer switcher's real
    gating role entirely: the outer switcher's *other* alternative can
    still orphan `node` in combination with the nested switcher's own
    worst option, even though neither one's own liveness proof, run in
    isolation against the unpruned graph, ever sees it. Re-deriving gates
    against a graph already pruned by every gate found so far, and
    repeating until nothing new turns up, uncovers exactly the switchers
    whose only route to `node` ran through such a position. A gate, once
    found, is never discarded even if further pruning would no longer
    rediscover it -- so the search only ever grows and always terminates.
    """
    known: dict[str, frozenset[str]] = {}
    while True:
        pruned = _prune_gate_edges(adjacency, known)
        closures = _child_closures(option_children, pruned)
        found = _gating_switchers(node, closures, option_children)
        new_parents = {parent: found[parent] for parent in found if parent not in known}
        if not new_parents:
            return known
        known = {**known, **new_parents}


def _drop_subsumed_gates(
    gates: Mapping[str, frozenset[str]],
    adjacency: dict[str, tuple[str, ...]],
    roots: frozenset[str],
) -> dict[str, frozenset[str]]:
    """Drop a gate whose entire switcher another gate already excludes alone.

    An ancestor and a nested descendant switcher are ordered, not always
    independent -- but only when the ancestor's *own* identified gate
    already excludes the descendant switcher's own parent: only then does
    the ancestor's rule alone hide everything beneath it, without needing
    the nested switcher's cooperation. That exclusion holds either because
    `parent` is itself one of the *other* gate's reaching children -- a
    direct child of an unselected option is always hidden regardless of
    what else can reach it, the same rule `_hidden_subtree` applies -- or
    because, once those reaching children are pruned `_hidden_subtree`'s
    way, `parent` has no surviving path left from any root. A nested
    switcher gating `node` through a branch the ancestor's own gate never
    touches -- a sibling alternative, not the branch carrying the nested
    switcher -- is not subsumed by it and describes a real, separate risk.
    """
    dropped: set[str] = set()
    for parent in gates:
        for other, other_reaching in gates.items():
            if other == parent:
                continue
            if parent in other_reaching:
                dropped.add(parent)
                break
            pruned = _prune_gate_edges(adjacency, {other: other_reaching})
            if parent not in _visible_from_roots(roots, pruned):
                dropped.add(parent)
                break
    return {parent: reaching for parent, reaching in gates.items() if parent not in dropped}


def _reject_orphanable_descendants(
    breakout_map: Mapping[str, Sequence[Breakout]],
    edges: Sequence[tuple[str, str]],
    adjacency: dict[str, tuple[str, ...]],
) -> None:
    """Reject a descendant whose only paths depend on two independent switchers.

    `partition_rules` proves liveness one switcher at a time: a descendant
    still reachable through some other, currently-unpruned path is judged
    safe by that switcher's own rule -- correctly, from its own narrow
    view. When that "other path" is itself only live because a *different*
    switcher's alternative happens to be selected, every contributing
    switcher's rule independently declines to hide the descendant, yet the
    combination that excludes all of them at once leaves it with nothing
    pointing at it. `_converge_gates` finds every contributing switcher,
    including one whose own gating role only appears once another
    switcher's worst option is already assumed -- the case a nested
    switcher sharing a descendant with a sibling alternative of its own
    ancestor produces, and no single-pass, unpruned reachability check can
    see. `_drop_subsumed_gates` then discards only the gates a *different*
    gate's own pruning already renders moot, never a gate whose switcher
    sits upstream in the raw graph merely by coincidence. Pruning every
    surviving gate together and finding the descendant still unreachable
    from every root proves the orphaning combination is real and
    selectable.

    A descendant that is itself a reaching child of one of its own
    surviving gates is normally not orphanable, and needs no separate
    guard: that gate's own switcher force-hides it as a direct child the
    instant a non-reaching option is selected -- the same rule
    `_hidden_subtree` applies -- so it is either hidden outright or
    visible through its own live edge.

    That is not an absolute exemption, which is why the check below still
    tests it rather than skipping it. If its switcher parent is itself
    jointly disconnected by two other surviving gates, then the parent and
    the child both become unreachable once every gate is pruned together,
    and the check correctly reports it. The reachability test is the
    authority here; being somebody's direct child only makes orphaning
    unlikely, not impossible.
    """
    option_children = _real_option_children(breakout_map)
    if len(option_children) < 2:
        return
    roots = _graph_roots(edges)
    candidates = {node for edge in edges for node in edge} - roots
    for node in sorted(candidates):
        gates = _drop_subsumed_gates(
            _converge_gates(node, option_children, adjacency), adjacency, roots
        )
        if len(gates) < 2:
            continue
        visible = _visible_from_roots(roots, _prune_gate_edges(adjacency, gates))
        if node not in visible:
            switchers = ", ".join(sorted(gates))
            raise SpecError(
                f"{node!r} visibility depends on more than one breakout switcher: {switchers}"
            )


def reject_switcher_conjunctions(
    breakout_map: Mapping[str, Sequence[Breakout]], edges: Sequence[tuple[str, str]]
) -> None:
    """Reject a descendant gated by two switcher options that neither subsumes.

    `breakout_map` maps every switcher's parent node to its own declared
    `Breakout` alternatives -- the real option boundaries, read directly
    from the spec rather than guessed from the parent's flattened
    children. A parent with fewer than two breakouts is not a real
    switcher and is ignored.

    Ordinary nesting -- a switcher declared inside another switcher's own
    alternative -- is supported: when the ancestor's excluding option is
    the branch that carries the nested switcher, the ancestor's own rule
    alone already hides the nested switcher's parent and everything
    beneath it, so the nested switcher's own gate is subsumed and drops
    out of consideration (`_drop_subsumed_gates`). What this still refuses
    is a descendant whose visibility depends on two switcher gates where
    neither subsumes the other -- whether that is two switchers in
    unrelated branches, or a nested switcher reaching a descendant through
    some *other* branch of its own ancestor, one the ancestor's excluding
    option never touches. Both shapes leave a real, selectable combination
    with nothing pointing at the descendant, for the reasons in
    `_reject_orphanable_descendants`. Switchers in disjoint branches that
    do not share a descendant are unaffected either way.
    """
    adjacency = _build_adjacency(edges)
    _reject_orphanable_descendants(breakout_map, edges, adjacency)
