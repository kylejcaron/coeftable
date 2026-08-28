"""Deterministic layered positions shared by graph builders and layouts."""

from __future__ import annotations

import math

from coeftable.graph.topology import check_acyclic


def layered_positions(
    node_ids: tuple[str, ...], edges: tuple[tuple[str, str], ...]
) -> tuple[tuple[str, int, int], ...]:
    """Return `(node_id, layer, slot)` in declaration order."""
    check_acyclic(node_ids, edges)
    parents: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    children: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for parent, child in edges:
        parents[child].append(parent)
        children[parent].append(child)

    layers: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id not in layers:
            layers[node_id] = (
                0
                if not parents[node_id]
                else 1 + max(depth(parent) for parent in parents[node_id])
            )
        return layers[node_id]

    for node_id in node_ids:
        depth(node_id)

    first = {node_id: index for index, node_id in enumerate(node_ids)}
    by_layer: dict[int, list[str]] = {}
    for node_id in node_ids:
        by_layer.setdefault(layers[node_id], []).append(node_id)

    slot_by_id: dict[str, int] = {}
    deepest = max(by_layer)
    for slot, node_id in enumerate(by_layer[deepest]):
        slot_by_id[node_id] = slot
    max_used = len(by_layer[deepest]) - 1

    for layer in range(deepest - 1, -1, -1):
        current = by_layer[layer]
        ranks = {node_id: index for index, node_id in enumerate(current)}
        childful = [node_id for node_id in current if children[node_id]]
        child_centers = {
            node_id: sum(slot_by_id[child] for child in children[node_id]) / len(children[node_id])
            for node_id in childful
        }
        leftmost = math.floor(min(child_centers.values(), default=0.0))
        first_childful_rank = min((ranks[node_id] for node_id in childful), default=0)
        centers = {
            node_id: child_centers.get(node_id, leftmost + ranks[node_id] - first_childful_rank)
            for node_id in current
        }
        ordered = [
            node_id
            for _, _, node_id in sorted(
                (centers[node_id], first[node_id], node_id) for node_id in current
            )
        ]
        max_used = max(max_used, len(ordered) - 1)
        for index, node_id in enumerate(ordered):
            lower = slot_by_id[ordered[index - 1]] + 1 if index else 0
            slot_by_id[node_id] = max(lower, min(round(centers[node_id]), max(max_used, lower)))
        max_used = max(max_used, slot_by_id[ordered[-1]])

    return tuple((node_id, layers[node_id], slot_by_id[node_id]) for node_id in node_ids)
