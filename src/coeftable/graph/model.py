"""Validated leaf values for the experimental graph layer."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from coeftable.cards.card import Card
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome, line_height
from coeftable.errors import SpecError
from coeftable.graph._layered import layered_positions
from coeftable.graph._routes import (
    Route,
    route_across,
    route_back_sag,
    route_c_loop,
    route_skip_bow,
)
from coeftable.graph._staged import staged_boxes
from coeftable.graph.state import _compile_state, _CompiledState
from coeftable.graph.topology import blocker_families, check_acyclic
from coeftable.theme import DEFAULT, Role, Theme

_ROLES: tuple[Role, ...] = ("favorable", "unfavorable", "inconclusive", "neutral")
_PREDICATES = ("checked", "option_checked")
type Predicate = Literal["checked", "option_checked"]


def _canonical(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot an input sequence while presenting malformed inputs as specs."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _non_empty_str(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{name} must be a non-empty str")


def _non_negative_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SpecError(f"{name} must be a non-negative int")


@dataclass(frozen=True, slots=True)
class ControlRef:
    """Reference a card's nub or one of its keyed select controls."""

    card_id: str
    key: str | None = None

    def __post_init__(self) -> None:
        """Validate the reference fields."""
        _non_empty_str(self.card_id, name="ControlRef.card_id")
        if self.key is not None:
            _non_empty_str(self.key, name="ControlRef.key")


@dataclass(frozen=True, slots=True)
class Atom:
    """One positive control predicate in a state rule."""

    control: ControlRef
    predicate: Predicate
    option: str | None = None

    def __post_init__(self) -> None:
        """Validate predicate and control/option coherence."""
        if not isinstance(self.control, ControlRef):
            raise SpecError("Atom.control must be a ControlRef")
        if self.predicate not in _PREDICATES:
            raise SpecError("Atom.predicate must be 'checked' or 'option_checked'")
        if self.predicate == "checked":
            if self.control.key is not None:
                raise SpecError("Atom.checked requires ControlRef.key to be None")
            if self.option is not None:
                raise SpecError("Atom.checked requires option to be None")
            return
        if self.control.key is None:
            raise SpecError("Atom.option_checked requires ControlRef.key")
        if self.option is None:
            raise SpecError("Atom.option_checked requires option")


@dataclass(frozen=True, slots=True)
class StateRule:
    """A positive conjunction and its card/wire hide targets."""

    when_all: tuple[Atom, ...]
    hide_cards: tuple[str, ...] = ()
    hide_wires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Canonicalize targets and validate the rule."""
        when_all = _canonical(self.when_all, name="StateRule.when_all")
        if not when_all:
            raise SpecError("StateRule.when_all must not be empty")
        atoms: list[Atom] = []
        for index, atom in enumerate(when_all):
            if not isinstance(atom, Atom):
                raise SpecError(f"StateRule.when_all[{index}] must be an Atom")
            atoms.append(atom)
        if len(set(when_all)) != len(when_all):
            raise SpecError("StateRule.when_all must not contain duplicates")
        option_by_control: dict[ControlRef, str] = {}
        for atom in atoms:
            if atom.predicate != "option_checked" or atom.option is None:
                continue
            previous = option_by_control.setdefault(atom.control, atom.option)
            if previous != atom.option:
                raise SpecError(
                    "StateRule.when_all must not contain conflicting options for the same control"
                )

        hide_cards = _canonical(self.hide_cards, name="StateRule.hide_cards")
        hide_wires = _canonical(self.hide_wires, name="StateRule.hide_wires")
        for name, targets in (
            ("StateRule.hide_cards", hide_cards),
            ("StateRule.hide_wires", hide_wires),
        ):
            for index, target in enumerate(targets):
                _non_empty_str(target, name=f"{name}[{index}]")
            if len(set(targets)) != len(targets):
                raise SpecError(f"{name} must not contain duplicates")
        if not hide_cards and not hide_wires:
            raise SpecError("StateRule must hide at least one card or wire")

        object.__setattr__(self, "when_all", cast(tuple[Atom, ...], when_all))
        object.__setattr__(self, "hide_cards", cast(tuple[str, ...], hide_cards))
        object.__setattr__(self, "hide_wires", cast(tuple[str, ...], hide_wires))


@dataclass(frozen=True, slots=True)
class Slot:
    """A card's zero-based position in a :class:`Slotted` layout."""

    card_id: str
    layer: int
    slot: int

    def __post_init__(self) -> None:
        """Validate the card and its zero-based coordinates."""
        _non_empty_str(self.card_id, name="Slot.card_id")
        _non_negative_int(self.layer, name="Slot.layer")
        _non_negative_int(self.slot, name="Slot.slot")


@dataclass(frozen=True, slots=True)
class Slotted:
    """Explicit card positions; graph-level domain checks are deferred."""

    slots: tuple[Slot, ...]

    def __post_init__(self) -> None:
        """Canonicalize and validate the slot entries."""
        slots = _canonical(self.slots, name="Slotted.slots")
        if not slots:
            raise SpecError("Slotted.slots must not be empty")
        for index, slot in enumerate(slots):
            if not isinstance(slot, Slot):
                raise SpecError(f"Slotted.slots[{index}] must be a Slot")
        object.__setattr__(self, "slots", cast(tuple[Slot, ...], slots))


@dataclass(frozen=True, slots=True)
class StageSlot:
    """A card's zero-based stage/lane position in a :class:`Staged` layout."""

    card_id: str
    stage: int
    lane: int

    def __post_init__(self) -> None:
        """Validate the card and its zero-based coordinates."""
        _non_empty_str(self.card_id, name="StageSlot.card_id")
        _non_negative_int(self.stage, name="StageSlot.stage")
        _non_negative_int(self.lane, name="StageSlot.lane")


@dataclass(frozen=True, slots=True)
class Staged:
    """Explicit stage/lane positions; graph-level domain checks are deferred."""

    slots: tuple[StageSlot, ...]

    def __post_init__(self) -> None:
        """Canonicalize and validate the stage/lane entries."""
        slots = _canonical(self.slots, name="Staged.slots")
        if not slots:
            raise SpecError("Staged.slots must not be empty")
        for index, slot in enumerate(slots):
            if not isinstance(slot, StageSlot):
                raise SpecError(f"Staged.slots[{index}] must be a StageSlot")
        object.__setattr__(self, "slots", cast(tuple[StageSlot, ...], slots))


@dataclass(frozen=True, slots=True)
class LayeredDag:
    """Derive deterministic slots from graph nodes and wires."""


type EdgeKind = Literal["forward", "skip", "back"]
_EDGE_KINDS: tuple[EdgeKind, ...] = ("forward", "skip", "back")


@dataclass(frozen=True, slots=True)
class EdgeStyle:
    """Stroke, width, and dash for one flow edge kind."""

    stroke: str
    width: float = 1.5
    dash: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """Validate stroke, width, and dash geometry."""
        _non_empty_str(self.stroke, name="EdgeStyle.stroke")
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, (int, float))
            or not math.isfinite(self.width)
            or self.width <= 0
        ):
            raise SpecError("EdgeStyle.width must be a positive finite number")
        dash = _canonical(self.dash, name="EdgeStyle.dash")
        for index, value in enumerate(dash):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise SpecError(f"EdgeStyle.dash[{index}] must be a positive finite number")
        numeric_dash = cast(tuple[float, ...], dash)
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "dash", tuple(float(value) for value in numeric_dash))


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """One staged event-flow edge and its topology kind."""

    id: str
    src: str
    dst: str
    kind: EdgeKind
    label: str | None = None

    def __post_init__(self) -> None:
        """Validate endpoints and the edge kind."""
        _non_empty_str(self.id, name="FlowEdge.id")
        _non_empty_str(self.src, name="FlowEdge.src")
        _non_empty_str(self.dst, name="FlowEdge.dst")
        if self.src == self.dst:
            raise SpecError("FlowEdge.src and FlowEdge.dst must differ")
        if self.kind not in _EDGE_KINDS:
            raise SpecError("FlowEdge.kind must be forward, skip, or back")
        if self.label is not None:
            _non_empty_str(self.label, name="FlowEdge.label")


@dataclass(frozen=True, slots=True)
class Wire:
    """A directed graph edge and optional semantic label.

    ``kind`` is ``None`` for Slotted/LayeredDag wires. A Staged wire must
    declare a flow ``kind``; :class:`EventFlow` is the intended builder, but
    :class:`Graph` validates the kind/geometry invariant directly so a
    caller cannot bypass it by constructing wires without that helper.
    """

    id: str
    src: str
    dst: str
    label: str | None = None
    label_role: Role | None = None
    label_color: str | None = None
    kind: EdgeKind | None = None

    def __post_init__(self) -> None:
        """Validate endpoints, optional label styling, and the flow kind."""
        _non_empty_str(self.id, name="Wire.id")
        _non_empty_str(self.src, name="Wire.src")
        _non_empty_str(self.dst, name="Wire.dst")
        if self.src == self.dst:
            raise SpecError("Wire.src and Wire.dst must differ")
        if self.label is not None:
            _non_empty_str(self.label, name="Wire.label")
        if self.label_role is not None and self.label_role not in _ROLES:
            raise SpecError("Wire.label_role must be a valid Role")
        if self.label_color is not None:
            _non_empty_str(self.label_color, name="Wire.label_color")
        if self.label_role is not None and self.label_color is not None:
            raise SpecError("Wire.label_role and Wire.label_color are mutually exclusive")
        if (self.label_role is not None or self.label_color is not None) and self.label is None:
            raise SpecError("Wire.label is required when label_role or label_color is set")
        if self.kind is not None and self.kind not in _EDGE_KINDS:
            raise SpecError("Wire.kind must be forward, skip, or back")


def _graph_positive_int(value: object, *, name: str) -> None:
    """Validate a graph spacing value."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SpecError(f"{name} must be a positive int")


def _graph_nodes(value: object) -> tuple[tuple[str, Card], ...]:
    """Canonicalize and validate graph node pairs."""
    entries = _canonical(value, name="Graph.nodes")
    if not entries:
        raise SpecError("Graph.nodes must not be empty")
    nodes: list[tuple[str, Card]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)) or len(entry) != 2:
            raise SpecError(f"Graph.nodes[{index}] must be an (id, Card) pair")
        node_id, card = entry
        _non_empty_str(node_id, name=f"Graph.nodes[{index}].id")
        if not isinstance(card, Card):
            raise SpecError(f"Graph.nodes[{index}].card must be a Card")
        nodes.append((cast(str, node_id), card))
    ids = [node_id for node_id, _ in nodes]
    if len(set(ids)) != len(ids):
        raise SpecError("Graph.nodes ids must be unique")
    return tuple(nodes)


def _graph_shared_slot_groups(slots: tuple[Slot, ...]) -> tuple[frozenset[str], ...]:
    """Collect card ids that occupy each shared layer/slot position."""
    positions: dict[tuple[int, int], list[str]] = {}
    for slot in slots:
        positions.setdefault((slot.layer, slot.slot), []).append(slot.card_id)
    return tuple(frozenset(group) for group in positions.values() if len(group) > 1)


def _graph_partition_rules(
    *,
    card_id: str,
    key: str,
    options: tuple[str, ...],
    rules: tuple[StateRule, ...],
) -> tuple[StateRule, ...] | None:
    """Return the select's one-rule-per-option partition, if every option has one."""
    governing: list[StateRule] = []
    for option in options:
        matches = [
            rule
            for rule in rules
            if len(rule.when_all) == 1
            and rule.when_all[0].predicate == "option_checked"
            and rule.when_all[0].control.card_id == card_id
            and (rule.when_all[0].control.key, rule.when_all[0].option) == (key, option)
        ]
        if len(matches) != 1:
            return None
        governing.append(matches[0])
    return tuple(governing)


def _graph_select_governed_groups(
    governing: tuple[StateRule, ...],
    groups: tuple[frozenset[str], ...],
) -> tuple[tuple[frozenset[str], ...], tuple[tuple[frozenset[str], StateRule], ...]]:
    """Classify each shared group a select's rules touch.

    A candidate group is any group one of the rules touches. A candidate is
    strictly governed when every option leaves exactly one member visible,
    covering the whole group across options. A candidate is instead an
    ancestor hide when every option either empties it completely or leaves
    it untouched: that shape belongs to a switcher retiring the group's
    owner wholesale, not to a governor of the group itself, and each
    emptying option is validated separately once the real governor is
    known. Any other shape a select's rules touch a group with is a bug,
    not a reason to keep looking for another governor.
    """
    hidden_by_option = tuple(frozenset(rule.hide_cards) for rule in governing)
    hidden_union: frozenset[str] = frozenset().union(*hidden_by_option)
    strict: list[frozenset[str]] = []
    ancestor: list[tuple[frozenset[str], StateRule]] = []
    for group in (candidate for candidate in groups if candidate & hidden_union):
        remaining_by_option = tuple(group - hidden for hidden in hidden_by_option)
        if all(len(remaining) == 1 for remaining in remaining_by_option):
            if frozenset().union(*remaining_by_option) != group:
                raise SpecError("shared slots require one governing external SelectControl")
            strict.append(group)
            continue
        if all(len(remaining) in (0, len(group)) for remaining in remaining_by_option):
            ancestor.extend(
                (group, rule)
                for rule, remaining in zip(governing, remaining_by_option, strict=True)
                if not remaining
            )
            continue
        raise SpecError("shared slots require one governing external SelectControl")
    return tuple(strict), tuple(ancestor)


def _graph_reject_unguarded_ancestor_hides(
    ancestor_touches: tuple[tuple[frozenset[str], StateRule], ...],
    *,
    resolved: Mapping[frozenset[str], tuple[str, tuple[StateRule, ...]]],
) -> None:
    """Require a rule that empties a shared group to also hide its controller."""
    for group, rule in ancestor_touches:
        controller, _ = resolved[group]
        if controller not in rule.hide_cards:
            raise SpecError(
                "shared-slot ancestor rule empties a group without hiding its "
                f"controller {controller!r}"
            )


def _graph_require_controller_hide_obligations(
    resolved: Mapping[frozenset[str], tuple[str, tuple[StateRule, ...]]],
    *,
    rules: tuple[StateRule, ...],
) -> None:
    """Require any rule hiding a shared-slot controller to also hide what it governs."""
    controller_groups: dict[str, frozenset[str]] = {}
    for group, (controller, _) in resolved.items():
        controller_groups[controller] = controller_groups.get(controller, frozenset()) | group

    for rule in rules:
        hidden = frozenset(rule.hide_cards)
        for controller, members in controller_groups.items():
            if controller not in hidden:
                continue
            left_behind = members - hidden
            if not left_behind:
                continue
            if hidden == frozenset({controller}):
                raise SpecError("shared-slot controller must never be hidden")
            raise SpecError(
                f"shared-slot controller {controller!r} hidden without hiding every "
                f"member it governs; left visible: {sorted(left_behind)}"
            )


def _graph_resolve_shared_slot_controller(
    groups: tuple[frozenset[str], ...],
    *,
    cards: Mapping[str, Card],
    rules: tuple[StateRule, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> tuple[
    dict[frozenset[str], tuple[str, tuple[StateRule, ...]]],
    dict[frozenset[str], frozenset[StateRule]],
]:
    """Resolve the sole external controller governing each shared group.

    The controller must sit outside the group it governs, but it need not stay
    visible: an ancestor rule may hide it, provided that same rule also hides
    every member of every group it governs. That obligation is enforced
    separately; this function only resolves who governs what, and collects the
    ancestor rules that legitimately touch each group.
    """
    governors: dict[frozenset[str], list[tuple[str, tuple[StateRule, ...]]]] = {
        group: [] for group in groups
    }
    ancestor_touches: list[tuple[frozenset[str], StateRule]] = []
    for card_id, card in cards.items():
        for key, options in card.control_options().items():
            governing = _graph_partition_rules(
                card_id=card_id, key=key, options=options, rules=rules
            )
            if governing is None:
                continue
            strict_groups, ancestor = _graph_select_governed_groups(governing, groups)
            for group in strict_groups:
                governors[group].append((card_id, governing))
            ancestor_touches.extend(ancestor)

    resolved: dict[frozenset[str], tuple[str, tuple[StateRule, ...]]] = {}
    for group, candidates in governors.items():
        if any(card_id in group for card_id, _ in candidates):
            raise SpecError("shared-slot controller must be external to its group")
        if len(candidates) != 1:
            raise SpecError("shared slots require one governing external SelectControl")
        controller, governing = candidates[0]
        if blockers[controller]:
            raise SpecError("shared-slot controller must never be hidden")
        resolved[group] = (controller, governing)

    _graph_reject_unguarded_ancestor_hides(tuple(ancestor_touches), resolved=resolved)
    _graph_require_controller_hide_obligations(resolved, rules=rules)

    ancestor_rules_by_group: dict[frozenset[str], frozenset[StateRule]] = {}
    for group, rule in ancestor_touches:
        ancestor_rules_by_group[group] = ancestor_rules_by_group.get(group, frozenset()) | {rule}
    return resolved, ancestor_rules_by_group


def _graph_reject_stray_shared_slot_rules(
    group: frozenset[str],
    *,
    rules: tuple[StateRule, ...],
    accepted: frozenset[StateRule],
) -> None:
    """Reject card-hiding rules that are not exact partition or ancestor rules."""
    if any(set(rule.hide_cards) & group and rule not in accepted for rule in rules):
        raise SpecError("shared-slot rules must be exact governing partition rules")


def _graph_shared_slot_proof(
    groups: tuple[frozenset[str], ...],
    *,
    cards: Mapping[str, Card],
    rules: tuple[StateRule, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> None:
    """Require one external select to prove exclusivity for every shared position."""
    resolved, ancestor_rules_by_group = _graph_resolve_shared_slot_controller(
        groups, cards=cards, rules=rules, blockers=blockers
    )
    for group, (_, governing) in resolved.items():
        accepted = frozenset(governing) | ancestor_rules_by_group.get(group, frozenset())
        _graph_reject_stray_shared_slot_rules(group, rules=rules, accepted=accepted)


def _graph_validate_settings(graph: Graph) -> None:
    """Validate graph-wide scalar settings and object types."""
    if not isinstance(graph.layout, (Slotted, LayeredDag, Staged)):
        raise SpecError("Graph.layout must be a Slotted, LayeredDag, or Staged")
    if not isinstance(graph.theme, Theme):
        raise SpecError("Graph.theme must be a Theme")
    if not isinstance(graph.chrome, CardChrome):
        raise SpecError("Graph.chrome must be a CardChrome")
    _graph_positive_int(graph.gap, name="Graph.gap")
    _graph_positive_int(graph.layer_gap, name="Graph.layer_gap")
    if (
        not isinstance(graph.dom_prefix, str)
        or re.fullmatch(r"[a-z][a-z0-9-]*", graph.dom_prefix) is None
    ):
        raise SpecError("Graph.dom_prefix must match [a-z][a-z0-9-]*")


def _graph_validate_layout(slots: tuple[Slot, ...], known_cards: set[str]) -> None:
    """Validate that layout slots cover nodes with dense coordinates."""
    slot_ids = tuple(slot.card_id for slot in slots)
    if len(set(slot_ids)) != len(slot_ids) or set(slot_ids) != known_cards:
        raise SpecError("Graph.layout.slots must cover graph node ids exactly once")
    layers = {slot.layer for slot in slots}
    slot_domain = {slot.slot for slot in slots}
    layers_dense = min(layers) == 0 and max(layers) == len(layers) - 1
    slots_dense = min(slot_domain) == 0 and max(slot_domain) == len(slot_domain) - 1
    if not (layers_dense and slots_dense):
        raise SpecError("Graph.layout layer and slot indices must be dense from zero")


def _graph_validate_staged(slots: tuple[StageSlot, ...], known_cards: set[str]) -> None:
    """Validate that staged slots cover nodes with dense, non-overlapping coordinates."""
    card_ids = tuple(slot.card_id for slot in slots)
    if len(set(card_ids)) != len(card_ids) or set(card_ids) != known_cards:
        raise SpecError("Graph.layout.slots must cover graph node ids exactly once")
    positions = tuple((slot.stage, slot.lane) for slot in slots)
    if len(set(positions)) != len(positions):
        raise SpecError("Graph.layout cards must not share a stage/lane")
    stages = {slot.stage for slot in slots}
    lanes = {slot.lane for slot in slots}
    if stages != set(range(len(stages))) or lanes != set(range(len(lanes))):
        raise SpecError("Graph.layout stage and lane indices must be dense from zero")


def _graph_wires(
    value: object,
    *,
    known_cards: set[str],
) -> tuple[Wire, ...]:
    """Canonicalize and validate graph wires."""
    wires = _canonical(value, name="Graph.wires")
    for index, wire in enumerate(wires):
        if not isinstance(wire, Wire):
            raise SpecError(f"Graph.wires[{index}] must be a Wire")
    result = cast(tuple[Wire, ...], wires)
    wire_ids = tuple(wire.id for wire in result)
    if len(set(wire_ids)) != len(wire_ids):
        raise SpecError("Graph.wires ids must be unique")
    wire_pairs = tuple((wire.src, wire.dst) for wire in result)
    if len(set(wire_pairs)) != len(wire_pairs):
        raise SpecError("Graph.wires must not contain duplicate pairs")
    if any(wire.src not in known_cards or wire.dst not in known_cards for wire in result):
        raise SpecError("Graph.wires endpoints must reference known cards")
    return result


def _graph_resolve_slots(
    layout: Slotted | LayeredDag,
    *,
    node_ids: tuple[str, ...],
    wires: tuple[Wire, ...],
) -> tuple[Slot, ...]:
    """Return explicit slots as-is, or derive them from wires for a LayeredDag."""
    if isinstance(layout, Slotted):
        return layout.slots
    return tuple(
        Slot(card_id, layer, slot)
        for card_id, layer, slot in layered_positions(
            node_ids, tuple((wire.src, wire.dst) for wire in wires)
        )
    )


def _graph_validate_wire_layers(
    wires: tuple[Wire, ...], *, layers_by_id: Mapping[str, int]
) -> None:
    """Reject a wire that does not strictly descend across layout layers."""
    if any(layers_by_id[wire.src] >= layers_by_id[wire.dst] for wire in wires):
        raise SpecError("Graph.wires must route strictly downward")


def _graph_edge_styles(
    value: object,
) -> tuple[tuple[EdgeKind, EdgeStyle], ...]:
    """Canonicalize and validate the graph's per-kind style overrides."""
    entries = _canonical(value, name="Graph.edge_styles")
    for index, entry in enumerate(entries):
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or entry[0] not in _EDGE_KINDS
            or not isinstance(entry[1], EdgeStyle)
        ):
            raise SpecError(f"Graph.edge_styles[{index}] must be an EdgeKind/EdgeStyle pair")
    result = cast(tuple[tuple[EdgeKind, EdgeStyle], ...], entries)
    kinds = tuple(kind for kind, _style in result)
    if len(set(kinds)) != len(kinds):
        raise SpecError("Graph.edge_styles kinds must be unique")
    return result


def _resolve_edge_styles(
    theme: Theme, overrides: tuple[tuple[EdgeKind, EdgeStyle], ...]
) -> dict[EdgeKind, EdgeStyle]:
    """Resolve default plus overridden per-kind styles against a theme.

    Shared by staged measurement (stroke widths shape the canvas) and the
    renderer (the same resolved styles paint the wires), so both always
    agree on every kind's stroke, width, and dash.
    """
    styles: dict[EdgeKind, EdgeStyle] = {
        "forward": EdgeStyle(theme.axis),
        "skip": EdgeStyle(theme.muted, dash=(5.0, 3.0)),
        "back": EdgeStyle(theme.muted, dash=(2.0, 3.0)),
    }
    styles.update(dict(overrides))
    return styles


def _graph_validate_flow_geometry(
    layout: Slotted | LayeredDag | Staged,
    wires: tuple[Wire, ...],
) -> None:
    """Require every Staged wire to declare a kind consistent with its stages.

    Graph is the authoritative boundary for this invariant: a caller that
    bypasses :class:`EventFlow` and constructs wires directly still cannot
    produce a staged wire with a kind/geometry mismatch.
    """
    if not isinstance(layout, Staged):
        if any(wire.kind is not None for wire in wires):
            raise SpecError("flow wire kinds require a Staged layout")
        return
    stage_by_id = {slot.card_id: slot.stage for slot in layout.slots}
    for wire in wires:
        if wire.kind is None:
            raise SpecError("Staged graph wires must declare a flow kind")
        src_stage = stage_by_id[wire.src]
        dst_stage = stage_by_id[wire.dst]
        if wire.kind == "forward" and dst_stage != src_stage + 1:
            raise SpecError("forward edge must advance by exactly one stage")
        if wire.kind == "skip" and dst_stage <= src_stage + 1:
            raise SpecError("skip edge must advance by more than one stage")
        if wire.kind == "back" and dst_stage > src_stage:
            raise SpecError("back edge must stay in or return to an earlier stage")


def _pill_width(label: str, chrome: CardChrome) -> float:
    """Return a flow wire label pill's exact rendered width."""
    return 2 * chrome.chip_padding_x + len(label) * chrome.caption_size * chrome.char_width_ratio


def _graph_validate_forward_pill_width(
    wires: tuple[Wire, ...],
    *,
    stage_gap: int,
    chrome: CardChrome,
    collapsible: tuple[str, ...],
) -> None:
    """Reject a labeled forward pill wide enough to overlap the next stage.

    A forward wire always crosses at least one ``stage_gap`` of clear space
    between adjacent stage columns (a box narrower than its column's widest
    occupant only widens that gap further), so a pill wider than the gap
    itself would spill onto a neighboring stage's cards no matter where it
    lands along the route. A collapsible source card additionally folds a
    right-edge nub into that same gap, plus matching clearance on either
    side of it (36px total), so its outgoing forward pills must fit the gap
    minus that reserve.
    """
    for wire in wires:
        if wire.kind != "forward" or wire.label is None:
            continue
        required = _pill_width(wire.label, chrome)
        if wire.src in collapsible:
            required += 36
        if required > stage_gap:
            raise SpecError(
                f"forward wire label pill requires {required:g}px but "
                f"Graph.layer_gap is {stage_gap}px"
            )


def _graph_collapsible(value: object, known_cards: set[str]) -> tuple[str, ...]:
    """Canonicalize and validate collapsible card ids."""
    collapsible = _canonical(value, name="Graph.collapsible")
    for index, card_id in enumerate(collapsible):
        _non_empty_str(card_id, name=f"Graph.collapsible[{index}]")
    if len(set(collapsible)) != len(collapsible):
        raise SpecError("Graph.collapsible entries must be unique")
    if any(card_id not in known_cards for card_id in collapsible):
        raise SpecError("Graph.collapsible references an unknown card")
    return cast(tuple[str, ...], collapsible)


def _graph_rebound_nodes(
    nodes: tuple[tuple[str, Card], ...],
    *,
    theme: Theme,
    chrome: CardChrome,
) -> tuple[dict[str, Card], list[tuple[str, Card]]]:
    """Validate chrome and rebind cards to the graph theme."""
    cards: dict[str, Card] = {}
    rebound_nodes: list[tuple[str, Card]] = []
    for card_id, card in nodes:
        if card.chrome != chrome:
            raise SpecError("Graph.chrome must match every Card.chrome")
        rebound = card.with_theme(theme) if card.theme != theme else card
        cards[card_id] = rebound
        rebound_nodes.append((card_id, rebound))
    return cards, rebound_nodes


def _graph_visibility(
    value: object,
    *,
    wires: tuple[Wire, ...],
    wire_ids: tuple[str, ...],
    all_wire_ids: tuple[str, ...],
) -> tuple[tuple[str, ...] | None, tuple[Wire, ...]]:
    """Canonicalize the selected visibility wires.

    A wire id is checked against every known wire first, so an unknown id
    and a known but paint-only back-wire id get distinct errors.
    """
    if value is None:
        return None, wires
    visibility_value = _canonical(value, name="Graph.visibility")
    for index, wire_id in enumerate(visibility_value):
        _non_empty_str(wire_id, name=f"Graph.visibility[{index}]")
    if len(set(visibility_value)) != len(visibility_value):
        raise SpecError("Graph.visibility entries must be unique")
    if any(wire_id not in all_wire_ids for wire_id in visibility_value):
        raise SpecError("Graph.visibility references an unknown wire")
    if any(wire_id not in wire_ids for wire_id in visibility_value):
        raise SpecError("Graph.visibility cannot select a paint-only back wire")
    visibility = cast(tuple[str, ...], visibility_value)
    selected = set(visibility)
    return visibility, tuple(wire for wire in wires if wire.id in selected)


def _graph_rules(
    value: object,
    *,
    known_cards: set[str],
    wire_ids: tuple[str, ...],
    all_wire_ids: tuple[str, ...],
    collapsible: tuple[str, ...],
    card_options: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[StateRule, ...]:
    """Canonicalize and validate graph state rules.

    A ``hide_wires`` id is checked against every known wire first, so an
    unknown id and a known but paint-only back-wire id get distinct errors.
    """
    rules = _canonical(value, name="Graph.rules")
    for index, rule in enumerate(rules):
        if not isinstance(rule, StateRule):
            raise SpecError(f"Graph.rules[{index}] must be a StateRule")
        if any(card_id not in known_cards for card_id in rule.hide_cards):
            raise SpecError("Graph.rules hide_cards must reference known cards")
        if any(wire_id not in all_wire_ids for wire_id in rule.hide_wires):
            raise SpecError("Graph.rules hide_wires must reference known wires")
        if any(wire_id not in wire_ids for wire_id in rule.hide_wires):
            raise SpecError("Graph.rules hide_wires cannot target a paint-only back wire")
        for atom in rule.when_all:
            if atom.control.card_id not in known_cards:
                raise SpecError("Graph.rules controls must reference known cards")
            options = card_options[atom.control.card_id]
            if atom.predicate == "checked":
                if atom.control.card_id not in collapsible:
                    raise SpecError("Graph.rules checked controls must be collapsible cards")
            elif (key := atom.control.key) is None or key not in options:
                raise SpecError("Graph.rules option controls must reference known selects")
            elif atom.option not in options[key]:
                raise SpecError("Graph.rules option must reference a known select option")
    return cast(tuple[StateRule, ...], rules)


def _graph_validate_rule_controllers(
    rules: tuple[StateRule, ...],
    *,
    collapsible: tuple[str, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> None:
    """Reject cycles in the explicit and derived hide dependencies."""
    condition_controllers = tuple(
        dict.fromkeys(atom.control.card_id for rule in rules for atom in rule.when_all)
    )
    outgoing: dict[str, list[str]] = {controller: [] for controller in condition_controllers}

    # A collapsible card's nub can hide any card for which it is a member of
    # at least one minimal blocker set.  Include those derived dependencies in
    # the same graph as injected rules so the two kinds cannot form a cycle.
    for source in collapsible:
        for target, family in blockers.items():
            if any(source in blocker for blocker in family):
                outgoing.setdefault(source, [])
                outgoing.setdefault(target, [])
                if target not in outgoing[source]:
                    outgoing[source].append(target)

    for rule in rules:
        condition_controllers = tuple(
            dict.fromkeys(atom.control.card_id for atom in rule.when_all)
        )
        for source in condition_controllers:
            for target in rule.hide_cards:
                if target in outgoing and target not in outgoing[source]:
                    outgoing[source].append(target)

    for source, targets in outgoing.items():
        if source in targets:
            raise SpecError("state rule controller dependencies must not contain self-loops")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(controller: str) -> None:
        if controller in visiting:
            raise SpecError("state rule controller dependencies must be acyclic")
        if controller in visited:
            return
        visiting.add(controller)
        for target in outgoing[controller]:
            visit(target)
        visiting.remove(controller)
        visited.add(controller)

    for controller in outgoing:
        visit(controller)


type Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class MeasuredGraph:
    """Cached canvas footprint and boxes in node declaration order.

    ``boxes`` is a tuple rather than a mutable mapping so the measured record
    remains an immutable snapshot while retaining deterministic iteration.
    Each entry is ``(card_id, (left, top, width, expanded_height))``; centered
    spare widths use floor integer division when the difference is odd.

    """

    width: int
    height: int
    boxes: tuple[tuple[str, Box], ...]


type AnchorOffset = tuple[float, float]
type GraphAnchors = tuple[tuple[str, tuple[AnchorOffset, AnchorOffset]], ...]
type WirePath = str
type WireGeometry = tuple[WirePath, AnchorOffset]
type GraphWireGeometry = tuple[tuple[str, WireGeometry], ...]


@dataclass(frozen=True, slots=True)
class _GraphLayout:
    """Internal graph geometry, including the measured wire attachments."""

    measured: MeasuredGraph
    anchors: GraphAnchors
    wire_geometry: GraphWireGeometry
    label_band_depths: tuple[tuple[int, int], ...] = ()
    nub_anchors: tuple[tuple[str, tuple[float, float, str]], ...] = ()
    flow_pills: tuple[tuple[str, tuple[float, float, float, float]], ...] = ()


def _graph_layout_offsets(sizes: tuple[int, ...], gap: int) -> tuple[int, ...]:
    """Return each column/layer's offset from the canvas origin."""
    offsets: list[int] = []
    offset = 0
    for size in sizes:
        offsets.append(offset)
        offset += size + gap
    return tuple(offsets)


def _graph_measure(
    nodes: tuple[tuple[str, Card], ...],
    slots: tuple[Slot, ...],
    wires: tuple[Wire, ...],
    *,
    collapsible: tuple[str, ...],
    gap: int,
    layer_gap: int,
    padding: int,
    chrome: CardChrome,
) -> _GraphLayout:
    """Measure rebound cards once and resolve their slotted border boxes."""
    measured = {card_id: card.measure() for card_id, card in nodes}
    slot_by_id = {slot.card_id: slot for slot in slots}
    column_widths = [0] * (max(slot.slot for slot in slots) + 1)
    layer_heights = [0] * (max(slot.layer for slot in slots) + 1)
    for slot in slots:
        footprint = measured[slot.card_id]
        column_widths[slot.slot] = max(column_widths[slot.slot], footprint.width)
        layer_heights[slot.layer] = max(layer_heights[slot.layer], footprint.expanded_height)
    column_offsets = _graph_layout_offsets(tuple(column_widths), gap)
    layer_offsets = _graph_layout_offsets(tuple(layer_heights), layer_gap)
    boxes: list[tuple[str, Box]] = []
    for card_id, _ in nodes:
        slot = slot_by_id[card_id]
        footprint = measured[card_id]
        left = (
            padding + column_offsets[slot.slot] + (column_widths[slot.slot] - footprint.width) // 2
        )
        top = padding + layer_offsets[slot.layer]
        boxes.append((card_id, (left, top, footprint.width, footprint.expanded_height)))
    bottom_layer = max(slot.layer for slot in slots)
    nub_overhang = (
        max(0, 18 - padding)
        if any(slot.layer == bottom_layer and slot.card_id in collapsible for slot in slots)
        else 0
    )
    width = sum(column_widths) + gap * (len(column_widths) - 1) + 2 * padding
    height = sum(layer_heights) + layer_gap * (len(layer_heights) - 1) + 2 * padding + nub_overhang
    footprint = MeasuredGraph(width, height, tuple(boxes))
    anchor_offsets: list[tuple[str, tuple[AnchorOffset, AnchorOffset]]] = []
    for card_id, _ in nodes:
        by_name = {anchor.name: (anchor.x, anchor.y) for anchor in measured[card_id].anchors}
        anchor_offsets.append((card_id, (by_name["in"], by_name["out"])))
    boxes_by_id = dict(boxes)
    anchors_by_id = dict(anchor_offsets)
    labeled_incoming: dict[str, list[int]] = {}
    source_x0: dict[int, float] = {}
    for index, wire in enumerate(wires):
        src_left, _, _, _ = boxes_by_id[wire.src]
        _, (out_x, _) = anchors_by_id[wire.src]
        source_x0[index] = src_left + out_x
        if wire.label is not None:
            labeled_incoming.setdefault(wire.dst, []).append(index)
    label_index = {
        wire_index: (index, len(indices))
        for indices in labeled_incoming.values()
        for index, wire_index in enumerate(
            sorted(indices, key=lambda item: (source_x0[item], item))
        )
    }
    label_offset = chrome.caption_size + 2
    label_step = chrome.caption_size + 4
    label_candidates: dict[int, tuple[float, float, float]] = {}
    wire_rows: list[tuple[int, str, str, AnchorOffset]] = []
    for wire_index, wire in enumerate(wires):
        src_left, src_top, _src_width, _src_height = boxes_by_id[wire.src]
        dst_left, dst_top, _dst_width, _dst_height = boxes_by_id[wire.dst]
        src_slot = slot_by_id[wire.src]
        dst_slot = slot_by_id[wire.dst]
        _, (out_x, out_y) = anchors_by_id[wire.src]
        in_x, in_y = anchors_by_id[wire.dst][0]
        x0 = src_left + out_x
        y0 = src_top + out_y
        x1 = dst_left + in_x
        y1 = dst_top + in_y
        # Bend only after clearing the source LAYER's max bottom: a short
        # card's wire must not sweep behind a taller sibling.
        src_layer_bottom = padding + layer_offsets[src_slot.layer] + layer_heights[src_slot.layer]
        my1 = src_layer_bottom + layer_gap / 2
        my2 = dst_top - layer_gap / 2
        if dst_slot.layer - src_slot.layer > 1:
            if src_slot.slot < len(column_widths) - 1:
                xg = (
                    padding
                    + column_offsets[src_slot.slot]
                    + column_widths[src_slot.slot]
                    + gap / 2
                )
            else:
                xg = padding + column_offsets[src_slot.slot] - gap / 2
            y_a = my1 + layer_gap / 2
            y_b = my2 - layer_gap / 2
            yb2 = (y_b + my2) / 2
            # Clamp into the canvas margin: padding/2 stays left of the first
            # column even under tiny custom padding.
            xg = max(padding / 2, min(footprint.width - padding / 2, xg))
            path = (
                f"M {x0:g},{y0:g} L {x0:g},{src_layer_bottom:g} "
                f"C {x0:g},{my1:g} {xg:g},{my1:g} {xg:g},{y_a:g} "
                f"L {xg:g},{y_b:g} "
                f"C {xg:g},{yb2:g} {x1:g},{yb2:g} {x1:g},{my2:g} "
                f"L {x1:g},{y1 - 3:g}"
            )
        else:
            # Split the inter-layer band into thirds: sweep, tangent run,
            # straight arrival — my1 == my2 under halves made the final
            # control degenerate and elbowed the arrowhead.
            band = dst_top - src_layer_bottom
            a_my1 = src_layer_bottom + band / 3
            a_my2 = dst_top - band / 3
            path = (
                f"M {x0:g},{y0:g} L {x0:g},{src_layer_bottom:g} "
                f"C {x0:g},{a_my1:g} {x1:g},{a_my1:g} {x1:g},{a_my2:g} "
                f"L {x1:g},{y1 - 3:g}"
            )
        if wire.label is None:
            label_anchor_x = x1
        else:
            k, n = label_index[wire_index]
            spread = (k - (n - 1) / 2) * 72
            half_text = len(wire.label) * chrome.caption_size * chrome.data_char_width_ratio / 2
            label_anchor_x = max(
                half_text,
                min(footprint.width - half_text, x1 + spread),
            )
            label_candidates[wire_index] = (
                label_anchor_x,
                half_text,
                y1 - label_offset,
            )
        wire_rows.append((wire_index, wire.id, path, (label_anchor_x, y1 - label_offset)))
    label_anchors: dict[int, AnchorOffset] = {}
    band_depths: dict[int, int] = {}
    for destination, indices in labeled_incoming.items():
        # Interval packing: each label takes the lowest row whose occupied
        # intervals it does not overlap (a wide early label must not leak
        # past a narrow neighbour onto a later one).
        band = slot_by_id[destination].layer - 1
        rows: list[list[tuple[float, float]]] = []
        for wire_index in sorted(indices, key=lambda item: (source_x0[item], item)):
            label_anchor_x, half_text, label_anchor_y = label_candidates[wire_index]
            left = label_anchor_x - half_text
            right = label_anchor_x + half_text
            row = 0
            while row < len(rows) and any(
                left < taken_right and taken_left < right for taken_left, taken_right in rows[row]
            ):
                row += 1
            if row == len(rows):
                rows.append([])
            rows[row].append((left, right))
            band_depths[band] = max(band_depths.get(band, 0), row)
            label_anchors[wire_index] = (
                label_anchor_x,
                label_anchor_y - label_step * row,
            )
    wire_geometry = [
        (wire_id, (path, label_anchors.get(wire_index, fallback)))
        for wire_index, wire_id, path, fallback in wire_rows
    ]
    return _GraphLayout(
        footprint,
        tuple(anchor_offsets),
        tuple(wire_geometry),
        tuple(sorted(band_depths.items())),
    )


def _flow_route(
    wire: Wire,
    src_box: Box,
    dst_box: Box,
    *,
    src_stage: int,
    dst_stage: int,
    src_lane: int,
    dst_lane: int,
    offset: float,
    stage_extents: Mapping[int, tuple[float, float]],
) -> Route:
    """Choose the pure route for one flow wire by kind and relative placement."""
    if wire.kind == "forward":
        return route_across(src_box, dst_box)
    if wire.kind == "skip":
        return route_skip_bow(src_box, dst_box, offset=offset)
    if dst_stage < src_stage:
        return route_back_sag(src_box, dst_box, offset=offset)
    side: Literal["left", "right"] = "left" if dst_lane < src_lane else "right"
    left_edge, right_edge = stage_extents[src_stage]
    return route_c_loop(
        src_box,
        dst_box,
        offset=offset,
        side=side,
        bound=left_edge if side == "left" else right_edge,
    )


def _stage_extents(
    boxes_by_id: Mapping[str, Box], slot_by_id: Mapping[str, StageSlot]
) -> dict[int, tuple[float, float]]:
    """Return each stage's outer (min_left, max_right) across every card in it.

    A same-stage C-loop must clear every card sharing its column, not only
    its own two endpoints, so its corridor is anchored to this shared
    extent rather than to the two boxes the wire happens to connect.
    """
    extents: dict[int, tuple[float, float]] = {}
    for card_id, (x, _y, width, _height) in boxes_by_id.items():
        stage = slot_by_id[card_id].stage
        left, right = extents.get(stage, (x, x + width))
        extents[stage] = (min(left, x), max(right, x + width))
    return extents


def _pill_bounds(
    label_anchor: AnchorOffset, label: str, chrome: CardChrome
) -> tuple[float, float, float, float]:
    """Return the centered (x, y, width, height) rect for a flow wire's pill."""
    width = _pill_width(label, chrome)
    height = line_height(chrome.caption_size, chrome) + 2 * chrome.chip_padding_y
    x, y = label_anchor
    return (x - width / 2, y - height / 2, width, height)


type _TrackAxis = Literal["height", "width"]


def _flow_track_group(
    wire: Wire, *, slot_by_id: Mapping[str, StageSlot]
) -> tuple[str, _TrackAxis] | None:
    """Classify a flow wire's exterior track pool and its packing axis.

    A forward wire routes directly with no exterior offset (``None``). A
    skip wire always bows above every stage it crosses, so every skip wire
    shares one upper corridor. A back wire returning to a strictly earlier
    stage always sags below every stage it crosses, so every such wire
    shares one lower corridor. A back wire that stays within its own stage
    loops around that stage's own left or right side instead; a stage's
    left loops and right loops each pack their own independent corridor, so
    a loop in one stage never reserves room in another.
    """
    if wire.kind == "forward":
        return None
    if wire.kind == "skip":
        return ("skip", "height")
    src_stage = slot_by_id[wire.src].stage
    dst_stage = slot_by_id[wire.dst].stage
    if dst_stage < src_stage:
        return ("back", "height")
    side = "left" if slot_by_id[wire.dst].lane < slot_by_id[wire.src].lane else "right"
    return (f"loop-{side}-{src_stage}", "width")


def _flow_track_extent(
    wire: Wire,
    *,
    axis: _TrackAxis,
    chrome: CardChrome,
    styles: Mapping[EdgeKind, EdgeStyle],
) -> float:
    """Return half the footprint a wire's track reserves along its packing axis.

    A labeled wire reserves half its own pill's height (a horizontal,
    vertically-stacked corridor) or width (a vertical, horizontally-stacked
    C-loop corridor); an unlabeled wire has no pill, so it reserves half
    its resolved stroke width instead.
    """
    if wire.label is not None:
        if axis == "height":
            return (line_height(chrome.caption_size, chrome) + 2 * chrome.chip_padding_y) / 2
        return _pill_width(wire.label, chrome) / 2
    return styles[cast(EdgeKind, wire.kind)].width / 2


def _flow_offsets(
    wires: tuple[Wire, ...],
    *,
    slot_by_id: Mapping[str, StageSlot],
    chrome: CardChrome,
    styles: Mapping[EdgeKind, EdgeStyle],
) -> dict[str, float]:
    """Pack every exterior route into its own track pool, closest-first.

    Tracks pack independently per corridor key (`_flow_track_group`) in wire
    declaration order. A pool's first track clears its own half-extent plus
    one `chip_gap` from the stage boundary, so even a single loop pill sits
    fully outside its stage's cards. Each later track in the same pool
    clears the prior track's half-extent, its own half-extent, and one more
    `chip_gap`, so consecutive pills (or bare strokes, for unlabeled wires)
    never overlap.
    """
    offsets: dict[str, float] = {}
    tracks: dict[str, tuple[float, float]] = {}
    for wire in wires:
        group = _flow_track_group(wire, slot_by_id=slot_by_id)
        if group is None:
            continue
        key, axis = group
        extent = _flow_track_extent(wire, axis=axis, chrome=chrome, styles=styles)
        if key in tracks:
            prev_offset, prev_extent = tracks[key]
            offset = prev_offset + prev_extent + chrome.chip_gap + extent
        else:
            offset = extent + chrome.chip_gap
        tracks[key] = (offset, extent)
        offsets[wire.id] = offset
    return offsets


def _flow_geometry(
    wires: tuple[Wire, ...],
    boxes_by_id: dict[str, Box],
    slot_by_id: dict[str, StageSlot],
    offsets: Mapping[str, float],
    chrome: CardChrome,
) -> tuple[dict[str, Route], dict[str, tuple[float, float, float, float]]]:
    """Resolve every wire's route and each labeled wire's pill bounds."""
    stage_extents = _stage_extents(boxes_by_id, slot_by_id)
    routes: dict[str, Route] = {}
    for wire in wires:
        src_slot = slot_by_id[wire.src]
        dst_slot = slot_by_id[wire.dst]
        routes[wire.id] = _flow_route(
            wire,
            boxes_by_id[wire.src],
            boxes_by_id[wire.dst],
            src_stage=src_slot.stage,
            dst_stage=dst_slot.stage,
            src_lane=src_slot.lane,
            dst_lane=dst_slot.lane,
            offset=offsets.get(wire.id, 0.0),
            stage_extents=stage_extents,
        )
    pills = {
        wire.id: _pill_bounds(routes[wire.id].label_anchor, wire.label, chrome)
        for wire in wires
        if wire.label is not None
    }
    return routes, pills


def _flow_bounds_extrema(
    wires: tuple[Wire, ...],
    routes: Mapping[str, Route],
    pills: Mapping[str, tuple[float, float, float, float]],
    *,
    styles: Mapping[EdgeKind, EdgeStyle],
    pill_halo: float,
) -> tuple[float, float, float, float]:
    """Return every painted route stroke's and pill halo's outer (x0, y0, x1, y1).

    A route's centerline bounds only cover its bezier anchor points, so a
    thick stroke paints outside them; expanding by half the wire's resolved
    stroke width keeps the actual painted line inside the result. A pill's
    rect border straddles its nominal edge the same way, so expanding by
    half the chrome border width keeps that outline inside too.
    """
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for wire in wires:
        half = styles[cast(EdgeKind, wire.kind)].width / 2
        x0, y0, x1, y1 = routes[wire.id].bounds
        xs0.append(x0 - half)
        ys0.append(y0 - half)
        xs1.append(x1 + half)
        ys1.append(y1 + half)
    for px, py, pw, ph in pills.values():
        xs0.append(px - pill_halo)
        ys0.append(py - pill_halo)
        xs1.append(px + pw + pill_halo)
        ys1.append(py + ph + pill_halo)
    return (
        min(xs0, default=0.0),
        min(ys0, default=0.0),
        max(xs1, default=0.0),
        max(ys1, default=0.0),
    )


def _graph_measure_staged(
    nodes: tuple[tuple[str, Card], ...],
    slots: tuple[StageSlot, ...],
    wires: tuple[Wire, ...],
    *,
    lane_gap: int,
    stage_gap: int,
    padding: int,
    collapsible: tuple[str, ...],
    chrome: CardChrome,
    theme: Theme,
    edge_styles: tuple[tuple[EdgeKind, EdgeStyle], ...],
) -> _GraphLayout:
    """Measure rebound cards, resolve staged boxes, and route flow wires.

    Every staged collapsible card folds along its right edge, wireless or
    wired: ``Graph.layer_gap``'s validated >= 18 minimum already reserves
    enough horizontal room for an interior column's nub, but the last stage
    has no following column to absorb it, so its collapsible cards' own
    actual box widths grow the canvas instead.
    """
    measured = {card_id: card.measure() for card_id, card in nodes}
    slot_by_id = {slot.card_id: slot for slot in slots}
    entries = tuple(
        (
            card_id,
            slot_by_id[card_id].stage,
            slot_by_id[card_id].lane,
            measured[card_id].width,
            measured[card_id].expanded_height,
        )
        for card_id, _ in nodes
    )
    width, height, boxes = staged_boxes(
        entries, lane_gap=lane_gap, stage_gap=stage_gap, padding=padding
    )
    anchors = tuple(
        (
            card_id,
            ((0.0, box_height / 2), (box_width, box_height / 2)),
        )
        for card_id, (_x, _y, box_width, box_height) in boxes
    )
    last_stage = max(slot.stage for slot in slots)
    for card_id, (x, _y, box_width, _height) in boxes:
        if card_id in collapsible and slot_by_id[card_id].stage == last_stage:
            width = max(width, x + box_width + 18)

    if not wires:
        nub_anchors = tuple(
            (card_id, (float(x + box_width), y + box_height / 2, "right"))
            for card_id, (x, y, box_width, box_height) in boxes
            if card_id in collapsible
        )
        return _GraphLayout(
            MeasuredGraph(width, height, boxes), anchors, (), nub_anchors=nub_anchors
        )

    styles = _resolve_edge_styles(theme, edge_styles)
    pill_halo = chrome.border_width / 2
    offsets = _flow_offsets(wires, slot_by_id=slot_by_id, chrome=chrome, styles=styles)
    boxes_by_id = dict(boxes)
    routes, pills = _flow_geometry(wires, boxes_by_id, slot_by_id, offsets, chrome)

    min_x0, min_y0, _max_x0, _max_y0 = _flow_bounds_extrema(
        wires, routes, pills, styles=styles, pill_halo=pill_halo
    )
    min_x = min(0.0, min_x0)
    min_y = min(0.0, min_y0)
    shift_x = math.ceil(-min_x) if min_x < 0 else 0
    shift_y = math.ceil(-min_y) if min_y < 0 else 0
    if shift_x or shift_y:
        boxes = tuple(
            (card_id, (x + shift_x, y + shift_y, box_width, box_height))
            for card_id, (x, y, box_width, box_height) in boxes
        )
        boxes_by_id = dict(boxes)
        width += shift_x
        height += shift_y
        routes, pills = _flow_geometry(wires, boxes_by_id, slot_by_id, offsets, chrome)

    _min_x1, _min_y1, max_x, max_y = _flow_bounds_extrema(
        wires, routes, pills, styles=styles, pill_halo=pill_halo
    )
    width = math.ceil(max(float(width), max_x))
    height = math.ceil(max(float(height), max_y))

    wire_geometry = tuple(
        (wire.id, (routes[wire.id].path, routes[wire.id].label_anchor)) for wire in wires
    )
    nub_anchors = tuple(
        (card_id, (float(x + box_width), y + box_height / 2, "right"))
        for card_id, (x, y, box_width, box_height) in boxes
        if card_id in collapsible
    )
    flow_pills = tuple((wire.id, pills[wire.id]) for wire in wires if wire.id in pills)
    return _GraphLayout(
        MeasuredGraph(width, height, boxes),
        anchors,
        wire_geometry,
        nub_anchors=nub_anchors,
        flow_pills=flow_pills,
    )


@dataclass(frozen=True, slots=True)
class Graph:
    """A validated, themed graph of cards and explicit vertical wires."""

    nodes: tuple[tuple[str, Card], ...]
    layout: Slotted | LayeredDag | Staged
    wires: tuple[Wire, ...] = ()
    collapsible: tuple[str, ...] = ()
    visibility: tuple[str, ...] | None = None
    rules: tuple[StateRule, ...] = ()
    gap: int = 36
    layer_gap: int = 56
    dom_prefix: str = "g0"
    theme: Theme = DEFAULT
    chrome: CardChrome = DEFAULT_CHROME
    edge_styles: tuple[tuple[EdgeKind, EdgeStyle], ...] = ()
    _rebound_cards: tuple[Card, ...] = field(init=False, repr=False, compare=False)
    _blocker_families: Mapping[str, frozenset[frozenset[str]]] = field(
        init=False, repr=False, compare=False
    )
    _compiled: _CompiledState = field(init=False, repr=False, compare=False)
    _layout: _GraphLayout = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Canonicalize, validate, and cache graph topology."""
        _graph_validate_settings(self)
        nodes = _graph_nodes(self.nodes)
        node_ids = tuple(node_id for node_id, _ in nodes)
        known_cards = set(node_ids)
        wires = _graph_wires(self.wires, known_cards=known_cards)
        collapsible = _graph_collapsible(self.collapsible, known_cards)
        edge_styles = _graph_edge_styles(self.edge_styles)
        if isinstance(self.layout, Staged):
            if collapsible and self.layer_gap < 18:
                raise SpecError(
                    "Graph.layer_gap must be at least 18 when staged collapsible cards are present"
                )
            staged_slots = self.layout.slots
            _graph_validate_staged(staged_slots, known_cards)
            slots: tuple[Slot, ...] = ()
        else:
            staged_slots = ()
            slots = _graph_resolve_slots(self.layout, node_ids=node_ids, wires=wires)
            _graph_validate_layout(slots, known_cards)
            layers_by_id = {slot.card_id: slot.layer for slot in slots}
            _graph_validate_wire_layers(wires, layers_by_id=layers_by_id)
        _graph_validate_flow_geometry(self.layout, wires)
        _graph_validate_forward_pill_width(
            wires, stage_gap=self.layer_gap, chrome=self.chrome, collapsible=collapsible
        )
        # Back edges are paint-only: they never enter visibility topology,
        # blocker families, or derived/injected hide rules; only forward and
        # skip wires ("topology_wires") do.
        topology_wires = tuple(wire for wire in wires if wire.kind != "back")
        wire_ids = tuple(wire.id for wire in topology_wires)
        all_wire_ids = tuple(wire.id for wire in wires)
        label_offset = self.chrome.caption_size + 2
        labeled_layer_gap = label_offset + self.chrome.caption_size + 4
        if not isinstance(self.layout, Staged):
            # Vertical label-band checks apply only to the row/column layouts;
            # Staged has no layers and defers wire/label geometry to R6.
            if collapsible and self.layer_gap < 18:
                raise SpecError(
                    "Graph.layer_gap must be at least 18 when collapsible cards are present"
                )
            if wires and self.layer_gap < 18:
                raise SpecError("Graph.layer_gap must be at least 18 when wires are present")
            if (
                any(wire.label is not None for wire in wires)
                and self.layer_gap < labeled_layer_gap
            ):
                raise SpecError(
                    f"Graph.layer_gap must be at least {labeled_layer_gap} when "
                    "wire labels are present"
                )
            collapsible_layers = {
                layers_by_id[card_id] for card_id in collapsible if card_id in layers_by_id
            }
            labeled_destination_bands = {
                layers_by_id[wire.dst] - 1 for wire in wires if wire.label is not None
            }
            shared_band_gap = 18 + label_offset + self.chrome.caption_size
            if collapsible_layers & labeled_destination_bands and self.layer_gap < shared_band_gap:
                raise SpecError(
                    f"Graph.layer_gap must be at least {shared_band_gap} when "
                    "labels share a band with fold nubs"
                )
        cards, rebound_nodes = _graph_rebound_nodes(nodes, theme=self.theme, chrome=self.chrome)
        card_options = {node_id: card.control_options() for node_id, card in rebound_nodes}
        visibility, visibility_wires = _graph_visibility(
            self.visibility, wires=topology_wires, wire_ids=wire_ids, all_wire_ids=all_wire_ids
        )
        rules = _graph_rules(
            self.rules,
            known_cards=known_cards,
            wire_ids=wire_ids,
            all_wire_ids=all_wire_ids,
            collapsible=collapsible,
            card_options=card_options,
        )
        visibility_edges = tuple((wire.src, wire.dst) for wire in visibility_wires)
        check_acyclic(node_ids, visibility_edges)
        blockers = blocker_families(node_ids, visibility_edges, collapsible)
        if not isinstance(self.layout, Staged):
            # Staged forbids shared stage/lane positions outright; the
            # select-governed shared-slot proof only applies to layered rows.
            _graph_shared_slot_proof(
                _graph_shared_slot_groups(slots), cards=cards, rules=rules, blockers=blockers
            )
        _graph_validate_rule_controllers(rules, collapsible=collapsible, blockers=blockers)
        object.__setattr__(self, "nodes", tuple(rebound_nodes))
        object.__setattr__(self, "wires", wires)
        object.__setattr__(self, "collapsible", collapsible)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "edge_styles", edge_styles)
        object.__setattr__(self, "_rebound_cards", tuple(card for _, card in rebound_nodes))
        object.__setattr__(self, "_blocker_families", blockers)
        object.__setattr__(
            self,
            "_compiled",
            _compile_state(
                nodes=rebound_nodes,
                wires=wires,
                collapsible=collapsible,
                blockers=blockers,
                rules=rules,
                card_options=card_options,
                dom_prefix=self.dom_prefix,
            ),
        )

        if isinstance(self.layout, Staged):
            layout = _graph_measure_staged(
                tuple(rebound_nodes),
                staged_slots,
                wires,
                lane_gap=self.gap,
                stage_gap=self.layer_gap,
                padding=self.chrome.padding,
                collapsible=collapsible,
                chrome=self.chrome,
                theme=self.theme,
                edge_styles=edge_styles,
            )
        else:
            layout = _graph_measure(
                tuple(rebound_nodes),
                slots,
                wires,
                collapsible=collapsible,
                gap=self.gap,
                layer_gap=self.layer_gap,
                chrome=self.chrome,
                padding=self.chrome.padding,
            )
            # The ladder raises stacked labels by label_step per row; every band
            # must fit its OWN occupied rows (SpecError still at construction) -
            # a deep ladder in one band never inflates an unrelated band.
            label_step = self.chrome.caption_size + 4
            band_depths = dict(layout.label_band_depths)
            overall_extra = max(band_depths.values(), default=0) * label_step
            if overall_extra and self.layer_gap < labeled_layer_gap + overall_extra:
                raise SpecError(
                    f"Graph.layer_gap must be at least {labeled_layer_gap + overall_extra} "
                    "to fit the stacked wire labels"
                )
            shared_extra = (
                max(
                    (depth for band, depth in band_depths.items() if band in collapsible_layers),
                    default=0,
                )
                * label_step
            )
            if (
                collapsible_layers & labeled_destination_bands
                and self.layer_gap < shared_band_gap + shared_extra
            ):
                raise SpecError(
                    f"Graph.layer_gap must be at least {shared_band_gap + shared_extra} "
                    "to fit stacked labels beside fold nubs"
                )
        object.__setattr__(self, "_layout", layout)

    def measure(self) -> MeasuredGraph:
        """Return this graph's cached exact slotted layout."""
        return self._layout.measured

    def as_raw_html(self) -> str:
        """Render this graph as deterministic standalone HTML."""
        from coeftable.graph.render import render_graph

        return render_graph(self)

    def _repr_html_(self) -> str:
        """Render this graph for notebook display."""
        return self.as_raw_html()

    def with_theme(self, theme: Theme) -> Graph:
        """Return a copy atomically rebound to ``theme``."""
        return replace(self, theme=theme)
