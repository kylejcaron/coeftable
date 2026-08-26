"""Data builder for metric-tree graphs."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

from coeftable.cards import DEFAULT_CHROME, Card, CardChrome
from coeftable.errors import SpecError
from coeftable.format import Format
from coeftable.graph.model import Graph, Slot, Slotted, Wire
from coeftable.graph.topology import check_acyclic
from coeftable.theme import DEFAULT, Direction, Theme, role_for

_DIRECTIONS: tuple[Direction, ...] = ("higher_is_better", "lower_is_better", "neutral")


def _sequence(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot a public sequence and report malformed values consistently."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Sequence[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _nodes(value: object) -> tuple[tuple[str, Card], ...]:
    """Snapshot node pairs and expose their ids for topology validation."""
    entries = _sequence(value, name="MetricTree.nodes")
    if not entries:
        raise SpecError("MetricTree.nodes must not be empty")
    result: list[tuple[str, Card]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)) or len(entry) != 2:
            raise SpecError(f"MetricTree.nodes[{index}] must be an (id, Card) pair")
        node_id, card = entry
        if not isinstance(node_id, str) or not node_id:
            raise SpecError(f"MetricTree.nodes[{index}].id must be a non-empty str")
        result.append((node_id, cast(Card, card)))
    ids = [node_id for node_id, _ in result]
    if len(set(ids)) != len(ids):
        raise SpecError("MetricTree.nodes ids must be unique")
    return tuple(result)


def _finite_contribution(value: object, *, index: int) -> float | None:
    """Validate and normalize one edge contribution."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"MetricTree.edges[{index}].contribution must be finite")
    if not math.isfinite(value):
        raise SpecError(f"MetricTree.edges[{index}].contribution must be finite")
    return float(value)


def _edges(value: object, *, node_ids: set[str]) -> tuple[tuple[str, str, float | None], ...]:
    """Snapshot and validate metric-tree edges."""
    entries = _sequence(value, name="MetricTree.edges")
    result: list[tuple[str, str, float | None]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)) or len(entry) != 3:
            raise SpecError(
                f"MetricTree.edges[{index}] must be a (parent, child, contribution) triple"
            )
        parent, child, contribution = entry
        if not isinstance(parent, str) or not parent or not isinstance(child, str) or not child:
            raise SpecError(f"MetricTree.edges[{index}] endpoints must be non-empty str")
        if parent not in node_ids or child not in node_ids:
            raise SpecError(f"MetricTree.edges[{index}] references an unknown node")
        if parent == child:
            raise SpecError("MetricTree edges must not contain self-loops")
        pair = (parent, child)
        if pair in seen:
            raise SpecError("MetricTree edges must not contain duplicate pairs")
        seen.add(pair)
        result.append((parent, child, _finite_contribution(contribution, index=index)))
    return tuple(result)


def _layers(
    node_ids: tuple[str, ...], edges: tuple[tuple[str, str, float | None], ...]
) -> dict[str, int]:
    """Compute longest root paths in a validated acyclic topology."""
    parents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for parent, child, _ in edges:
        parents[child].append(parent)

    layer: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id not in layer:
            layer[node_id] = (
                0
                if not parents[node_id]
                else 1 + max(depth(parent) for parent in parents[node_id])
            )
        return layer[node_id]

    for node_id in node_ids:
        depth(node_id)
    return layer


def _label(fmt: Format, contribution: float) -> str:
    """Format a contribution, making positive signs explicit."""
    text = fmt(contribution)
    if not isinstance(text, str):
        raise SpecError("MetricTree fmt must return a str")
    if contribution > 0 and not text.startswith("+"):
        text = f"+{text}"
    return text


def MetricTree(
    nodes: Sequence[tuple[str, Card]],
    edges: Sequence[tuple[str, str, float | None]],
    fmt: Format,
    direction: Direction = "higher_is_better",
    theme: Theme = DEFAULT,
    chrome: CardChrome = DEFAULT_CHROME,
) -> Graph:
    """Build a slotted, collapsible graph from a metric-tree topology."""
    if not callable(fmt):
        raise SpecError("MetricTree fmt must be callable")
    if direction not in _DIRECTIONS:
        raise SpecError("MetricTree direction must be valid")

    node_entries = _nodes(nodes)
    node_ids = tuple(node_id for node_id, _ in node_entries)
    edge_entries = _edges(edges, node_ids=set(node_ids))
    check_acyclic(node_ids, tuple((parent, child) for parent, child, _ in edge_entries))

    layers = _layers(node_ids, edge_entries)
    next_slot: dict[int, int] = {}
    slots: list[Slot] = []
    for node_id in node_ids:
        layer = layers[node_id]
        slot = next_slot.get(layer, 0)
        slots.append(Slot(node_id, layer, slot))
        next_slot[layer] = slot + 1

    wires = tuple(
        Wire(
            id=f"w{index}",  # ordinal: node ids are unrestricted and may collide if concatenated
            src=parent,
            dst=child,
            label=None if contribution is None else _label(fmt, contribution),
            label_role=None
            if contribution is None
            else role_for(contribution, contribution, 0.0, direction),
        )
        for index, (parent, child, contribution) in enumerate(edge_entries)
    )
    outgoing = {parent for parent, _, _ in edge_entries}
    collapsible = tuple(node_id for node_id in node_ids if node_id in outgoing)
    return Graph(
        nodes=node_entries,
        layout=Slotted(tuple(slots)),
        wires=wires,
        collapsible=collapsible,
        theme=theme,
        chrome=chrome,
    )
