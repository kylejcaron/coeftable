"""Thin builder for prepared cards in a staged event flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from coeftable.cards import Card, CardChrome
from coeftable.cards.chrome import DEFAULT_CHROME
from coeftable.errors import SpecError
from coeftable.graph.model import (
    EdgeKind,
    EdgeStyle,
    FlowEdge,
    Graph,
    Staged,
    StageSlot,
    Wire,
)
from coeftable.theme import DEFAULT, Theme


def _styles(
    overrides: Mapping[EdgeKind, EdgeStyle] | None,
) -> tuple[tuple[EdgeKind, EdgeStyle], ...]:
    """Snapshot the caller's style overrides into an ordered, validated tuple."""
    if overrides is None:
        return ()
    if not isinstance(overrides, Mapping):
        raise SpecError("EventFlow.styles must be a mapping")
    kinds: tuple[EdgeKind, ...] = ("forward", "skip", "back")
    result: list[tuple[EdgeKind, EdgeStyle]] = []
    for kind in kinds:
        if kind not in overrides:
            continue
        style = overrides[kind]
        if not isinstance(style, EdgeStyle):
            raise SpecError("EventFlow.styles values must be EdgeStyle")
        result.append((kind, style))
    if any(kind not in kinds for kind in overrides):
        raise SpecError("EventFlow.styles keys must be valid edge kinds")
    return tuple(result)


def EventFlow(
    nodes: Sequence[tuple[str, Card]],
    placements: Sequence[StageSlot],
    edges: Sequence[FlowEdge],
    *,
    styles: Mapping[EdgeKind, EdgeStyle] | None = None,
    collapsible: Sequence[str] = (),
    theme: Theme = DEFAULT,
    chrome: CardChrome = DEFAULT_CHROME,
    dom_prefix: str = "g0",
    gap: int = 36,
    stage_gap: int = 72,
) -> Graph:
    """Build a staged flow with paint-only back edges.

    ``EventFlow`` measures and validates the same kind/geometry invariant
    that :class:`~coeftable.graph.model.Graph` enforces directly, so its
    checks exist only to name this builder's own input surface in errors;
    Graph remains the authoritative boundary for any caller that constructs
    staged wires without going through this helper.
    """
    node_entries = tuple(nodes)
    placement_entries = tuple(placements)
    edge_entries = tuple(edges)
    collapsible_entries = tuple(collapsible)
    layout = Staged(placement_entries)
    stage_by_id = {slot.card_id: slot.stage for slot in layout.slots}
    if len(stage_by_id) != len(layout.slots):
        raise SpecError("EventFlow placements card ids must be unique")
    for index, edge in enumerate(edge_entries):
        if not isinstance(edge, FlowEdge):
            raise SpecError(f"EventFlow.edges[{index}] must be a FlowEdge")
        if edge.src not in stage_by_id or edge.dst not in stage_by_id:
            raise SpecError("EventFlow edge endpoints must reference placements")
        src_stage = stage_by_id[edge.src]
        dst_stage = stage_by_id[edge.dst]
        if edge.kind == "forward" and dst_stage != src_stage + 1:
            raise SpecError("forward edge must advance by exactly one stage")
        if edge.kind == "skip" and dst_stage <= src_stage + 1:
            raise SpecError("skip edge must advance by more than one stage")
        if edge.kind == "back" and dst_stage > src_stage:
            raise SpecError("back edge must stay in or return to an earlier stage")
    wires = tuple(
        Wire(
            edge.id,
            edge.src,
            edge.dst,
            label=edge.label,
            kind=edge.kind,
        )
        for edge in edge_entries
    )
    visibility = tuple(wire.id for wire in wires if wire.kind != "back")
    return Graph(
        nodes=node_entries,
        layout=layout,
        wires=wires,
        collapsible=collapsible_entries,
        visibility=visibility,
        gap=gap,
        layer_gap=stage_gap,
        dom_prefix=dom_prefix,
        theme=theme,
        chrome=chrome,
        edge_styles=_styles(styles),
    )


__all__ = ["EventFlow"]
