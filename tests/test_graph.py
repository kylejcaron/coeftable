"""Contract tests for the experimental graph leaf values."""

import ast
import dataclasses
import re
from pathlib import Path
from typing import Any, cast

import pytest

import coeftable
import coeftable.graph
from coeftable.cards import Anchor, Card, CardChrome, SelectControl, TextBlock
from coeftable.cards.regions import Metric
from coeftable.errors import SpecError
from coeftable.format import Format, Number
from coeftable.graph import (
    Atom,
    ControlRef,
    Graph,
    MeasuredGraph,
    MetricTree,
    Slot,
    Slotted,
    StateRule,
    Wire,
)
from coeftable.graph.state import _CompiledState
from coeftable.graph.topology import blocker_families, check_acyclic, is_acyclic
from coeftable.theme import DEFAULT, Direction


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
            lambda: StateRule(
                (
                    Atom(ControlRef("card", "select"), "option_checked", "yes"),
                    Atom(ControlRef("card", "select"), "option_checked", "no"),
                ),
                hide_cards=("x",),
            ),
            "StateRule.when_all must not contain conflicting options for the same control",
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
        kwargs: dict[str, object] = {
            "when_all": (atom,),
            "hide_cards": ("card",),
            "hide_wires": ("wire",),
        }
        kwargs[field] = values[field]
        with pytest.raises(SpecError, match="must be a sequence of entries, not a string"):
            StateRule(**cast(Any, kwargs))


def test_slotted_rejects_string_sequence():
    with pytest.raises(
        SpecError, match=r"Slotted\.slots must be a sequence of entries, not a string"
    ):
        Slotted(cast(tuple[Slot, ...], "slot"))


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
    expected = {
        "Atom",
        "ControlRef",
        "Graph",
        "MeasuredGraph",
        "MetricTree",
        "Slot",
        "Slotted",
        "StateRule",
        "Wire",
    }
    assert len(coeftable.graph.__all__) == 9
    assert set(coeftable.graph.__all__) == expected
    for name in expected:
        assert hasattr(coeftable.graph, name)
    assert "graph" not in coeftable.__all__


def test_measured_graph_is_frozen_slotted_and_tuple_backed():
    measured = MeasuredGraph(100, 200, (("card", (1, 2, 3, 4)),))

    assert dataclasses.is_dataclass(measured)
    assert hasattr(type(measured), "__slots__")
    assert not hasattr(measured, "__dict__")
    assert isinstance(measured.boxes, tuple)
    assert measured.boxes[0] == ("card", (1, 2, 3, 4))
    with pytest.raises(dataclasses.FrozenInstanceError):
        measured.width = 101


def test_graph_measure_single_card_is_exact_and_cached():
    graph = _plain_graph()
    footprint = graph.nodes[0][1].measure()

    measured = graph.measure()
    assert measured is graph.measure()
    assert measured.width == footprint.width + 2 * graph.chrome.padding
    assert measured.height == footprint.expanded_height + 2 * graph.chrome.padding
    assert measured.boxes == (
        (
            "root",
            (
                graph.chrome.padding,
                graph.chrome.padding,
                footprint.width,
                footprint.expanded_height,
            ),
        ),
    )


def test_graph_measure_sums_different_column_widths_and_layer_heights():
    left = Card("left", width=200)
    right = Card("right", width=301)
    graph = _plain_graph(
        nodes=(("left", left), ("right", right)),
        slots=(Slot("left", 0, 0), Slot("right", 0, 1)),
        gap=13,
    )
    left_size = graph.nodes[0][1].measure()
    right_size = graph.nodes[1][1].measure()
    pad = graph.chrome.padding
    measured = graph.measure()

    assert measured.width == left_size.width + right_size.width + 13 + 2 * pad
    assert measured.boxes == (
        ("left", (pad, pad, left_size.width, left_size.expanded_height)),
        ("right", (pad + left_size.width + 13, pad, right_size.width, right_size.expanded_height)),
    )

    tall = Card("tall", content=(TextBlock("body"),))
    layered = _plain_graph(
        nodes=(("short", Card("short")), ("tall", tall)),
        slots=(Slot("short", 0, 0), Slot("tall", 1, 0)),
        layer_gap=17,
    )
    short_size = layered.nodes[0][1].measure()
    tall_size = layered.nodes[1][1].measure()
    layered_measure = layered.measure()
    assert (
        layered_measure.height
        == short_size.expanded_height + tall_size.expanded_height + 17 + 2 * pad
    )
    assert layered_measure.boxes[1] == (
        "tall",
        (pad, pad + short_size.expanded_height + 17, tall_size.width, tall_size.expanded_height),
    )


def test_graph_measure_centers_shared_slot_alternatives_by_max_width():
    graph = Graph(
        nodes=(
            ("controller", _shared_slot_controller()),
            ("left", Card("left", width=200)),
            ("right", Card("right", width=301)),
        ),
        layout=Slotted((Slot("controller", 0, 0), Slot("left", 1, 0), Slot("right", 1, 0))),
        gap=13,
        rules=_shared_slot_partition_rules(),
    )
    boxes = dict(graph.measure().boxes)
    pad = graph.chrome.padding
    assert boxes["left"][0] == pad + (301 - 200) // 2
    assert boxes["right"][0] == pad
    assert boxes["left"][1] == boxes["right"][1]
    assert graph.measure().width == 301 + 2 * pad


def test_graph_measure_boxes_cover_each_node_once():
    graph = _plain_graph(
        nodes=(("a", Card("a")), ("b", Card("b"))),
        slots=(Slot("a", 0, 0), Slot("b", 0, 1)),
    )

    assert tuple(card_id for card_id, _ in graph.measure().boxes) == ("a", "b")


def test_graph_measure_uses_rebound_theme_sensitive_heights():
    from coeftable.cards import InlineSvg
    from coeftable.theme import BLUE, DEFAULT

    class ThemeSized:
        def resolve(self, *, width, theme, chrome):
            """Resolve to a taller drawing under any non-default theme."""
            height = 30 if theme is DEFAULT else 60
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="{height}"></svg>'
            return (InlineSvg(svg, 80, height),)

    card = Card("t", content=(ThemeSized(),))
    default_graph = _plain_graph(nodes=(("root", card),))
    blue_graph = Graph(
        nodes=(("root", card),),
        layout=Slotted((Slot("root", 0, 0),)),
        theme=BLUE,
    )
    delta = blue_graph.measure().height - default_graph.measure().height
    assert delta == 30  # the rebound card re-resolved under BLUE and grew


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
                "slots": (Slot("root", 0, 0), Slot("child", 1, 0)),
                "wires": (Wire("w1", "root", "child"), Wire("w2", "root", "child")),
            },
            "Graph.wires must not contain duplicate pairs",
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
        (
            {"nodes": cast(tuple[tuple[str, Card], ...], "nodes")},
            "Graph.nodes must be a sequence of entries, not a string",
        ),
        ({"nodes": (7,)}, "Graph.nodes[0] must be an (id, Card) pair"),
        (
            {"wires": cast(tuple[Wire, ...], "wires")},
            "Graph.wires must be a sequence of entries, not a string",
        ),
        ({"wires": (7,)}, "Graph.wires[0] must be a Wire"),
        (
            {"visibility": cast(tuple[str, ...], "visibility")},
            "Graph.visibility must be a sequence of entries, not a string",
        ),
        ({"visibility": (7,)}, "Graph.visibility[0] must be a non-empty str"),
        ({"visibility": (7, 8)}, "Graph.visibility[0] must be a non-empty str"),
        (
            {"rules": cast(tuple[StateRule, ...], "rules")},
            "Graph.rules must be a sequence of entries, not a string",
        ),
        ({"rules": (7,)}, "Graph.rules[0] must be a StateRule"),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 1, 0)),
                "wires": (Wire("w", "root", "child"),),
                "visibility": ("w", "w"),
            },
            "Graph.visibility entries must be unique",
        ),
        (
            {
                "rules": (
                    StateRule(
                        (Atom(ControlRef("root"), "checked"),),
                        hide_cards=("unknown",),
                    ),
                )
            },
            "Graph.rules hide_cards must reference known cards",
        ),
        (
            {
                "nodes": (("root", Card("root")), ("child", Card("child"))),
                "slots": (Slot("root", 0, 0), Slot("child", 1, 0)),
                "wires": (Wire("w", "root", "child"),),
                "rules": (
                    StateRule(
                        (Atom(ControlRef("root"), "checked"),),
                        hide_wires=("unknown",),
                    ),
                ),
                "collapsible": ("root",),
            },
            "Graph.rules hide_wires must reference known wires",
        ),
        (
            {
                "nodes": (
                    (
                        "root",
                        Card(
                            "root",
                            content=[
                                SelectControl("Mode", (("a", "A"),), selected="a", key="mode")
                            ],
                        ),
                    ),
                ),
                "rules": (
                    StateRule(
                        (Atom(ControlRef("root", "other"), "option_checked", "a"),),
                        hide_cards=("root",),
                    ),
                ),
            },
            "Graph.rules option controls must reference known selects",
        ),
        (
            {
                "nodes": (
                    (
                        "root",
                        Card(
                            "root",
                            content=[
                                SelectControl("Mode", (("a", "A"),), selected="a", key="mode")
                            ],
                        ),
                    ),
                ),
                "rules": (
                    StateRule(
                        (Atom(ControlRef("root", "mode"), "option_checked", "other"),),
                        hide_cards=("root",),
                    ),
                ),
            },
            "Graph.rules option must reference a known select option",
        ),
    ],
)
def test_graph_validation_matrix(kwargs, message):
    with pytest.raises(SpecError, match=f"^{re.escape(message)}$"):
        _plain_graph(**kwargs)


def test_graph_rejects_self_trapping_checked_rule():
    with pytest.raises(
        SpecError,
        match=re.escape("state rule controller dependencies must not contain self-loops"),
    ):
        _plain_graph(
            collapsible=("root",),
            rules=(StateRule((Atom(ControlRef("root"), "checked"),), hide_cards=("root",)),),
        )


def test_graph_rejects_self_trapping_option_checked_rule():
    controller = Card(
        "Controller",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    with pytest.raises(
        SpecError,
        match=re.escape("state rule controller dependencies must not contain self-loops"),
    ):
        _plain_graph(
            nodes=(("controller", controller),),
            slots=(Slot("controller", 0, 0),),
            rules=(
                StateRule(
                    (Atom(ControlRef("controller", "mode"), "option_checked", "on"),),
                    hide_cards=("controller",),
                ),
            ),
        )


def test_graph_rejects_mutually_hidden_option_controllers():
    left = Card(
        "Left",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    right = Card(
        "Right",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    with pytest.raises(
        SpecError,
        match=re.escape("state rule controller dependencies must be acyclic"),
    ):
        _plain_graph(
            nodes=(("left", left), ("right", right)),
            slots=(Slot("left", 0, 0), Slot("right", 1, 0)),
            rules=(
                StateRule(
                    (Atom(ControlRef("left", "mode"), "option_checked", "on"),),
                    hide_cards=("right",),
                ),
                StateRule(
                    (Atom(ControlRef("right", "mode"), "option_checked", "on"),),
                    hide_cards=("left",),
                ),
            ),
        )


def test_graph_accepts_one_way_hidden_option_controllers():
    upstream = Card(
        "Upstream",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    downstream = Card(
        "Downstream",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    graph = _plain_graph(
        nodes=(("upstream", upstream), ("downstream", downstream), ("leaf", Card("Leaf"))),
        slots=(
            Slot("upstream", 0, 0),
            Slot("downstream", 1, 0),
            Slot("leaf", 2, 0),
        ),
        rules=(
            StateRule(
                (Atom(ControlRef("upstream", "mode"), "option_checked", "on"),),
                hide_cards=("downstream",),
            ),
            StateRule(
                (Atom(ControlRef("downstream", "mode"), "option_checked", "on"),),
                hide_cards=("leaf",),
            ),
        ),
    )
    assert graph.rules[0].hide_cards == ("downstream",)


def test_graph_rejects_injected_rule_cycle_with_derived_nub_dependency():
    controller = Card(
        "controller",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    rule = StateRule(
        (Atom(ControlRef("controller", "mode"), "option_checked", "on"),),
        hide_cards=("ancestor",),
    )
    with pytest.raises(
        SpecError,
        match=re.escape("state rule controller dependencies must be acyclic"),
    ):
        _plain_graph(
            nodes=(("ancestor", Card("Ancestor")), ("controller", controller)),
            slots=(Slot("ancestor", 0, 0), Slot("controller", 1, 0)),
            wires=(Wire("ancestry", "ancestor", "controller"),),
            collapsible=("ancestor",),
            rules=(rule,),
        )


def test_graph_accepts_injected_rule_without_collapsible_ancestry():
    controller = Card(
        "controller",
        content=(SelectControl("Mode", (("on", "On"),), selected="on", key="mode"),),
    )
    rule = StateRule(
        (Atom(ControlRef("controller", "mode"), "option_checked", "on"),),
        hide_cards=("ancestor",),
    )
    graph = _plain_graph(
        nodes=(("ancestor", Card("Ancestor")), ("controller", controller)),
        slots=(Slot("ancestor", 0, 0), Slot("controller", 1, 0)),
        wires=(Wire("ancestry", "ancestor", "controller"),),
        rules=(rule,),
    )
    assert graph.rules == (rule,)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"layout": cast(Slotted, 7)}, "Graph.layout must be a Slotted"),
        ({"theme": cast(object, 7)}, "Graph.theme must be a Theme"),
        ({"chrome": cast(object, 7)}, "Graph.chrome must be a CardChrome"),
    ],
)
def test_graph_rejects_invalid_object_types(kwargs, message):
    if "layout" in kwargs:
        with pytest.raises(SpecError, match=f"^{re.escape(message)}$"):
            Graph(
                nodes=(("root", Card("root")),),
                layout=cast(Slotted, kwargs["layout"]),
            )
    else:
        with pytest.raises(SpecError, match=f"^{re.escape(message)}$"):
            _plain_graph(**kwargs)


def test_visibility_topology_rejects_cycles():
    with pytest.raises(SpecError, match=r"^visibility topology must be acyclic$"):
        check_acyclic(("root", "child"), (("root", "child"), ("child", "root")))


def test_graph_rethemes_cards_atomically_and_rejects_chrome_mismatch():
    theme = dataclasses.replace(Card("x").theme, text="#123456")
    card = Card("root")
    graph = _plain_graph(nodes=(("root", card),), theme=theme)
    assert graph.nodes[0][1] is not card
    assert graph.nodes[0][1].theme == theme
    assert theme.text in graph.nodes[0][1].as_raw_html()
    chrome = dataclasses.replace(CardChrome(), padding=20)
    with pytest.raises(SpecError, match=re.escape("Graph.chrome must match every Card.chrome")):
        _plain_graph(nodes=(("root", card),), chrome=chrome)


def _shared_slot_controller() -> Card:
    return Card(
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


def _shared_slot_partition_rules() -> tuple[StateRule, ...]:
    return (
        StateRule(
            (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
            hide_cards=("right",),
        ),
        StateRule(
            (Atom(ControlRef("controller", "mode"), "option_checked", "right"),),
            hide_cards=("left",),
        ),
    )


def _shared_slot_graph(
    rules: tuple[StateRule, ...],
    *,
    nodes: tuple[tuple[str, Card], ...] | None = None,
    slots: tuple[Slot, ...] | None = None,
    wires: tuple[Wire, ...] = (),
    collapsible: tuple[str, ...] = (),
) -> Graph:
    return Graph(
        nodes
        or (
            ("controller", _shared_slot_controller()),
            ("left", Card("left")),
            ("right", Card("right")),
        ),
        Slotted(slots or (Slot("controller", 0, 0), Slot("left", 1, 0), Slot("right", 1, 0))),
        wires=wires,
        collapsible=collapsible,
        rules=rules,
    )


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


def test_shared_slot_scan_tolerates_empty_option_on_unrelated_select():
    unrelated = Card(
        "unrelated",
        content=(
            SelectControl(
                "Other",
                (("", "Empty"), ("other", "Other")),
                selected="",
                key="mode",
            ),
        ),
    )
    graph = _shared_slot_graph(
        _shared_slot_partition_rules(),
        nodes=(
            ("controller", _shared_slot_controller()),
            ("unrelated", unrelated),
            ("left", Card("left")),
            ("right", Card("right")),
        ),
        slots=(
            Slot("controller", 0, 0),
            Slot("unrelated", 0, 1),
            Slot("left", 1, 0),
            Slot("right", 1, 0),
        ),
    )
    assert graph.measure().width > 0


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


def test_shared_slot_controller_cannot_be_inside_the_group():
    # Shared-slot partition validation rejects hiding the controller inside
    # its own group.
    rules = (
        StateRule(
            (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
            hide_cards=("controller",),
        ),
        StateRule(
            (Atom(ControlRef("controller", "mode"), "option_checked", "right"),),
            hide_cards=("left",),
        ),
    )
    with pytest.raises(SpecError, match="shared-slot controller must be external to its group"):
        _shared_slot_graph(
            rules,
            slots=(Slot("controller", 0, 0), Slot("left", 0, 0), Slot("right", 1, 0)),
        )


def test_visibility_subset_controls_shared_slot_blocker_derivation():
    # A painted wire from a collapsible root to the controller makes the
    # controller hideable ONLY when that wire is part of the visibility
    # topology; excluding it must make the same graph constructible.
    nodes = (
        ("root", Card("root")),
        ("controller", _shared_slot_controller()),
        ("left", Card("left")),
        ("right", Card("right")),
    )
    slots = (
        Slot("root", 0, 0),
        Slot("controller", 1, 0),
        Slot("left", 2, 0),
        Slot("right", 2, 0),
    )
    wires = (Wire("w", "root", "controller"),)
    with pytest.raises(SpecError, match="shared-slot controller must never be hidden"):
        Graph(
            nodes,
            Slotted(slots),
            wires=wires,
            collapsible=("root",),
            rules=_shared_slot_partition_rules(),
        )
    accepted = Graph(
        nodes,
        Slotted(slots),
        wires=wires,
        collapsible=("root",),
        visibility=(),
        rules=_shared_slot_partition_rules(),
    )
    assert accepted.measure().width > 0


def test_shared_slot_controller_cannot_be_hidden_by_a_derived_blocker():
    with pytest.raises(SpecError, match="shared-slot controller must never be hidden"):
        _shared_slot_graph(
            _shared_slot_partition_rules(),
            nodes=(
                ("root", Card("root")),
                ("controller", _shared_slot_controller()),
                ("left", Card("left")),
                ("right", Card("right")),
            ),
            slots=(
                Slot("root", 0, 0),
                Slot("controller", 1, 0),
                Slot("left", 2, 0),
                Slot("right", 2, 0),
            ),
            wires=(Wire("block", "root", "controller"),),
            collapsible=("root",),
        )


def test_shared_slot_controller_cannot_be_hidden_by_a_rule():
    with pytest.raises(SpecError, match="shared-slot controller must never be hidden"):
        _shared_slot_graph(
            (
                *_shared_slot_partition_rules(),
                StateRule(
                    (Atom(ControlRef("root"), "checked"),),
                    hide_cards=("controller",),
                ),
            ),
            nodes=(
                ("root", Card("root")),
                ("controller", _shared_slot_controller()),
                ("left", Card("left")),
                ("right", Card("right")),
            ),
            slots=(
                Slot("root", 0, 0),
                Slot("controller", 1, 0),
                Slot("left", 2, 0),
                Slot("right", 2, 0),
            ),
            collapsible=("root",),
        )


@pytest.mark.parametrize(
    "rules",
    [
        (
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("right",),
            ),
        ),
        (
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("right",),
            ),
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("left",),
            ),
        ),
        (
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("left", "right"),
            ),
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "right"),),
                hide_cards=("left",),
            ),
        ),
    ],
)
def test_shared_slot_partition_rules_must_be_exhaustive_and_exact(rules):
    with pytest.raises(SpecError, match="shared slots require one governing external"):
        _shared_slot_graph(rules)


def test_shared_slot_rejects_stray_rule_intersecting_group():
    rules = (
        *_shared_slot_partition_rules(),
        StateRule((Atom(ControlRef("other"), "checked"),), hide_cards=("left",)),
    )
    with pytest.raises(SpecError, match="shared-slot rules must be exact governing"):
        _shared_slot_graph(
            rules,
            nodes=(
                ("controller", _shared_slot_controller()),
                ("left", Card("left")),
                ("right", Card("right")),
                ("other", Card("other")),
            ),
            slots=(
                Slot("controller", 0, 0),
                Slot("other", 0, 1),
                Slot("left", 1, 0),
                Slot("right", 1, 0),
            ),
            collapsible=("other",),
        )


def _state_diamond(*, collapsible=("a", "b"), prefix="g") -> Graph:
    nodes = tuple((card_id, Card(card_id)) for card_id in ("r", "a", "b", "c"))
    layout = Slotted(
        tuple(Slot(card_id, layer, 0) for layer, card_id in enumerate(("r", "a", "b", "c")))
    )
    wires = (
        Wire("ra", "r", "a"),
        Wire("rb", "r", "b"),
        Wire("ac", "a", "c"),
        Wire("bc", "b", "c"),
    )
    return Graph(nodes, layout, wires=wires, collapsible=collapsible, dom_prefix=prefix)


def test_graph_compiles_diamond_state_to_exact_record():
    graph = _state_diamond()
    assert graph._compiled == _CompiledState(
        card_dom_ids=("g-card-0", "g-card-1", "g-card-2", "g-card-3"),
        wire_dom_ids=("g-edge-0", "g-edge-1", "g-edge-2", "g-edge-3"),
        nub_dom_ids={"a": "g-nub-1", "b": "g-nub-2"},
        control_dom_ids={},
        rules=(
            (("#g-nub-1:checked",), ("g-edge-2",)),
            (("#g-nub-1:checked", "#g-nub-2:checked"), ("g-card-3",)),
            (("#g-nub-2:checked",), ("g-edge-3",)),
        ),
    )


def test_graph_compiles_root_and_unequal_depth_blockers():
    rooted = _state_diamond(collapsible=("r", "a", "b"))
    assert rooted._compiled.rules == (
        (
            ("#g-nub-0:checked",),
            ("g-card-1", "g-card-2", "g-card-3", "g-edge-0", "g-edge-1", "g-edge-2", "g-edge-3"),
        ),
        (("#g-nub-1:checked",), ("g-edge-2",)),
        (("#g-nub-1:checked", "#g-nub-2:checked"), ("g-card-3",)),
        (("#g-nub-2:checked",), ("g-edge-3",)),
    )
    nodes = tuple((card_id, Card(card_id)) for card_id in ("r", "a", "b", "d", "c"))
    layout = Slotted(
        tuple(Slot(card_id, layer, 0) for layer, card_id in enumerate(("r", "a", "b", "d", "c")))
    )
    graph = Graph(
        nodes,
        layout,
        wires=(
            Wire("ra", "r", "a"),
            Wire("ac", "a", "c"),
            Wire("rb", "r", "b"),
            Wire("bd", "b", "d"),
            Wire("dc", "d", "c"),
        ),
        collapsible=("a", "b", "d"),
        dom_prefix="g",
    )
    assert graph._compiled.rules == (
        (("#g-nub-1:checked",), ("g-edge-1",)),
        (("#g-nub-1:checked", "#g-nub-2:checked"), ("g-card-4",)),
        (("#g-nub-1:checked", "#g-nub-3:checked"), ("g-card-4",)),
        (("#g-nub-2:checked",), ("g-card-3", "g-edge-3", "g-edge-4")),
        (("#g-nub-3:checked",), ("g-edge-4",)),
    )


def test_graph_compiles_injected_checked_rule_and_renders_css():
    graph = Graph(
        (("controller", Card("Controller")), ("hidden", Card("Hidden"))),
        Slotted((Slot("controller", 0, 0), Slot("hidden", 0, 1))),
        collapsible=("controller",),
        rules=(
            StateRule(
                (Atom(ControlRef("controller"), "checked"),),
                hide_cards=("hidden",),
            ),
        ),
        dom_prefix="inject",
    )
    assert graph._compiled.rules == ((("#inject-nub-0:checked",), ("inject-card-1",)),)
    assert ".inject-canvas:has(#inject-nub-0:checked) #inject-card-1{display:none}" in (
        graph.as_raw_html()
    )


def test_graph_compiles_explicit_wire_hide_without_hiding_endpoints():
    graph = Graph(
        (
            ("controller", Card("Controller")),
            ("source", Card("Source")),
            ("target", Card("Target")),
        ),
        Slotted(
            (
                Slot("controller", 0, 0),
                Slot("source", 0, 1),
                Slot("target", 1, 0),
            )
        ),
        wires=(Wire("route", "source", "target"),),
        collapsible=("controller",),
        rules=(
            StateRule(
                (Atom(ControlRef("controller"), "checked"),),
                hide_wires=("route",),
            ),
        ),
        dom_prefix="wirehide",
    )
    assert graph._compiled.rules == ((("#wirehide-nub-0:checked",), ("wirehide-edge-0",)),)
    targets = graph._compiled.rules[0][1]
    assert "wirehide-edge-0" in targets
    assert "wirehide-card-1" not in targets
    assert "wirehide-card-2" not in targets


def test_graph_compiler_keeps_uncuttable_cards_visible():
    nodes = (("r", Card("r")), ("a", Card("a")), ("c", Card("c")))
    graph = Graph(
        nodes,
        Slotted((Slot("r", 0, 0), Slot("a", 1, 0), Slot("c", 2, 0))),
        wires=(Wire("rc", "r", "c"), Wire("ra", "r", "a"), Wire("ac", "a", "c")),
        collapsible=("a",),
    )
    # Every root->card path is uncuttable, so no CARD is ever hidden; the
    # only rule hides the wire leaving the collapsible a (edge index 2).
    assert graph._compiled.rules == ((("#g0-nub-1:checked",), ("g0-edge-2",)),)


def test_graph_compiler_merges_injected_closure_and_escapes_options():
    option = 'quote"\\value'
    nodes = (
        ("root hostile", Card("root")),
        (
            "controller:hostile",
            Card(
                "controller",
                content=(
                    SelectControl(
                        "Mode",
                        ((option, "Mode"),),
                        selected=option,
                        key="mode",
                    ),
                ),
            ),
        ),
        ("hidden'card", Card("hidden")),
    )
    graph = Graph(
        nodes,
        Slotted(
            (
                Slot("root hostile", 0, 0),
                Slot("controller:hostile", 0, 1),
                Slot("hidden'card", 1, 0),
            )
        ),
        wires=(Wire('wire "hostile"', "root hostile", "hidden'card"),),
        rules=(
            StateRule(
                (Atom(ControlRef("controller:hostile", "mode"), "option_checked", option),),
                hide_cards=("hidden'card",),
            ),
        ),
        dom_prefix="p",
    )
    assert graph._compiled.control_dom_ids == {"controller:hostile": {"mode": "p-ctl-1-0"}}
    assert graph._compiled.rules == (
        (
            ('#p-ctl-1-0 option[value="quote\\"\\\\value"]:checked',),
            ("p-card-2", "p-edge-0"),
        ),
    )
    assert all(
        hostile not in selector
        for conditions, _ in graph._compiled.rules
        for selector in conditions
        for hostile in ("root hostile", "controller:hostile", "hidden'card", 'wire "hostile"')
    )


def test_graph_renderer_escapes_style_terminators_in_option_values():
    option = "</style><script>"
    graph = Graph(
        (
            (
                "controller",
                Card(
                    "controller",
                    content=(
                        SelectControl(
                            "Mode",
                            ((option, "Mode"),),
                            selected=option,
                            key="mode",
                        ),
                    ),
                ),
            ),
            ("hidden", Card("hidden")),
        ),
        Slotted((Slot("controller", 0, 0), Slot("hidden", 1, 0))),
        rules=(
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", option),),
                hide_cards=("hidden",),
            ),
        ),
        dom_prefix="escape",
    )
    output = graph.as_raw_html()
    style_body = output[output.rindex("<style>") + len("<style>") : output.rindex("</style>")]
    assert "</style>" not in style_body
    assert "<script>" not in style_body
    assert r"\3C /style\3E \3C script\3E " in style_body


def test_graph_state_is_empty_and_byte_deterministic():
    first = _state_diamond(collapsible=(), prefix="x")
    second = _state_diamond(collapsible=(), prefix="x")
    assert first._compiled == second._compiled
    assert first._compiled == _CompiledState(
        card_dom_ids=("x-card-0", "x-card-1", "x-card-2", "x-card-3"),
        wire_dom_ids=("x-edge-0", "x-edge-1", "x-edge-2", "x-edge-3"),
        nub_dom_ids={},
        control_dom_ids={},
        rules=(),
    )


def _render_fixture(*, theme=None, prefix="render") -> Graph:
    """Build a compact graph for renderer contract tests."""
    theme = DEFAULT if theme is None else theme
    nodes = (
        ("source", Card("Source")),
        ("left", Card("Left")),
        ("right", Card("Right")),
        ("target", Card("Target")),
    )
    wires = (
        Wire("role", "source", "left", label="role", label_role="favorable"),
        Wire("explicit", "source", "right", label="explicit", label_color="#123456"),
        Wire("muted", "source", "target", label="muted"),
    )
    return Graph(
        nodes,
        Slotted(
            (
                Slot("source", 0, 0),
                Slot("left", 1, 0),
                Slot("right", 1, 1),
                Slot("target", 1, 2),
            )
        ),
        wires=wires,
        collapsible=("source",),
        dom_prefix=prefix,
        theme=theme,
    )


def test_graph_renderer_is_deterministic_and_places_svg_before_cards():
    graph = _render_fixture()
    first = graph.as_raw_html()
    assert first == graph.as_raw_html() == graph._repr_html_()
    assert first.index("<svg") < first.index('id="render-card-0"')
    assert first.count('<g id="render-edge-') == 3
    assert first.count('id="render-arrow"') == 1


def test_graph_renderer_uses_cached_anchor_and_vertical_route_geometry():
    graph = Graph(
        (("source", Card("Source")), ("target", Card("Target"))),
        Slotted((Slot("source", 0, 0), Slot("target", 1, 0))),
        wires=(Wire("wire", "source", "target"),),
        dom_prefix="route",
    )
    layout = graph._layout
    source_left, source_top, _source_width, source_height = dict(graph.measure().boxes)["source"]
    target_left, target_top, _target_width, _target_height = dict(graph.measure().boxes)["target"]
    source_out = dict(layout.anchors)["source"][1]
    target_in = dict(layout.anchors)["target"][0]
    x0 = source_left + source_out[0]
    y0 = source_top + source_out[1]
    x1 = target_left + target_in[0]
    y1 = target_top + target_in[1]
    src_layer_bottom = source_top + source_height
    my1 = src_layer_bottom + graph.layer_gap / 2
    my2 = target_top - graph.layer_gap / 2
    expected_path = (
        f"M {x0:g},{y0:g} L {x0:g},{src_layer_bottom:g} "
        f"C {x0:g},{my1:g} {x1:g},{my2:g} {x1:g},{y1 - 3:g}"
    )
    expected_geometry = (("wire", (expected_path, (x1, y1 - 13))),)
    assert layout.wire_geometry == expected_geometry
    expected = f'd="{expected_path}"'
    output = graph.as_raw_html()
    assert expected in output
    assert graph.as_raw_html() == output
    assert graph._layout == layout


def test_graph_measure_swings_skip_layer_wire_through_column_corridor():
    graph = Graph(
        nodes=(
            ("r", Card("Root")),
            ("a", Card("A", width=300)),
            ("b", Card("B")),
            ("c", Card("C")),
        ),
        layout=Slotted(
            (
                Slot("r", 0, 0),
                Slot("a", 1, 0),
                Slot("b", 1, 1),
                Slot("c", 2, 0),
            )
        ),
        wires=(
            Wire("r-a", "r", "a"),
            Wire("a-c", "a", "c"),
            Wire("r-c", "r", "c"),
            Wire("r-b", "r", "b"),
        ),
        gap=20,
        layer_gap=40,
    )
    boxes = dict(graph.measure().boxes)
    anchors = dict(graph._layout.anchors)
    source_left, source_top, _source_width, source_height = boxes["r"]
    target_left, target_top, _target_width, _target_height = boxes["c"]
    source_out = anchors["r"][1]
    target_in = anchors["c"][0]
    x0, y0 = source_left + source_out[0], source_top + source_out[1]
    x1, y1 = target_left + target_in[0], target_top + target_in[1]
    src_layer_bottom = source_top + source_height
    my1 = src_layer_bottom + graph.layer_gap / 2
    my2 = target_top - graph.layer_gap / 2
    source_column_right = max(boxes[card_id][0] + boxes[card_id][2] for card_id in ("r", "a", "c"))
    xg = max(2, min(graph.measure().width - 2, source_column_right + graph.gap / 2))

    path, _label_anchor = dict(graph._layout.wire_geometry)["r-c"]
    y_a = my1 + graph.layer_gap / 2
    y_b = my2 - graph.layer_gap / 2
    expected_path = (
        f"M {x0:g},{y0:g} L {x0:g},{src_layer_bottom:g} "
        f"C {x0:g},{my1:g} {xg:g},{my1:g} {xg:g},{y_a:g} "
        f"L {xg:g},{y_b:g} C {xg:g},{my2:g} {x1:g},{my2:g} {x1:g},{y1 - 3:g}"
    )
    assert path == expected_path
    assert xg != x0
    assert xg != x1


def test_graph_measure_adjacent_route_exits_source_layer_before_bending():
    graph = Graph(
        nodes=(
            ("source", Card("Source")),
            (
                "sibling",
                Card(
                    "Sibling",
                    content=(TextBlock("one"), TextBlock("two"), TextBlock("three")),
                ),
            ),
            ("target", Card("Target")),
        ),
        layout=Slotted(
            (
                Slot("source", 0, 0),
                Slot("sibling", 0, 1),
                Slot("target", 1, 2),
            )
        ),
        wires=(Wire("wire", "source", "target"),),
        gap=20,
        layer_gap=40,
    )
    boxes = dict(graph.measure().boxes)
    source_left, source_top, _source_width, source_height = boxes["source"]
    sibling_left, sibling_top, sibling_width, sibling_height = boxes["sibling"]
    target_left, target_top, _target_width, _target_height = boxes["target"]
    assert sibling_height > source_height
    anchors = dict(graph._layout.anchors)
    source_out = anchors["source"][1]
    target_in = anchors["target"][0]
    x0, y0 = source_left + source_out[0], source_top + source_out[1]
    x1, y1 = target_left + target_in[0], target_top + target_in[1]
    values = tuple(
        float(value)
        for value in re.findall(r"-?\d+(?:\.\d+)?", dict(graph._layout.wire_geometry)["wire"][0])
    )
    assert len(values) == 10
    (
        path_x0,
        path_y0,
        lead_x,
        lead_y,
        control_x0,
        control_y1,
        control_x1,
        control_y2,
        end_x,
        end_y,
    ) = values
    assert (path_x0, path_y0, lead_x, lead_y) == (
        x0,
        y0,
        x0,
        sibling_top + sibling_height,
    )
    assert (control_x0, control_y1, end_x, end_y) == (x0, control_y1, x1, y1 - 3)

    def cubic(start, control_a, control_b, end, t):
        u = 1 - t
        return (
            u**3 * start[0]
            + 3 * u**2 * t * control_a[0]
            + 3 * u * t**2 * control_b[0]
            + t**3 * end[0],
            u**3 * start[1]
            + 3 * u**2 * t * control_a[1]
            + 3 * u * t**2 * control_b[1]
            + t**3 * end[1],
        )

    def inside_sibling(point):
        x, y = point
        return (
            sibling_left <= x <= sibling_left + sibling_width
            and sibling_top <= y <= sibling_top + sibling_height
        )

    samples = [(lead_x, path_y0 + t * (lead_y - path_y0)) for t in (0.1, 0.25, 0.5, 0.75, 0.9)]
    samples.extend(
        cubic(
            (lead_x, lead_y),
            (control_x0, control_y1),
            (control_x1, control_y2),
            (end_x, end_y),
            t,
        )
        for t in (0.1, 0.25, 0.5, 0.75, 0.9)
    )
    assert not any(inside_sibling(point) for point in samples)


def test_graph_measure_skip_corridor_stays_on_canvas_in_single_column():
    graph = Graph(
        nodes=(
            ("source", Card("Source")),
            ("middle", Card("Middle")),
            ("target", Card("Target")),
        ),
        layout=Slotted(
            (
                Slot("source", 0, 0),
                Slot("middle", 1, 0),
                Slot("target", 2, 0),
            )
        ),
        wires=(Wire("wire", "source", "target"),),
    )
    path = dict(graph._layout.wire_geometry)["wire"][0]
    xs = tuple(float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)[::2])
    assert all(0 <= x <= graph.measure().width for x in xs)


def test_graph_measure_skip_layer_route_samples_stay_outside_intervening_card():
    graph = Graph(
        nodes=(
            ("source", Card("Source")),
            ("blocker", Card("Blocker", width=220)),
            ("target", Card("Target")),
        ),
        layout=Slotted(
            (
                Slot("source", 0, 0),
                Slot("blocker", 1, 1),
                Slot("target", 2, 2),
            )
        ),
        wires=(Wire("wire", "source", "target"),),
        gap=20,
        layer_gap=40,
    )
    boxes = dict(graph.measure().boxes)
    anchors = dict(graph._layout.anchors)
    source_left, source_top, _source_width, source_height = boxes["source"]
    target_left, target_top, _target_width, _target_height = boxes["target"]
    source_out = anchors["source"][1]
    target_in = anchors["target"][0]
    x0, y0 = source_left + source_out[0], source_top + source_out[1]
    x1, y1 = target_left + target_in[0], target_top + target_in[1]
    src_layer_bottom = source_top + source_height
    my1 = src_layer_bottom + graph.layer_gap / 2
    my2 = target_top - graph.layer_gap / 2
    blocker_left, blocker_top, blocker_width, blocker_height = boxes["blocker"]

    def inside_blocker(point):
        x, y = point
        return (
            blocker_left <= x <= blocker_left + blocker_width
            and blocker_top <= y <= blocker_top + blocker_height
        )

    def cubic(start, control_a, control_b, end, t):
        u = 1 - t
        return (
            u**3 * start[0]
            + 3 * u**2 * t * control_a[0]
            + 3 * u * t**2 * control_b[0]
            + t**3 * end[0],
            u**3 * start[1]
            + 3 * u**2 * t * control_a[1]
            + 3 * u * t**2 * control_b[1]
            + t**3 * end[1],
        )

    straight_samples = [
        cubic((x0, y0), (x0, my1), (x1, my2), (x1, y1 - 3), t) for t in (0.25, 0.5, 0.75)
    ]
    assert any(inside_blocker(point) for point in straight_samples)

    values = tuple(
        float(value)
        for value in re.findall(r"-?\d+(?:\.\d+)?", dict(graph._layout.wire_geometry)["wire"][0])
    )
    assert len(values) == 18
    (
        path_x0,
        path_y0,
        lead_x,
        lead_y,
        control_x0,
        control_y1,
        control_x1,
        control_y2,
        first_end_x,
        first_end_y,
        line_x,
        line_y,
        control_x2,
        control_y3,
        control_x3,
        control_y4,
        end_x,
        end_y,
    ) = values
    assert (path_x0, path_y0) == (x0, y0)
    assert (lead_x, lead_y) == (x0, src_layer_bottom)
    samples = [(path_x0, path_y0 + t * (lead_y - path_y0)) for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    samples.extend(
        cubic(
            (lead_x, lead_y),
            (control_x0, control_y1),
            (control_x1, control_y2),
            (first_end_x, first_end_y),
            t,
        )
        for t in (0.25, 0.5, 0.75)
    )
    samples.extend(
        (
            first_end_x + t * (line_x - first_end_x),
            first_end_y + t * (line_y - first_end_y),
        )
        for t in (0.0, 0.25, 0.5, 0.75, 1.0)
    )
    samples.extend(
        cubic(
            (line_x, line_y),
            (control_x2, control_y3),
            (control_x3, control_y4),
            (end_x, end_y),
            t,
        )
        for t in (0.25, 0.5, 0.75)
    )
    assert not any(inside_blocker(point) for point in samples)


def test_graph_measure_routes_to_synthetic_in_anchor(monkeypatch):
    original_measure = Card.measure

    def synthetic_measure(card):
        measured = original_measure(card)
        out_anchor = next(anchor for anchor in measured.anchors if anchor.name == "out")
        return dataclasses.replace(
            measured,
            anchors=(Anchor("in", 10, 5), out_anchor),
        )

    monkeypatch.setattr(Card, "measure", synthetic_measure)
    graph = Graph(
        (("source", Card("Source")), ("target", Card("Target"))),
        Slotted((Slot("source", 0, 0), Slot("target", 1, 0))),
        wires=(Wire("wire", "source", "target", label="edge"),),
    )
    boxes = dict(graph.measure().boxes)
    anchors = dict(graph._layout.anchors)
    source_left, source_top, _source_width, source_height = boxes["source"]
    source_out = anchors["source"][1]
    target_left, target_top, _target_width, _target_height = boxes["target"]
    x0, y0 = source_left + source_out[0], source_top + source_out[1]
    x1, y1 = target_left + 10, target_top + 5
    src_layer_bottom = source_top + source_height
    my1 = src_layer_bottom + graph.layer_gap / 2
    my2 = target_top - graph.layer_gap / 2
    path, label_anchor = dict(graph._layout.wire_geometry)["wire"]
    expected_path = (
        f"M {x0:g},{y0:g} L {x0:g},{src_layer_bottom:g} "
        f"C {x0:g},{my1:g} {x1:g},{my2:g} {x1:g},{y1 - 3:g}"
    )
    assert path == expected_path
    assert label_anchor == (x1, y1 - 13)
    assert f'd="{expected_path}"' in graph.as_raw_html()


def test_graph_renderer_does_not_remeasure_cards(monkeypatch):
    graph = _render_fixture()
    calls = 0
    original_measure = Card.measure

    def record_measure(card):
        nonlocal calls
        calls += 1
        return original_measure(card)

    monkeypatch.setattr(Card, "measure", record_measure)
    graph.as_raw_html()
    graph.as_raw_html()
    assert calls == 0


def test_graph_renderer_places_label_above_target_and_rethemes_roles():
    theme = dataclasses.replace(
        DEFAULT,
        favorable="#111111",
        muted="#222222",
        surface="#333333",
    )
    graph = _render_fixture(theme=theme, prefix="labels")
    output = graph.as_raw_html()
    assert 'fill="#111111"' in output
    assert 'fill="#123456"' in output
    assert 'fill="#222222"' in output
    target = dict(graph.measure().boxes)["target"]
    target_in = dict(graph._layout.anchors)["target"][0]
    x1 = target[0] + target_in[0]
    y1 = target[1] + target_in[1]
    assert f'x="{x1:g}" y="{y1 - 13:g}" text-anchor="middle"' in output
    rethemed = graph.with_theme(dataclasses.replace(theme, favorable="#444444"))
    assert 'fill="#444444"' in rethemed.as_raw_html()
    assert 'fill="#123456"' in rethemed.as_raw_html()


def test_graph_renderer_spreads_labeled_diamond_anchors_at_target():
    graph = Graph(
        (
            ("left", Card("Left")),
            ("middle", Card("Middle")),
            ("right", Card("Right")),
            ("target", Card("Target")),
        ),
        Slotted(
            (
                Slot("left", 0, 0),
                Slot("middle", 0, 1),
                Slot("right", 0, 2),
                Slot("target", 1, 0),
            )
        ),
        wires=(
            Wire("right-target", "right", "target", label="right"),
            Wire("middle-target", "middle", "target"),
            Wire("left-target", "left", "target", label="left"),
        ),
        dom_prefix="label-spread",
    )
    target_left, target_top, _target_width, _target_height = dict(graph.measure().boxes)["target"]
    target_in = dict(graph._layout.anchors)["target"][0]
    x1 = target_left + target_in[0]
    y1 = target_top + target_in[1]
    geometry = dict(graph._layout.wire_geometry)
    assert geometry["left-target"][1] == (x1 - 36, y1 - 13)
    assert geometry["right-target"][1] == (x1 + 36, y1 - 13)


def test_graph_renderer_serializes_compiled_rules_and_nub_glyph_swap():
    graph = _state_diamond(prefix="rules")
    output = graph.as_raw_html()
    style = output[output.rindex("<style>") :]
    for conditions, targets in graph._compiled.rules:
        prefix = ".rules-canvas" + "".join(f":has({condition})" for condition in conditions)
        expected = ",".join(f"{prefix} #{target}" for target in targets)
        assert f"{expected}{{display:none}}" in style
    assert 'type="checkbox" id="rules-nub-1" style="display:none"' in output
    assert "<span>−</span><span>+</span></label>" in output
    assert "#rules-nub-1:checked + label span:first-child{display:none}" in style
    assert "#rules-nub-1:checked + label span:last-child{display:inline}" in style


def test_graph_renderer_contains_nubs_inside_their_card_wrappers():
    graph = Graph(
        (("source", Card("Source")), ("target", Card("Target"))),
        Slotted((Slot("source", 0, 0), Slot("target", 1, 0))),
        collapsible=("source",),
        rules=(StateRule((Atom(ControlRef("source"), "checked"),), hide_cards=("target",)),),
        dom_prefix="contain",
    )
    output = graph.as_raw_html()
    source_start = output.index('<div id="contain-card-0"')
    target_start = output.index('<div id="contain-card-1"')
    nub_input = '<input type="checkbox" id="contain-nub-0" style="display:none">'
    nub_label = '<label for="contain-nub-0"'
    input_start = output.index(nub_input)
    label_start = output.index(nub_label)
    assert source_start < input_start < target_start
    assert source_start < label_start < target_start
    assert '<div style="position:relative"><details' in output
    assert "left:50%;transform:translateX(-50%);top:100%" in output


def test_graph_renderer_mints_disjoint_ids_and_never_emits_semantic_ids():
    hostile = Graph(
        (("a hostile", Card("A")), ("b:hostile", Card("B"))),
        Slotted((Slot("a hostile", 0, 0), Slot("b:hostile", 1, 0))),
        wires=(Wire('wire "hostile"', "a hostile", "b:hostile"),),
        collapsible=("a hostile",),
        dom_prefix="hostile",
    )
    one = hostile.as_raw_html()
    other = _render_fixture(prefix="other").as_raw_html()
    assert all(value not in one for value in ("a hostile", "b:hostile", 'wire "hostile"'))
    ids = set(re.findall(r'(?:id|for)="([^"]+)"', one))
    other_ids = set(re.findall(r'(?:id|for)="([^"]+)"', other))
    assert ids.isdisjoint(other_ids)


def test_graph_renderer_stress_floor_has_cards_without_graph_svg_or_style():
    graph = Graph(
        (("first", Card("First")), ("second", Card("Second"))),
        Slotted((Slot("first", 0, 0), Slot("second", 0, 1))),
        dom_prefix="floor",
    )
    output = graph.as_raw_html()
    assert "<svg" not in output
    assert ".floor-canvas:has" not in output
    assert output.count('id="floor-card-') == 2


def test_metric_tree_slots_clamp_parents_and_keep_orphans_rightward():
    centered = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("parent", "c0", "c1", "c2")),
        (("parent", "c0", 1.0), ("parent", "c1", 1.0), ("parent", "c2", 1.0)),
    )
    assert dict((slot.card_id, slot.slot) for slot in centered.layout.slots)["parent"] == 1

    nodes = tuple(
        (node_id, Card(node_id)) for node_id in ("parent", *(f"c{i}" for i in range(10)), "orphan")
    )
    graph = _metric_tree(
        nodes,
        tuple(("parent", f"c{i}", 1.0) for i in range(10)),
    )
    slots = {slot.card_id: slot.slot for slot in graph.layout.slots}
    assert 4 <= slots["parent"] <= 5
    assert slots["orphan"] > slots["parent"]


def test_metric_tree_orphans_flow_around_parent_barycenter():
    nodes = tuple(
        (node_id, Card(node_id)) for node_id in ("parent", "c0", "c1", "c2", "orphan1", "orphan2")
    )
    graph = _metric_tree(
        nodes,
        (("parent", "c0", 1.0), ("parent", "c1", 1.0), ("parent", "c2", 1.0)),
    )
    slots = {slot.card_id: slot.slot for slot in graph.layout.slots}
    assert slots["parent"] == 1
    assert slots["orphan1"] == 2
    assert slots["orphan2"] == 3


def test_metric_tree_childless_rank_is_within_layer_not_global():
    graph = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("child", "orphan", "parent")),
        (("parent", "child", 1.0),),
    )
    assert graph.layout.slots == (
        Slot("child", 1, 0),
        Slot("orphan", 0, 0),
        Slot("parent", 0, 1),
    )


def test_graph_renderer_threads_keyed_control_dom_id():
    control = SelectControl("Mode", (("left", "Left"),), selected="left", key="mode")
    graph = Graph(
        (("source", Card("Source")), ("controller", Card("Controller", content=(control,)))),
        Slotted((Slot("source", 0, 0), Slot("controller", 1, 0))),
        wires=(Wire("wire", "source", "controller"),),
        rules=(
            StateRule(
                (Atom(ControlRef("controller", "mode"), "option_checked", "left"),),
                hide_cards=("source",),
            ),
        ),
        dom_prefix="controls",
    )
    assert '<select id="controls-ctl-1-0" ' in graph.as_raw_html()


def test_graph_renderer_source_never_reaches_cached_card_template():
    source = Path(coeftable.graph.__file__).parent.joinpath("render.py").read_text()
    assert "_template" not in source


def _metric_tree(nodes, edges, *, direction="higher_is_better"):
    return MetricTree(nodes, edges, lambda value: f"{value:.1f}", direction=direction)


def test_metric_tree_assigns_longest_path_layers_and_barycenter_slots():
    nodes = tuple((node_id, Card(node_id)) for node_id in ("root", "b", "a", "orphan"))
    graph = _metric_tree(nodes, (("root", "a", 1.0), ("root", "b", -1.0)))
    assert graph.layout.slots == (
        Slot("root", 0, 0),
        Slot("b", 1, 0),
        Slot("a", 1, 1),
        Slot("orphan", 0, 1),
    )
    centered_parent = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("left", "root", "c0", "c1", "c2")),
        (("root", "c0", 1.0), ("root", "c1", 1.0), ("root", "c2", 1.0)),
    )
    assert centered_parent.layout.slots == (
        Slot("left", 0, 0),
        Slot("root", 0, 1),
        Slot("c0", 1, 0),
        Slot("c1", 1, 1),
        Slot("c2", 1, 2),
    )
    multi_root = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("second", "child", "first")),
        (("first", "child", 1.0),),
    )
    assert multi_root.layout.slots == (
        Slot("second", 0, 0),
        Slot("child", 1, 0),
        Slot("first", 0, 1),
    )
    diamond_nodes = tuple((node_id, Card(node_id)) for node_id in ("r", "b", "a", "c"))
    diamond = _metric_tree(
        diamond_nodes,
        (("r", "a", 1.0), ("r", "b", 1.0), ("a", "c", 1.0), ("b", "c", 1.0)),
    )
    assert diamond.layout.slots == (
        Slot("r", 0, 0),
        Slot("b", 1, 0),
        Slot("a", 1, 1),
        Slot("c", 2, 0),
    )

    unequal = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("r", "a", "c", "b", "d")),
        (("r", "a", 1.0), ("a", "c", 1.0), ("r", "b", 1.0), ("b", "d", 1.0), ("d", "c", 1.0)),
    )
    assert dict((slot.card_id, slot.layer) for slot in unequal.layout.slots) == {
        "r": 0,
        "a": 1,
        "b": 1,
        "d": 2,
        "c": 3,
    }


def test_metric_tree_formats_wire_labels_and_roles():
    graph = _metric_tree(
        tuple(
            (node_id, Card(node_id)) for node_id in ("r", "positive", "negative", "none", "zero")
        ),
        (
            ("r", "positive", 1.25),
            ("r", "negative", -2.5),
            ("r", "none", None),
            ("r", "zero", 0.0),
        ),
    )
    assert tuple(wire.label for wire in graph.wires) == ("+1.2", "-2.5", None, "0.0")
    assert tuple(wire.label_role for wire in graph.wires) == (
        "favorable",
        "unfavorable",
        None,
        "inconclusive",
    )
    lower = _metric_tree(
        (("r", Card("r")), ("child", Card("child"))),
        (("r", "child", 1.0),),
        direction="lower_is_better",
    )
    assert lower.wires[0].label_role == "unfavorable"


def test_metric_tree_collapsible_nodes_are_exactly_non_leaves_and_renders():
    graph = _metric_tree(
        tuple((node_id, Card(node_id)) for node_id in ("r", "a", "b")),
        (("r", "a", 1.0), ("r", "b", None)),
    )
    assert graph.collapsible == ("r",)
    html = graph.as_raw_html()
    assert all(f'id="g0-card-{index}"' in html for index in range(3))


@pytest.mark.parametrize(
    "edges",
    [
        (("r", "r", 1.0),),
        (("r", "missing", 1.0),),
        (("r", "a", 1.0), ("r", "a", 2.0)),
        (("r", "a", 1.0), ("a", "r", 2.0)),
    ],
)
def test_metric_tree_rejects_invalid_edges(edges):
    nodes = (("r", Card("r")), ("a", Card("a")))
    with pytest.raises(SpecError):
        _metric_tree(nodes, edges)


@pytest.mark.parametrize("contribution", [float("nan"), float("inf"), float("-inf"), 10**1000])
def test_metric_tree_rejects_non_finite_contributions(contribution):
    with pytest.raises(SpecError):
        _metric_tree((("r", Card("r")), ("a", Card("a"))), (("r", "a", contribution),))


def test_metric_tree_wire_ids_survive_arrowed_node_ids():
    # "a->b" -> "c" and "a" -> "b->c" would collide under concatenated ids.
    nodes = (("a", Card("a")), ("a->b", Card("ab")), ("b->c", Card("bc")), ("c", Card("c")))
    tree = _metric_tree(nodes, (("a->b", "c", None), ("a", "b->c", None)))
    assert tuple(wire.id for wire in tree.wires) == ("w0", "w1")


def test_metric_tree_dom_prefixes_keep_rendered_ids_disjoint():
    nodes = (("root", Card("Root")), ("child", Card("Child")))
    edges = (("root", "child", 1.0),)
    first = MetricTree(nodes, edges, lambda value: f"{value:.1f}", dom_prefix="first")
    second = MetricTree(nodes, edges, lambda value: f"{value:.1f}", dom_prefix="second")
    first_ids = set(re.findall(r'(?:id|for)="([^"]+)"', first.as_raw_html()))
    second_ids = set(re.findall(r'(?:id|for)="([^"]+)"', second.as_raw_html()))
    assert first_ids
    assert second_ids
    assert first_ids.isdisjoint(second_ids)


def test_metric_tree_rejects_float_convertible_impostors():
    class Sneaky:
        def __float__(self) -> float:
            return 1.0

    with pytest.raises(SpecError, match="contribution must be finite"):
        _metric_tree((("r", Card("r")), ("a", Card("a"))), (("r", "a", Sneaky()),))


def test_metric_tree_rejects_empty_nodes_bad_formatter_and_direction():
    with pytest.raises(SpecError):
        MetricTree((), (), str)
    with pytest.raises(SpecError):
        MetricTree((("r", Card("r")),), (), cast(Format, 1))
    with pytest.raises(SpecError):
        MetricTree(
            (("r", Card("r")),),
            (),
            lambda value: str(value),
            direction=cast(Direction, "sideways"),
        )


def test_metric_tree_module_contains_no_html_string_literals():
    source = Path(coeftable.graph.__file__).parent.joinpath("metric_tree.py").read_text()
    tree = ast.parse(source)
    assert all(
        "<" not in node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _driver_tree_fixture() -> Graph:
    """Build a realistic two-layer revenue driver tree through MetricTree."""
    theme = dataclasses.replace(DEFAULT, favorable="#117733", unfavorable="#AA2233")
    return MetricTree(
        (
            (
                "revenue",
                Card(
                    "Revenue",
                    content=(Metric(4_800_000, Number(prefix="$", compact=True), ref=4_500_000),),
                    subtitle="total sales",
                    width=282,
                ),
            ),
            (
                "users",
                Card(
                    "Active Users",
                    content=(Metric(89_000, Number(compact=True), ref=86_000),),
                    subtitle="new + returning",
                    width=238,
                ),
            ),
            (
                "orders",
                Card(
                    "Orders / User",
                    content=(Metric(0.398, Number(decimals=3), ref=0.410),),
                    subtitle="weekly orders per user",
                    width=252,
                ),
            ),
            (
                "aov",
                Card(
                    "AOV",
                    content=(
                        Metric(42.12, Number(prefix="$", decimals=2), ref=41.00),
                        TextBlock("items and price", variant="caption"),
                    ),
                    subtitle="average order value",
                    width=266,
                ),
            ),
            (
                "new",
                Card(
                    "New Users",
                    content=(Metric(26_000, Number(compact=True), ref=25_000),),
                    subtitle="weekly acquisition",
                    width=244,
                ),
            ),
            (
                "returning",
                Card(
                    "Returning Users",
                    content=(
                        Metric(63_000, Number(compact=True), ref=64_000),
                        TextBlock("12-week returning cohort", variant="caption"),
                    ),
                    subtitle="weekly retention",
                    width=296,
                ),
            ),
            (
                "price",
                Card(
                    "Price / Item",
                    content=(Metric(19.50, Number(prefix="$", decimals=2), ref=18.75),),
                    subtitle="average item price",
                    width=230,
                ),
            ),
        ),
        (
            ("revenue", "users", 4.5),
            ("revenue", "orders", -1.5),
            ("revenue", "aov", 2.0),
            ("users", "new", 2.2),
            ("users", "returning", -0.4),
            ("aov", "price", 1.1),
        ),
        lambda value: f"{value:.1f}",
        theme=theme,
        direction="higher_is_better",
    )


def test_metric_tree_driver_fixture_has_exact_layout_wires_labels_nubs_and_determinism():
    graph = _driver_tree_fixture()
    measured = graph.measure()
    assert graph.layout.slots == (
        Slot("revenue", 0, 1),
        Slot("users", 1, 0),
        Slot("orders", 1, 1),
        Slot("aov", 1, 2),
        Slot("new", 2, 0),
        Slot("returning", 2, 1),
        Slot("price", 2, 2),
    )
    assert tuple(card.measure().expanded_height for _, card in graph.nodes) == (
        107,
        107,
        107,
        130,
        107,
        130,
        107,
    )
    slot_by_id = {slot.card_id: slot for slot in graph.layout.slots}
    column_widths = tuple(
        max(
            card.measure().width
            for card_id, card in graph.nodes
            if slot_by_id[card_id].slot == column
        )
        for column in range(3)
    )
    layer_heights = tuple(
        max(
            card.measure().expanded_height
            for card_id, card in graph.nodes
            if slot_by_id[card_id].layer == layer
        )
        for layer in range(3)
    )
    assert column_widths == (244, 296, 266)
    assert layer_heights == (107, 130, 130)
    assert measured.width == 910
    assert measured.height == 511
    assert measured.boxes == (
        ("revenue", (303, 16, 282, 107)),
        ("users", (19, 179, 238, 107)),
        ("orders", (318, 179, 252, 107)),
        ("aov", (628, 179, 266, 130)),
        ("new", (16, 365, 244, 107)),
        ("returning", (296, 365, 296, 130)),
        ("price", (646, 365, 230, 107)),
    )

    html = graph.as_raw_html()
    assert all(f'id="g0-card-{index}"' in html for index in range(7))
    assert graph.collapsible == ("revenue", "users", "aov")
    for index in (0, 1, 3):
        assert f'id="g0-nub-{index}"' in html
    for index in (2, 4, 5, 6):
        assert f'id="g0-nub-{index}"' not in html

    labels = tuple(re.findall(r'<text [^>]*fill="([^"]+)"[^>]*>([^<]+)</text>', html))
    assert labels == (
        ("#117733", "+4.5"),
        ("#AA2233", "-1.5"),
        ("#117733", "+2.0"),
        ("#117733", "+2.2"),
        ("#AA2233", "-0.4"),
        ("#117733", "+1.1"),
    )
    path_matches = re.findall(r'<g id="g0-edge-(\d+)"><path d="([^"]+)"', html)
    assert len(path_matches) == len(graph.wires) == 6
    assert html.count('<g id="g0-edge-') == len(graph.wires)
    boxes = dict(measured.boxes)
    anchors = dict(graph._layout.anchors)
    for expected_index, (wire, (index, path_d)) in enumerate(
        zip(graph.wires, path_matches, strict=True)
    ):
        assert index == str(expected_index)
        match = re.fullmatch(
            r"M ([^,]+),([^ ]+) L ([^,]+),([^ ]+) C ([^,]+),([^ ]+) "
            r"([^,]+),([^ ]+) ([^,]+),([^ ]+)",
            path_d,
        )
        assert match is not None
        coordinates = tuple(float(value) for value in match.groups())
        src_left, src_top, _src_width, _src_height = boxes[wire.src]
        dst_left, dst_top, _dst_width, _dst_height = boxes[wire.dst]
        (_, (out_x, out_y)) = anchors[wire.src]
        (in_x, in_y), _ = anchors[wire.dst]
        x0, y0 = src_left + out_x, src_top + out_y
        x1, y1 = dst_left + in_x, dst_top + in_y
        src_layer = slot_by_id[wire.src].layer
        src_layer_bottom = src_top + layer_heights[src_layer]
        my1 = src_layer_bottom + graph.layer_gap / 2
        my2 = dst_top - graph.layer_gap / 2
        assert coordinates == pytest.approx(
            (x0, y0, x0, src_layer_bottom, x0, my1, x1, my2, x1, y1 - 3)
        )
    # Construction-level determinism: a FRESH fixture build yields identical HTML.
    assert html == _driver_tree_fixture().as_raw_html()


def test_graph_html_attributes_are_well_formed():
    """An unterminated attribute quote swallows following markup silently."""
    import html.parser

    class Auditor(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tags: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.tags.append(tag)
            for name, value in attrs:
                assert value is None or "<" not in value, f"unterminated {name} on <{tag}>"

    output = _state_diamond(prefix="wf").as_raw_html()
    auditor = Auditor()
    auditor.feed(output)
    labels = auditor.tags.count("label")
    inputs = auditor.tags.count("input")
    assert labels == inputs > 0  # every nub checkbox has its glyph label parsed as a real tag
