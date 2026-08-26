"""Validated leaf values for the experimental graph layer."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from coeftable.cards.card import Card
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.errors import SpecError
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


def _graph_shared_slot_proof(
    group: frozenset[str],
    *,
    cards: Mapping[str, Card],
    rules: tuple[StateRule, ...],
    blockers: Mapping[str, frozenset[frozenset[str]]],
) -> None:
    """Require one external select to prove exclusivity for a shared slot."""
    candidates: list[tuple[str, str]] = []
    for card_id, card in cards.items():
        if card_id in group:
            continue
        for key, options in card.control_options().items():
            if len(options) != len(group):
                continue
            if len(
                {
                    rule.when_all[0].option
                    for rule in rules
                    if len(rule.when_all) == 1
                    and rule.when_all[0].predicate == "option_checked"
                    and rule.when_all[0].control == ControlRef(card_id, key)
                }
            ) != len(options):
                continue
            selected: set[str] = set()
            valid = True
            for option in options:
                matches = [
                    rule
                    for rule in rules
                    if len(rule.when_all) == 1
                    and rule.when_all[0]
                    == Atom(ControlRef(card_id, key), "option_checked", option)
                ]
                if len(matches) != 1:
                    valid = False
                    break
                hidden = set(matches[0].hide_cards)
                if not hidden <= group or len(group - hidden) != 1:
                    valid = False
                    break
                selected.update(group - hidden)
            if valid and selected == group:
                candidates.append((card_id, key))

    if len(candidates) != 1:
        raise SpecError("shared slots require one governing external SelectControl")
    controller, _ = candidates[0]
    if blockers[controller]:
        raise SpecError("shared-slot controller must never be hidden")
    if any(controller in rule.hide_cards for rule in rules):
        raise SpecError("shared-slot controller must never be hidden")


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

    def __post_init__(self) -> None:
        """Canonicalize, validate, and cache graph topology."""
        if not isinstance(self.layout, Slotted):
            raise SpecError("Graph.layout must be a Slotted")
        if not isinstance(self.theme, Theme):
            raise SpecError("Graph.theme must be a Theme")
        if not isinstance(self.chrome, CardChrome):
            raise SpecError("Graph.chrome must be a CardChrome")
        _graph_positive_int(self.gap, name="Graph.gap")
        _graph_positive_int(self.layer_gap, name="Graph.layer_gap")
        if (
            not isinstance(self.dom_prefix, str)
            or re.fullmatch(r"[a-z][a-z0-9-]*", self.dom_prefix) is None
        ):
            raise SpecError("Graph.dom_prefix must match [a-z][a-z0-9-]*")

        nodes = _graph_nodes(self.nodes)
        node_ids = tuple(node_id for node_id, _ in nodes)
        known_cards = set(node_ids)
        slots = self.layout.slots
        slot_ids = tuple(slot.card_id for slot in slots)
        if len(set(slot_ids)) != len(slot_ids) or set(slot_ids) != known_cards:
            raise SpecError("Graph.layout.slots must cover graph node ids exactly once")
        layers = {slot.layer for slot in slots}
        slot_domain = {slot.slot for slot in slots}
        if layers != set(range(max(layers) + 1)) or slot_domain != set(
            range(max(slot_domain) + 1)
        ):
            raise SpecError("Graph.layout layer and slot indices must be dense from zero")

        wires = _canonical(self.wires, name="Graph.wires")
        for index, wire in enumerate(wires):
            if not isinstance(wire, Wire):
                raise SpecError(f"Graph.wires[{index}] must be a Wire")
        wires = cast(tuple[Wire, ...], wires)
        wire_ids = tuple(wire.id for wire in wires)
        if len(set(wire_ids)) != len(wire_ids):
            raise SpecError("Graph.wires ids must be unique")
        if any(wire.src not in known_cards or wire.dst not in known_cards for wire in wires):
            raise SpecError("Graph.wires endpoints must reference known cards")
        layers_by_id = {slot.card_id: slot.layer for slot in slots}
        if any(layers_by_id[wire.src] >= layers_by_id[wire.dst] for wire in wires):
            raise SpecError("Graph.wires must route strictly downward")

        collapsible = _canonical(self.collapsible, name="Graph.collapsible")
        for index, card_id in enumerate(collapsible):
            _non_empty_str(card_id, name=f"Graph.collapsible[{index}]")
        if len(set(collapsible)) != len(collapsible):
            raise SpecError("Graph.collapsible entries must be unique")
        if any(card_id not in known_cards for card_id in collapsible):
            raise SpecError("Graph.collapsible references an unknown card")
        collapsible = cast(tuple[str, ...], collapsible)
        cards: dict[str, Card] = {}
        rebound_nodes: list[tuple[str, Card]] = []
        for card_id, card in nodes:
            if card.chrome != self.chrome:
                raise SpecError("Graph.chrome must match every Card.chrome")
            rebound = card.with_theme(self.theme) if card.theme != self.theme else card
            cards[card_id] = rebound
            rebound_nodes.append((card_id, rebound))
        card_options = {node_id: card.control_options() for node_id, card in rebound_nodes}

        visibility: tuple[str, ...] | None
        if self.visibility is None:
            visibility = None
            visibility_wires = wires
        else:
            visibility_value = _canonical(self.visibility, name="Graph.visibility")
            for index, wire_id in enumerate(visibility_value):
                _non_empty_str(wire_id, name=f"Graph.visibility[{index}]")
            if len(set(visibility_value)) != len(visibility_value):
                raise SpecError("Graph.visibility entries must be unique")
            if any(wire_id not in wire_ids for wire_id in visibility_value):
                raise SpecError("Graph.visibility references an unknown wire")
            visibility = cast(tuple[str, ...], visibility_value)
            visibility_wires = tuple(wire for wire in wires if wire.id in set(visibility))

        rules = _canonical(self.rules, name="Graph.rules")
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
        rules = cast(tuple[StateRule, ...], rules)

        visibility_edges = tuple((wire.src, wire.dst) for wire in visibility_wires)
        check_acyclic(node_ids, visibility_edges)
        blockers = blocker_families(node_ids, visibility_edges, collapsible)

        positions: dict[tuple[int, int], list[str]] = {}
        for slot in slots:
            positions.setdefault((slot.layer, slot.slot), []).append(slot.card_id)
        for group_ids in positions.values():
            if len(group_ids) > 1:
                _graph_shared_slot_proof(
                    frozenset(group_ids), cards=cards, rules=rules, blockers=blockers
                )

        object.__setattr__(self, "nodes", tuple(rebound_nodes))
        object.__setattr__(self, "wires", wires)
        object.__setattr__(self, "collapsible", collapsible)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "_rebound_cards", tuple(card for _, card in rebound_nodes))
        object.__setattr__(self, "_blocker_families", blockers)
