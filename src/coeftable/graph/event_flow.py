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
    stage_inset: int = 0,
    stage_labels: Sequence[str] = (),
) -> Graph:
    """Build a staged flow with paint-only back edges.

    ``EventFlow`` measures and validates the same kind/geometry invariant
    that :class:`~coeftable.graph.model.Graph` enforces directly, so its
    checks exist only to name this builder's own input surface in errors;
    Graph remains the authoritative boundary for any caller that constructs
    staged wires without going through this helper.

    Placement rules for staged edges: ``forward`` advances to the next
    stage or to the next lane in the same stage; ``skip`` advances to any
    later stage (adjacent stages included) or to the next lane in the same
    stage; ``back`` returns to the same or an earlier stage and is
    paint-only, never affecting visibility. A same-stage forward/skip pill
    is centered in the lane gap (``EventFlow.gap``) it routes through, not
    the inter-stage ``stage_gap``; every cross-stage forward/adjacent-skip
    pill packs into ``stage_gap`` instead, alongside exterior skip bows,
    back loops, and collapsible fold nubs.

    ``stage_inset`` reserves a nonnegative horizontal margin inside each
    stage column, centering every intrinsic-width card in it; zero (the
    default) is byte-identical to omitting it. ``stage_gap`` is always the
    empty distance between two adjacent *padded* stage-column bounds, so a
    stage boundary's actual physical clearance for routes, pills, and nubs
    is ``stage_gap + 2 * stage_inset``.

    Omitting ``stage_gap`` derives the narrowest visible band gap that still
    keeps every forward pill, loop pool, and collapsible fold nub disjoint.
    Physical card-edge clearance is floored at 108px before
    ``2 * stage_inset`` is subtracted. The visible gap is clamped to 18px
    when fold nubs are present and otherwise to the Graph contract's 1px
    minimum.
    """
    node_entries = cast(tuple[tuple[str, Card], ...], _canonical(nodes, name="EventFlow.nodes"))
    placement_entries = cast(
        tuple[StageSlot, ...], _canonical(placements, name="EventFlow.placements")
    )
    edge_entries = cast(tuple[FlowEdge, ...], _canonical(edges, name="EventFlow.edges"))
    stage_label_entries = cast(
        tuple[str, ...], _canonical(stage_labels, name="EventFlow.stage_labels")
    )
    layout = Staged(placement_entries, labels=stage_label_entries, stage_inset=stage_inset)
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
        src_slot = slot_by_id[edge.src]
        dst_slot = slot_by_id[edge.dst]
        same_stage_next_lane = (
            dst_slot.stage == src_slot.stage and dst_slot.lane == src_slot.lane + 1
        )
        if edge.kind == "forward":
            if dst_slot.stage != src_slot.stage + 1 and not same_stage_next_lane:
                if dst_slot.stage == src_slot.stage:
                    raise SpecError("same-stage forward edge must advance to the next lane")
                raise SpecError(
                    "forward edge must advance by exactly one stage or to the next "
                    "lane in the same stage"
                )
        elif edge.kind == "skip":
            if dst_slot.stage <= src_slot.stage and not same_stage_next_lane:
                if dst_slot.stage == src_slot.stage:
                    raise SpecError("same-stage skip edge must advance to the next lane")
                raise SpecError(
                    "skip edge must advance to a later stage or to the next lane in the same stage"
                )
        elif dst_slot.stage > src_slot.stage:
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
        # `stage_gap` is measured between padded column bounds. Preserve the
        # existing 108px minimum as physical card-edge clearance, then net
        # out the free inset on both sides so wider bands replace empty gap
        # instead of pushing cards farther apart.
        physical_requirement = max(
            float(_DEFAULT_STAGE_GAP_FLOOR),
            max(requirements.values(), default=0.0),
        )
        minimum_visible_gap = 18 if collapsible_entries else 1
        resolved_stage_gap = max(
            minimum_visible_gap,
            math.ceil(physical_requirement - 2 * layout.stage_inset),
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
