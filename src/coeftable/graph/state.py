"""Internal compiler for graph visibility state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from coeftable.graph.model import Atom, StateRule, Wire


@dataclass(frozen=True, slots=True)
class _CompiledState:
    """Ordinal DOM bindings and minimal visibility rules for a graph."""

    card_dom_ids: tuple[str, ...]
    wire_dom_ids: tuple[str, ...]
    nub_dom_ids: Mapping[str, str]
    control_dom_ids: Mapping[str, Mapping[str, str]]
    rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]


def _css_string(value: str) -> str:
    """Quote and CSS-string-escape a select option value.

    Carriage returns cannot occur: SelectControl rejects them at
    construction (they cannot survive an HTML attribute round-trip).
    """
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character == "\n":
            escaped.append("\\A ")
        elif character == "\f":
            escaped.append("\\C ")
        elif codepoint == 0:
            escaped.append("\\FFFD ")
        elif character == "<":
            escaped.append("\\3C ")
        elif character == ">":
            escaped.append("\\3E ")
        elif codepoint < 0x20 or codepoint == 0x7F:
            escaped.append(f"\\{codepoint:X} ")
        else:
            escaped.append(character)
    return '"' + "".join(escaped) + '"'


def _minimal_family(family: Iterable[frozenset[str]]) -> tuple[frozenset[str], ...]:
    """Return unique inclusion-minimal sets in deterministic order."""
    unique = set(family)
    return tuple(
        sorted(
            (candidate for candidate in unique if not any(other < candidate for other in unique)),
            key=lambda candidate: (len(candidate), tuple(sorted(candidate))),
        )
    )


def _wire_family(
    src: str,
    dst: str,
    *,
    blockers: Mapping[str, frozenset[frozenset[str]]],
    collapsible: frozenset[str],
) -> tuple[frozenset[str], ...]:
    """Compute the minimal blocker family for one wire."""
    family = set(blockers[src]) | set(blockers[dst])
    if src in collapsible:
        family.add(frozenset({src}))
    return _minimal_family(family)


def _atom_selector(
    atom: Atom,
    *,
    nub_dom_ids: Mapping[str, str],
    control_dom_ids: Mapping[str, Mapping[str, str]],
) -> str:
    """Compile one validated atom to a CSS selector."""
    control = atom.control
    card_id = control.card_id
    if atom.predicate == "checked":
        return f"#{nub_dom_ids[card_id]}:checked"
    control_key = cast(str, control.key)
    option = cast(str, atom.option)
    control_id = control_dom_ids[card_id][control_key]
    return f"#{control_id} option[value={_css_string(option)}]:checked"


def _add_rule(
    compiled: dict[tuple[str, ...], set[str]],
    conditions: Iterable[str],
    targets: Iterable[str],
) -> None:
    """Add targets to a condition bucket, omitting targetless rules."""
    target_set = set(targets)
    if not target_set:
        return
    condition_set = tuple(sorted(set(conditions)))
    compiled.setdefault(condition_set, set()).update(target_set)


def _emit_rules(
    *,
    nodes: tuple[tuple[str, object], ...],
    wires: tuple[Wire, ...],
    collapsible: frozenset[str],
    blockers: Mapping[str, frozenset[frozenset[str]]],
    injected: tuple[StateRule, ...],
    card_dom_ids: Mapping[str, str],
    wire_dom_ids: Mapping[str, str],
    nub_dom_ids: Mapping[str, str],
    control_dom_ids: Mapping[str, Mapping[str, str]],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Emit derived and injected rules, merging identical conditions."""
    compiled: dict[tuple[str, ...], set[str]] = {}
    for card_id, _ in nodes:
        for blocker_set in blockers[card_id]:
            conditions = (f"#{nub_dom_ids[blocked]}:checked" for blocked in blocker_set)
            _add_rule(compiled, conditions, (card_dom_ids[card_id],))
    for wire in wires:
        family = _wire_family(
            wire.src,
            wire.dst,
            blockers=blockers,
            collapsible=collapsible,
        )
        for blocker_set in family:
            conditions = (f"#{nub_dom_ids[blocked]}:checked" for blocked in blocker_set)
            _add_rule(compiled, conditions, (wire_dom_ids[wire.id],))
    for rule in injected:
        conditions = (
            _atom_selector(
                atom,
                nub_dom_ids=nub_dom_ids,
                control_dom_ids=control_dom_ids,
            )
            for atom in rule.when_all
        )
        hidden_cards = set(rule.hide_cards)
        targets = [card_dom_ids[card_id] for card_id in hidden_cards]
        targets.extend(wire_dom_ids[wire_id] for wire_id in rule.hide_wires)
        targets.extend(
            wire_dom_ids[wire.id]
            for wire in wires
            if wire.src in hidden_cards or wire.dst in hidden_cards
        )
        _add_rule(compiled, conditions, targets)
    return tuple(
        (conditions, tuple(sorted(targets))) for conditions, targets in sorted(compiled.items())
    )


def _compile_state(
    *,
    nodes: Sequence[tuple[str, object]],
    wires: Sequence[Wire],
    topology_wires: Sequence[Wire],
    collapsible: Iterable[str],
    blockers: Mapping[str, frozenset[frozenset[str]]],
    rules: Sequence[StateRule],
    card_options: Mapping[str, Mapping[str, tuple[str, ...]]],
    dom_prefix: str,
) -> _CompiledState:
    """Compile validated graph values into the renderer's state contract."""
    node_values = tuple(nodes)
    wire_values = tuple(wires)
    topology_wire_values = tuple(topology_wires)
    collapsible_set = frozenset(collapsible)
    card_dom_ids = tuple(f"{dom_prefix}-card-{index}" for index, _ in enumerate(node_values))
    wire_dom_ids = tuple(f"{dom_prefix}-edge-{index}" for index, _ in enumerate(wire_values))
    card_id_by_index = {
        card_id: card_dom_ids[index] for index, (card_id, _) in enumerate(node_values)
    }
    wire_id_by_index = {wire.id: wire_dom_ids[index] for index, wire in enumerate(wire_values)}
    nub_dom_ids = {
        card_id: f"{dom_prefix}-nub-{index}"
        for index, (card_id, _) in enumerate(node_values)
        if card_id in collapsible_set
    }
    control_dom_ids = {
        card_id: {
            key: f"{dom_prefix}-ctl-{index}-{key_index}"
            for key_index, key in enumerate(card_options[card_id])
        }
        for index, (card_id, _) in enumerate(node_values)
        if card_options[card_id]
    }
    frozen_control_ids = MappingProxyType(
        {card_id: MappingProxyType(ids) for card_id, ids in control_dom_ids.items()}
    )
    frozen_nub_ids = MappingProxyType(nub_dom_ids)
    compiled_rules = _emit_rules(
        nodes=node_values,
        wires=topology_wire_values,
        collapsible=collapsible_set,
        blockers=blockers,
        injected=tuple(rules),
        card_dom_ids=card_id_by_index,
        wire_dom_ids=wire_id_by_index,
        nub_dom_ids=frozen_nub_ids,
        control_dom_ids=frozen_control_ids,
    )
    return _CompiledState(
        card_dom_ids=card_dom_ids,
        wire_dom_ids=wire_dom_ids,
        nub_dom_ids=frozen_nub_ids,
        control_dom_ids=frozen_control_ids,
        rules=compiled_rules,
    )
