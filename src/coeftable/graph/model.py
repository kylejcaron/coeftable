"""Validated leaf values for the experimental graph layer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, cast

from coeftable.errors import SpecError
from coeftable.theme import Role

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
