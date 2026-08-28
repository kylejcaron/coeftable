"""Thin builder for prepared cards in a staged event flow."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

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
    _canonical,
    _flow_offsets,
    _non_empty_str,
    _resolve_edge_styles,
    _stage_gap_requirements,
)
from coeftable.theme import DEFAULT, Theme

_DEFAULT_STAGE_GAP_FLOOR = 108


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


def _collapsible_entries(
    value: Sequence[str], *, stage_by_id: Mapping[str, int]
) -> tuple[str, ...]:
    """Canonicalize and validate collapsible card ids against placements.

    Both `_flow_offsets` and `_stage_gap_requirements` index `stage_by_id`
    by every collapsible entry to derive its stage before `Graph` itself
    ever runs its own `known_cards` check, so a bad type, a duplicate, or
    an id missing from `placements` must be rejected here first — with a
    named `SpecError` — rather than surfacing as a raw `KeyError` deep
    inside either private geometry helper.
    """
    collapsible = _canonical(value, name="EventFlow.collapsible")
    for index, card_id in enumerate(collapsible):
        _non_empty_str(card_id, name=f"EventFlow.collapsible[{index}]")
    if len(set(collapsible)) != len(collapsible):
        raise SpecError("EventFlow.collapsible entries must be unique")
    if any(card_id not in stage_by_id for card_id in collapsible):
        raise SpecError("EventFlow.collapsible references an unplaced card")
    return cast(tuple[str, ...], collapsible)


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
    stage_gap: int | None = None,
) -> Graph:
    """Build a staged flow with paint-only back edges.

    ``EventFlow`` measures and validates the same kind/geometry invariant
    that :class:`~coeftable.graph.model.Graph` enforces directly, so its
    checks exist only to name this builder's own input surface in errors;
    Graph remains the authoritative boundary for any caller that constructs
    staged wires without going through this helper.

    Omitting ``stage_gap`` derives the narrowest gap that still keeps every
    forward pill, loop pool, and collapsible fold nub disjoint, using the
    exact same physical planner Graph itself validates an explicit
    ``stage_gap`` against (see `_stage_gap_requirements`), floored at 108px.
    """
    node_entries = cast(tuple[tuple[str, Card], ...], _canonical(nodes, name="EventFlow.nodes"))
    placement_entries = cast(
        tuple[StageSlot, ...], _canonical(placements, name="EventFlow.placements")
    )
    edge_entries = cast(tuple[FlowEdge, ...], _canonical(edges, name="EventFlow.edges"))
    layout = Staged(placement_entries)
    slot_by_id = {slot.card_id: slot for slot in layout.slots}
    stage_by_id = {card_id: slot.stage for card_id, slot in slot_by_id.items()}
    if len(stage_by_id) != len(layout.slots):
        raise SpecError("EventFlow placements card ids must be unique")
    collapsible_entries = _collapsible_entries(collapsible, stage_by_id=stage_by_id)
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
    edge_style_overrides = _styles(styles)
    resolved_stage_gap = stage_gap
    if resolved_stage_gap is None:
        resolved_styles = _resolve_edge_styles(theme, edge_style_overrides)
        max_stage = max((slot.stage for slot in layout.slots), default=0)
        offsets = _flow_offsets(
            wires,
            slot_by_id=slot_by_id,
            collapsible=collapsible_entries,
            chrome=chrome,
            styles=resolved_styles,
        )
        requirements = _stage_gap_requirements(
            wires,
            slot_by_id=slot_by_id,
            offsets=offsets,
            collapsible=collapsible_entries,
            chrome=chrome,
            styles=resolved_styles,
            max_stage=max_stage,
        )
        resolved_stage_gap = max(
            _DEFAULT_STAGE_GAP_FLOOR, math.ceil(max(requirements.values(), default=0.0))
        )
    visibility = tuple(wire.id for wire in wires if wire.kind != "back")
    return Graph(
        nodes=node_entries,
        layout=layout,
        wires=wires,
        collapsible=collapsible_entries,
        visibility=visibility,
        gap=gap,
        layer_gap=resolved_stage_gap,
        dom_prefix=dom_prefix,
        theme=theme,
        chrome=chrome,
        edge_styles=edge_style_overrides,
    )


__all__ = ["EventFlow"]
