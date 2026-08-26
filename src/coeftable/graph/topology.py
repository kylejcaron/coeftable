"""Visibility-topology helpers for the experimental graph layer."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from types import MappingProxyType

from coeftable.errors import SpecError


def _canonical_ids(nodes: Iterable[object]) -> tuple[str, ...]:
    """Return node ids from strings, ``(id, value)`` pairs, or id-bearing values."""
    values: list[str] = []
    for index, node in enumerate(nodes):
        if isinstance(node, str):
            node_id = node
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)) and len(node) >= 1:
            node_id = node[0]
        elif hasattr(node, "id"):
            node_id = node.id
        else:
            raise SpecError(f"topology.nodes[{index}] must identify a node")
        if not isinstance(node_id, str) or not node_id:
            raise SpecError(f"topology.nodes[{index}] must have a non-empty id")
        values.append(node_id)
    if len(set(values)) != len(values):
        raise SpecError("topology.nodes ids must be unique")
    return tuple(values)


def _edge_endpoints(edge: object, index: int) -> tuple[str, str]:
    """Read endpoints from a wire-like value or a two-item edge pair."""
    if hasattr(edge, "src") and hasattr(edge, "dst"):
        src = edge.src
        dst = edge.dst
    elif isinstance(edge, Sequence) and not isinstance(edge, (str, bytes)) and len(edge) >= 2:
        src, dst = edge[0], edge[1]
    else:
        raise SpecError(f"topology.edges[{index}] must identify source and destination")
    if not isinstance(src, str) or not src or not isinstance(dst, str) or not dst:
        raise SpecError(f"topology.edges[{index}] endpoints must be non-empty str")
    return src, dst


def _normalise_edges(
    nodes: tuple[str, ...], edges: Iterable[object]
) -> tuple[tuple[str, str], ...]:
    """Validate and snapshot topology edges."""
    node_ids = set(nodes)
    result: list[tuple[str, str]] = []
    for index, edge in enumerate(edges):
        src, dst = _edge_endpoints(edge, index)
        if src not in node_ids or dst not in node_ids:
            raise SpecError(f"topology.edges[{index}] references an unknown node")
        if src == dst:
            raise SpecError("visibility topology must not contain self-loops")
        result.append((src, dst))
    return tuple(result)


def is_acyclic(nodes: Iterable[object], edges: Iterable[object]) -> bool:
    """Return whether the directed edge set is acyclic.

    Unknown endpoints and malformed values are invalid topology rather than a cycle,
    and therefore return ``False``.  :func:`check_acyclic` provides a diagnostic
    ``SpecError`` for graph construction.
    """
    try:
        node_ids = _canonical_ids(nodes)
        topology = _normalise_edges(node_ids, edges)
    except SpecError:
        return False

    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for src, dst in topology:
        outgoing[src].append(dst)
        indegree[dst] += 1
    ready = [node_id for node_id in node_ids if indegree[node_id] == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for child in outgoing[node_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return visited == len(node_ids)


def check_acyclic(nodes: Iterable[object], edges: Iterable[object]) -> None:
    """Validate that a directed edge set is acyclic."""
    node_ids = _canonical_ids(nodes)
    topology = _normalise_edges(node_ids, edges)
    if not is_acyclic(node_ids, topology):
        raise SpecError("visibility topology must be acyclic")


def _root_paths(
    node_id: str,
    parents: Mapping[str, tuple[str, ...]],
    memo: dict[str, tuple[frozenset[str], ...]],
) -> tuple[frozenset[str], ...]:
    """Enumerate root-to-node paths as sets of strict ancestors."""
    if node_id in memo:
        return memo[node_id]
    node_paths: set[frozenset[str]] = set()
    for parent in parents[node_id]:
        for path in _root_paths(parent, parents, memo):
            node_paths.add(path | {parent})
    if not node_paths:
        node_paths.add(frozenset())
    result = tuple(node_paths)
    memo[node_id] = result
    return result


def _minimal_hitting_sets(
    paths: tuple[frozenset[str], ...], candidates: tuple[str, ...]
) -> frozenset[frozenset[str]]:
    """Return inclusion-minimal non-empty subsets intersecting every path."""
    found: list[frozenset[str]] = []
    for size in range(1, len(candidates) + 1):
        for combination in combinations(candidates, size):
            candidate = frozenset(combination)
            if any(existing <= candidate for existing in found):
                continue
            if all(path & candidate for path in paths):
                found = [existing for existing in found if not candidate < existing]
                found.append(candidate)
    return frozenset(found)


def blocker_families(
    nodes: Iterable[object],
    edges: Iterable[object],
    collapsible: Iterable[str],
) -> Mapping[str, frozenset[frozenset[str]]]:
    """Compute total minimal blocker families for every node.

    ``B(v)`` is the empty family for roots and for any node with an uncuttable
    root-to-node path.  Otherwise it contains the inclusion-minimal hitting sets
    over the collapsible strict-ancestor interiors of every root-to-node path.
    """
    node_ids = _canonical_ids(nodes)
    topology = _normalise_edges(node_ids, edges)
    candidates = tuple(collapsible)
    if any(not isinstance(node_id, str) or not node_id for node_id in candidates):
        raise SpecError("collapsible entries must be non-empty str")
    if len(set(candidates)) != len(candidates):
        raise SpecError("collapsible entries must be unique")
    unknown = set(candidates) - set(node_ids)
    if unknown:
        raise SpecError("collapsible references an unknown node")
    if not is_acyclic(node_ids, topology):
        raise SpecError("visibility topology must be acyclic")

    parents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for src, dst in topology:
        parents[dst].append(src)
    frozen_parents = {node_id: tuple(value) for node_id, value in parents.items()}
    memo: dict[str, tuple[frozenset[str], ...]] = {}
    collapsible_set = set(candidates)
    families: dict[str, frozenset[frozenset[str]]] = {}
    for node_id in node_ids:
        paths = _root_paths(node_id, frozen_parents, memo)
        interiors = tuple(path & collapsible_set for path in paths)
        if any(not interior for interior in interiors):
            families[node_id] = frozenset()
        else:
            families[node_id] = _minimal_hitting_sets(interiors, candidates)
    return MappingProxyType(families)


__all__ = ["blocker_families", "check_acyclic", "is_acyclic"]
