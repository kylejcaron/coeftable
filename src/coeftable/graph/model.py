"""Validated leaf values for the experimental graph layer."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from coeftable.cards.card import Card
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.errors import SpecError
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
        _non_empty_str(self.option, name="Atom.option")


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
        for index, atom in enumerate(when_all):
            if not isinstance(atom, Atom):
                raise SpecError(f"StateRule.when_all[{index}] must be an Atom")
        if len(set(when_all)) != len(when_all):
            raise SpecError("StateRule.when_all must not contain duplicates")

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
class Wire:
    """A directed, downward graph edge and optional semantic label."""

    id: str
    src: str
    dst: str
    label: str | None = None
    label_role: Role | None = None
    label_color: str | None = None

    def __post_init__(self) -> None:
        """Validate endpoints and optional label styling."""
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
    group: frozenset[str],
    *,
    card_id: str,
    key: str,
    options: tuple[str, ...],
    rules: tuple[StateRule, ...],
) -> tuple[StateRule, ...] | None:
    """Return exact one-rule-per-option partition rules, if present."""
    governing: list[StateRule] = []
    selected: set[str] = set()
    for option in options:
        matches = [
            rule
            for rule in rules
            if len(rule.when_all) == 1
            and rule.when_all[0] == Atom(ControlRef(card_id, key), "option_checked", option)
        ]
        if len(matches) != 1:
            return None
        rule = matches[0]
        hidden = set(rule.hide_cards)
        if not hidden <= group or len(group - hidden) != 1:
            return None
        governing.append(rule)
        selected.update(group - hidden)
    if selected != group:
        return None
    return tuple(governing)


def _graph_resolve_shared_slot_controller(
    group: frozenset[str],
    *,
    cards: Mapping[str, Card],
    rules: tuple[StateRule, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> tuple[str, tuple[StateRule, ...]]:
    """Resolve the sole external controller and enforce its visibility."""
    candidates: list[tuple[str, tuple[StateRule, ...]]] = []
    for card_id, card in cards.items():
        if card_id in group:
            continue
        for key, options in card.control_options().items():
            if len(options) != len(group):
                continue
            governing = _graph_partition_rules(
                group,
                card_id=card_id,
                key=key,
                options=options,
                rules=rules,
            )
            if governing is not None:
                candidates.append((card_id, governing))

    if len(candidates) != 1:
        raise SpecError("shared slots require one governing external SelectControl")
    controller, governing = candidates[0]
    if blockers[controller] or any(controller in rule.hide_cards for rule in rules):
        raise SpecError("shared-slot controller must never be hidden")
    return controller, governing


def _graph_reject_stray_shared_slot_rules(
    group: frozenset[str],
    *,
    rules: tuple[StateRule, ...],
    governing: tuple[StateRule, ...],
) -> None:
    """Reject card-hiding rules that are not exact partition rules."""
    governing_set = set(governing)
    if any(set(rule.hide_cards) & group and rule not in governing_set for rule in rules):
        raise SpecError("shared-slot rules must be exact governing partition rules")


def _graph_shared_slot_proof(
    group: frozenset[str],
    *,
    cards: Mapping[str, Card],
    rules: tuple[StateRule, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> None:
    """Require one external select to prove exclusivity for a shared slot."""
    _, governing = _graph_resolve_shared_slot_controller(
        group, cards=cards, rules=rules, blockers=blockers
    )
    _graph_reject_stray_shared_slot_rules(group, rules=rules, governing=governing)


def _graph_validate_settings(graph: Graph) -> None:
    """Validate graph-wide scalar settings and object types."""
    if not isinstance(graph.layout, Slotted):
        raise SpecError("Graph.layout must be a Slotted")
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


def _graph_wires(
    value: object,
    *,
    known_cards: set[str],
    layers_by_id: Mapping[str, int],
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
    if any(wire.src not in known_cards or wire.dst not in known_cards for wire in result):
        raise SpecError("Graph.wires endpoints must reference known cards")
    if any(layers_by_id[wire.src] >= layers_by_id[wire.dst] for wire in result):
        raise SpecError("Graph.wires must route strictly downward")
    return result


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
) -> tuple[tuple[str, ...] | None, tuple[Wire, ...]]:
    """Canonicalize the selected visibility wires."""
    if value is None:
        return None, wires
    visibility_value = _canonical(value, name="Graph.visibility")
    for index, wire_id in enumerate(visibility_value):
        _non_empty_str(wire_id, name=f"Graph.visibility[{index}]")
    if len(set(visibility_value)) != len(visibility_value):
        raise SpecError("Graph.visibility entries must be unique")
    if any(wire_id not in wire_ids for wire_id in visibility_value):
        raise SpecError("Graph.visibility references an unknown wire")
    visibility = cast(tuple[str, ...], visibility_value)
    selected = set(visibility)
    return visibility, tuple(wire for wire in wires if wire.id in selected)


def _graph_rules(
    value: object,
    *,
    known_cards: set[str],
    wire_ids: tuple[str, ...],
    collapsible: tuple[str, ...],
    card_options: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[StateRule, ...]:
    """Canonicalize and validate graph state rules."""
    rules = _canonical(value, name="Graph.rules")
    for index, rule in enumerate(rules):
        if not isinstance(rule, StateRule):
            raise SpecError(f"Graph.rules[{index}] must be a StateRule")
        if any(card_id not in known_cards for card_id in rule.hide_cards):
            raise SpecError("Graph.rules hide_cards must reference known cards")
        if any(wire_id not in wire_ids for wire_id in rule.hide_wires):
            raise SpecError("Graph.rules hide_wires must reference known wires")
        for atom in rule.when_all:
            if atom.control.card_id not in known_cards:
                raise SpecError("Graph.rules controls must reference known cards")
            options = card_options[atom.control.card_id]
            if atom.predicate == "checked":
                if atom.control.card_id not in collapsible:
                    raise SpecError("Graph.rules checked controls must be collapsible cards")
            elif atom.control.key not in options:
                raise SpecError("Graph.rules option controls must reference known selects")
            elif atom.option not in options[atom.control.key]:
                raise SpecError("Graph.rules option must reference a known select option")
    return cast(tuple[StateRule, ...], rules)


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


@dataclass(frozen=True, slots=True)
class _GraphLayout:
    """Internal graph geometry, including the measured wire attachments."""

    measured: MeasuredGraph
    anchors: GraphAnchors


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
    *,
    gap: int,
    layer_gap: int,
    padding: int,
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
    width = sum(column_widths) + gap * (len(column_widths) - 1) + 2 * padding
    height = sum(layer_heights) + layer_gap * (len(layer_heights) - 1) + 2 * padding
    footprint = MeasuredGraph(width, height, tuple(boxes))
    anchor_offsets: list[tuple[str, tuple[AnchorOffset, AnchorOffset]]] = []
    for card_id, _ in nodes:
        by_name = {anchor.name: (anchor.x, anchor.y) for anchor in measured[card_id].anchors}
        anchor_offsets.append((card_id, (by_name["in"], by_name["out"])))
    return _GraphLayout(footprint, tuple(anchor_offsets))


@dataclass(frozen=True, slots=True)
class Graph:
    """A validated, themed graph of cards and explicit vertical wires."""

    nodes: tuple[tuple[str, Card], ...]
    layout: Slotted
    wires: tuple[Wire, ...] = ()
    collapsible: tuple[str, ...] = ()
    visibility: tuple[str, ...] | None = None
    rules: tuple[StateRule, ...] = ()
    gap: int = 36
    layer_gap: int = 56
    dom_prefix: str = "g0"
    theme: Theme = DEFAULT
    chrome: CardChrome = DEFAULT_CHROME
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
        slots = self.layout.slots
        _graph_validate_layout(slots, known_cards)
        layers_by_id = {slot.card_id: slot.layer for slot in slots}
        wires = _graph_wires(self.wires, known_cards=known_cards, layers_by_id=layers_by_id)
        wire_ids = tuple(wire.id for wire in wires)
        collapsible = _graph_collapsible(self.collapsible, known_cards)
        cards, rebound_nodes = _graph_rebound_nodes(nodes, theme=self.theme, chrome=self.chrome)
        card_options = {node_id: card.control_options() for node_id, card in rebound_nodes}
        visibility, visibility_wires = _graph_visibility(
            self.visibility, wires=wires, wire_ids=wire_ids
        )
        rules = _graph_rules(
            self.rules,
            known_cards=known_cards,
            wire_ids=wire_ids,
            collapsible=collapsible,
            card_options=card_options,
        )
        visibility_edges = tuple((wire.src, wire.dst) for wire in visibility_wires)
        check_acyclic(node_ids, visibility_edges)
        blockers = blocker_families(node_ids, visibility_edges, collapsible)
        for group in _graph_shared_slot_groups(slots):
            _graph_shared_slot_proof(group, cards=cards, rules=rules, blockers=blockers)
        object.__setattr__(self, "nodes", tuple(rebound_nodes))
        object.__setattr__(self, "wires", wires)
        object.__setattr__(self, "collapsible", collapsible)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "rules", rules)
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

        object.__setattr__(
            self,
            "_layout",
            _graph_measure(
                tuple(rebound_nodes),
                slots,
                gap=self.gap,
                layer_gap=self.layer_gap,
                padding=self.chrome.padding,
            ),
        )

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
