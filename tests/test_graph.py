"""Contract tests for the experimental graph leaf values."""

import ast
import dataclasses
import re
from pathlib import Path
from typing import cast

import pytest

import coeftable
import coeftable.graph
from coeftable.cards import Card, CardChrome, SelectControl
from coeftable.errors import SpecError
from coeftable.graph import Atom, ControlRef, Graph, Slot, Slotted, StateRule, Wire
from coeftable.graph.topology import blocker_families, is_acyclic


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: ControlRef(""), "ControlRef.card_id must be a non-empty str"),
        (lambda: ControlRef(cast(str, 7)), "ControlRef.card_id must be a non-empty str"),
        (lambda: ControlRef("card", key=""), "ControlRef.key must be a non-empty str"),
        (lambda: ControlRef("card", key=cast(str, 7)), "ControlRef.key must be a non-empty str"),
        (lambda: Atom(cast(ControlRef, 7), "checked"), "Atom.control must be a ControlRef"),
        (
            lambda: Atom(ControlRef("card"), cast(object, "unknown")),  # ty: ignore[invalid-argument-type]
            "Atom.predicate must be 'checked' or 'option_checked'",
        ),
        (
            lambda: Atom(ControlRef("card", key="select"), "checked"),
            "Atom.checked requires ControlRef.key to be None",
        ),
        (
            lambda: Atom(ControlRef("card"), "checked", option="yes"),
            "Atom.checked requires option to be None",
        ),
        (
            lambda: Atom(ControlRef("card"), "option_checked", option="yes"),
            "Atom.option_checked requires ControlRef.key",
        ),
        (
            lambda: Atom(ControlRef("card", key="select"), "option_checked"),
            "Atom.option_checked requires option",
        ),
        (
            lambda: Atom(ControlRef("card", key="select"), "option_checked", option=""),
            "Atom.option must be a non-empty str",
        ),
        (lambda: StateRule((), hide_cards=("card",)), "StateRule.when_all must not be empty"),
        (
            lambda: StateRule((cast(Atom, 7),), hide_cards=("card",)),
            "StateRule.when_all[0] must be an Atom",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),) * 2, hide_cards=("x",)),
            "StateRule.when_all must not contain duplicates",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),), hide_cards=("",)),
            "StateRule.hide_cards[0] must be a non-empty str",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),), hide_cards=(cast(str, 7),)),
            "StateRule.hide_cards[0] must be a non-empty str",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),), hide_wires=("",)),
            "StateRule.hide_wires[0] must be a non-empty str",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),), hide_cards=("x", "x")),
            "StateRule.hide_cards must not contain duplicates",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),), hide_wires=("x", "x")),
            "StateRule.hide_wires must not contain duplicates",
        ),
        (
            lambda: StateRule((Atom(ControlRef("card"), "checked"),)),
            "StateRule must hide at least one card or wire",
        ),
        (lambda: Slot("", 0, 0), "Slot.card_id must be a non-empty str"),
        (lambda: Slot("card", cast(int, 1.5), 0), "Slot.layer must be a non-negative int"),
        (lambda: Slot("card", True, 0), "Slot.layer must be a non-negative int"),
        (lambda: Slot("card", -1, 0), "Slot.layer must be a non-negative int"),
        (lambda: Slot("card", 0, cast(int, 1.5)), "Slot.slot must be a non-negative int"),
        (lambda: Slot("card", 0, True), "Slot.slot must be a non-negative int"),
        (lambda: Slot("card", 0, -1), "Slot.slot must be a non-negative int"),
        (lambda: Slotted(()), "Slotted.slots must not be empty"),
        (lambda: Slotted((cast(Slot, 7),)), "Slotted.slots[0] must be a Slot"),
        (lambda: Wire("", "a", "b"), "Wire.id must be a non-empty str"),
        (lambda: Wire("w", "", "b"), "Wire.src must be a non-empty str"),
        (lambda: Wire("w", "a", ""), "Wire.dst must be a non-empty str"),
        (lambda: Wire("w", "a", "a"), "Wire.src and Wire.dst must differ"),
        (lambda: Wire("w", "a", "b", label=""), "Wire.label must be a non-empty str"),
        (lambda: Wire("w", "a", "b", label=cast(str, 7)), "Wire.label must be a non-empty str"),
        (
            lambda: Wire("w", "a", "b", label_role=cast(object, "loud")),  # ty: ignore[invalid-argument-type]
            "Wire.label_role must be a valid Role",
        ),
        (
            lambda: Wire("w", "a", "b", label_color=""),
            "Wire.label_color must be a non-empty str",
        ),
        (
            lambda: Wire("w", "a", "b", label_color=cast(str, 7)),
            "Wire.label_color must be a non-empty str",
        ),
        (
            lambda: Wire("w", "a", "b", label_role="neutral", label_color="#fff"),
            "Wire.label_role and Wire.label_color are mutually exclusive",
        ),
        (
            lambda: Wire("w", "a", "b", label_role="neutral"),
            "Wire.label is required when label_role or label_color is set",
        ),
        (
            lambda: Wire("w", "a", "b", label_color="#fff"),
            "Wire.label is required when label_role or label_color is set",
        ),
    ],
)
def test_intrinsic_validation_matrix(build, message):
    with pytest.raises(SpecError, match=f"^{re.escape(message)}$"):
        build()


def test_sequence_inputs_are_snapshotted():
    atom = Atom(ControlRef("card"), "checked")
    when_all = [atom]
    hide_cards = ["card"]
    hide_wires = ["wire"]
    rule = StateRule(
        cast(tuple[Atom, ...], when_all),
        cast(tuple[str, ...], hide_cards),
        cast(tuple[str, ...], hide_wires),
    )
    when_all.append(Atom(ControlRef("other"), "checked"))
    hide_cards.append("other")
    hide_wires.append("other")
    assert rule.when_all == (atom,)
    assert rule.hide_cards == ("card",)
    assert rule.hide_wires == ("wire",)

    source = [Slot("card", 0, 0)]
    layout = Slotted(cast(tuple[Slot, ...], source))
    source.append(Slot("other", 0, 1))
    assert layout.slots == (Slot("card", 0, 0),)


def test_state_rule_rejects_string_sequences():
    atom = Atom(ControlRef("card"), "checked")
    for field in ("when_all", "hide_cards", "hide_wires"):
        values = {"when_all": "atom", "hide_cards": "card", "hide_wires": "wire"}
        kwargs = {"when_all": (atom,), "hide_cards": ("card",), "hide_wires": ("wire",)}
        kwargs[field] = values[field]  # ty: ignore[invalid-assignment]
        with pytest.raises(SpecError, match="must be a sequence of entries, not a string"):
            StateRule(**kwargs)


def test_slotted_rejects_string_sequence():
    with pytest.raises(
        SpecError, match=r"Slotted\.slots must be a sequence of entries, not a string"
    ):
        Slotted(cast(tuple[Slot, ...], "slot"))  # ty: ignore[invalid-argument-type]


def test_valid_leaf_values_and_optional_wire_labels():
    assert ControlRef("card") == ControlRef("card", key=None)
    assert Atom(ControlRef("card"), "checked")
    assert Atom(ControlRef("card", key="mode"), "option_checked", option="compact")
    assert StateRule((Atom(ControlRef("card"), "checked"),), hide_cards=("other",))
    assert Wire("w", "a", "b")
    assert Wire("w", "a", "b", label="estimate", label_role="favorable")
    assert Wire("w", "a", "b", label="estimate", label_color="#abc")


def test_every_leaf_is_frozen_slotted_and_without_dict():
    values = [
        ControlRef("card"),
        Atom(ControlRef("card"), "checked"),
        StateRule((Atom(ControlRef("card"), "checked"),), hide_cards=("other",)),
        Slot("card", 0, 0),
        Slotted((Slot("card", 0, 0),)),
        Wire("wire", "card", "other"),
    ]
    for value in values:
        assert dataclasses.is_dataclass(value)
        assert hasattr(type(value), "__slots__")
        assert not hasattr(value, "__dict__")
        field = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field, None)


def test_graph_export_surface_is_exact_and_top_level_excludes_graph():
    expected = {"Atom", "ControlRef", "Graph", "Slot", "Slotted", "StateRule", "Wire"}
    assert len(coeftable.graph.__all__) == 7
    assert set(coeftable.graph.__all__) == expected
    for name in expected:
        assert hasattr(coeftable.graph, name)
    assert "graph" not in coeftable.__all__


def test_every_graph_module_imports_only_foundation_or_cards_roots():
    package_dir = Path(coeftable.graph.__file__).parent
    src_root = package_dir.parent.parent
    allowed = {"graph", "cards", "theme", "format", "svg", "annotations", "errors"}
    modules = sorted(package_dir.rglob("*.py"))
    assert modules
    for module in modules:
        tree = ast.parse(module.read_text())
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "coeftable":
                        imported_roots.add(parts[1] if len(parts) > 1 else "")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    paths = [node.module.split(".")] if node.module else []
                else:
                    package = list(module.parent.relative_to(src_root).parts)
                    base = package[: len(package) - (node.level - 1)]
                    if node.module:
                        paths = [base + node.module.split(".")]
                    else:
                        paths = [[*base, alias.name] for alias in node.names]
                for parts in paths:
                    if parts[0] != "coeftable":
                        continue
                    if len(parts) > 1:
                        imported_roots.add(parts[1])
                    else:
                        imported_roots.update(alias.name for alias in node.names)
        assert not imported_roots - allowed, f"{module.name}: {imported_roots - allowed}"


def _plain_graph(
    *,
    nodes: tuple[tuple[str, Card], ...] = (("root", Card("root")),),
    slots: tuple[Slot, ...] = (Slot("root", 0, 0),),
    **kwargs: object,
) -> Graph:
    """Build a small graph for validation tests."""
    return Graph(nodes=nodes, layout=Slotted(slots), **kwargs)  # ty: ignore[invalid-argument-type]


def test_blocker_families_cover_diamonds_depth_and_uncuttable_paths():
    diamond = blocker_families(
        ("r", "a", "b", "c"),
        (("r", "a"), ("r", "b"), ("a", "c"), ("b", "c")),
        ("a", "b"),
    )
    assert diamond["c"] == frozenset({frozenset({"a", "b"})})
    rooted = blocker_families(
        ("r", "a", "b", "c"),
        (("r", "a"), ("r", "b"), ("a", "c"), ("b", "c")),
        ("r", "a", "b"),
    )
    assert rooted["c"] == frozenset({frozenset({"a", "b"}), frozenset({"r"})})
    unequal = blocker_families(
        ("r", "a", "b", "c", "d"),
        (("r", "a"), ("a", "c"), ("r", "b"), ("b", "d"), ("d", "c")),
        ("a", "b", "d"),
    )
    assert unequal["c"] == frozenset({frozenset({"a", "b"}), frozenset({"a", "d"})})
    mixed = blocker_families(
        ("r", "a", "c"),
        (("r", "c"), ("r", "a"), ("a", "c")),
        ("a",),
    )
    assert mixed["c"] == frozenset()
    assert blocker_families((), (), ()) == {}
    assert is_acyclic(("r", "a"), (("r", "a"),))
    assert not is_acyclic(("r", "a"), (("r", "a"), ("a", "r")))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"nodes": (), "slots": (Slot("root", 0, 0),)}, "Graph.nodes must not be empty"),
        ({"nodes": (("root", cast(Card, 7)),)}, "Graph.nodes[0].card must be a Card"),
        (
            {"nodes": (("root", Card("root")), ("root", Card("other")))},
            "Graph.nodes ids must be unique",
        ),
        (
            {"nodes": (("root", Card("root")),), "slots": (Slot("other", 0, 0),)},
            "Graph.layout.slots must cover graph node ids exactly once",
        ),
        (
            {"slots": (Slot("root", 1, 0),)},
            "Graph.layout layer and slot indices must be dense from zero",
        ),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 0, 2)),
            },
            "Graph.layout layer and slot indices must be dense from zero",
        ),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 1, 0)),
                "wires": (Wire("w", "unknown", "child"),),
            },
            "Graph.wires endpoints must reference known cards",
        ),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 1, 0)),
                "wires": (Wire("w", "root", "child"), Wire("w", "root", "child")),
            },
            "Graph.wires ids must be unique",
        ),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 0, 0)),
                "wires": (Wire("w", "root", "child"),),
            },
            "Graph.wires must route strictly downward",
        ),
        (
            {"collapsible": ("unknown",)},
            "Graph.collapsible references an unknown card",
        ),
        (
            {"collapsible": ("root", "root")},
            "Graph.collapsible entries must be unique",
        ),
        (
            {"visibility": ("unknown",)},
            "Graph.visibility references an unknown wire",
        ),
        (
            {"gap": True},
            "Graph.gap must be a positive int",
        ),
        (
            {"layer_gap": 0},
            "Graph.layer_gap must be a positive int",
        ),
        (
            {"dom_prefix": "0bad"},
            "Graph.dom_prefix must match [a-z][a-z0-9-]*",
        ),
        (
            {
                "rules": (
                    StateRule((Atom(ControlRef("unknown"), "checked"),), hide_cards=("root",)),
                ),
            },
            "Graph.rules controls must reference known cards",
        ),
        (
            {
                "rules": (
                    StateRule((Atom(ControlRef("root"), "checked"),), hide_cards=("root",)),
                ),
            },
            "Graph.rules checked controls must be collapsible cards",
        ),
    ],
)
def test_graph_validation_matrix(kwargs, message):
    with pytest.raises(SpecError, match=f"^{re.escape(message)}$"):
        _plain_graph(**kwargs)


def test_graph_rethemes_cards_atomically_and_rejects_chrome_mismatch():
    theme = dataclasses.replace(Card("x").theme, text="#123456")
    card = Card("root")
    graph = _plain_graph(theme=theme)
    assert graph.nodes[0][1] is not card
    assert graph.nodes[0][1].theme == theme
    assert theme.text in graph.nodes[0][1].as_raw_html()
    chrome = dataclasses.replace(CardChrome(), padding=20)
    with pytest.raises(SpecError, match=re.escape("Graph.chrome must match every Card.chrome")):
        _plain_graph(chrome=chrome)


def test_graph_accepts_proven_shared_slot_alternatives():
    controller = Card(
        "controller",
        content=[
            SelectControl(
                "Mode",
                (("left", "Left"), ("right", "Right")),
                selected="left",
                key="mode",
            )
        ],
    )
    graph = Graph(
        (
            ("controller", controller),
            ("left", Card("left")),
            ("right", Card("right")),
        ),
        Slotted((Slot("controller", 0, 0), Slot("left", 1, 0), Slot("right", 1, 0))),
        rules=(
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("right",),
            ),
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "right"),),
                hide_cards=("left",),
            ),
        ),
    )
    assert graph.nodes[0][0] == "controller"


@pytest.mark.parametrize(
    "rules",
    [
        (),
        (
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("right",),
            ),
        ),
    ],
)
def test_graph_rejects_unproven_shared_slot(rules):
    controller = Card(
        "controller",
        content=[
            SelectControl(
                "Mode",
                (("left", "Left"), ("right", "Right")),
                selected="left",
                key="mode",
            )
        ],
    )
    with pytest.raises(SpecError, match="shared slots require one governing external"):
        Graph(
            (("controller", controller), ("left", Card("left")), ("right", Card("right"))),
            Slotted((Slot("controller", 0, 0), Slot("left", 1, 0), Slot("right", 1, 0))),
            rules=rules,
        )
