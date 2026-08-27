import pytest

from coeftable.cards import Card
from coeftable.errors import SpecError
from coeftable.graph import Graph, Slot, Slotted, Wire
from coeftable.graph.breakout import (
    Breakout,
    breakout_control,
    partition_rules,
    reject_nested_switchers,
)


def _two_way() -> tuple[Breakout, ...]:
    return (
        Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
        Breakout(key="region", label="by region", op="+", children=("us", "eu")),
    )


def test_control_offers_one_option_per_breakout_with_the_operator_in_the_label():
    control = breakout_control(_two_way(), key="rev_breakout")
    assert control.selected == "drivers"
    assert control.options == (
        ("drivers", "by drivers (\u00d7 decomposition)"),
        ("region", "by region (+ slice)"),
    )
    assert control.key == "rev_breakout"


def test_each_rule_hides_exactly_the_other_alternatives():
    rules = partition_rules("revenue", "rev_breakout", _two_way(), ())
    drivers, region = rules
    assert set(drivers.hide_cards) == {"us", "eu"}
    assert set(region.hide_cards) == {"users", "aov"}


def test_the_emitted_shape_satisfies_the_kernel_proof():
    # The real gate: build a Graph with shared slots and let its shared-slot
    # proof accept the generated control and rules.
    breakouts = _two_way()
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("revenue", Card("Revenue", content=(control,), width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
    )
    slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
    )
    wires = (
        Wire("w0", "revenue", "users"),
        Wire("w1", "revenue", "aov"),
        Wire("w2", "revenue", "us"),
        Wire("w3", "revenue", "eu"),
    )
    graph = Graph(
        nodes,
        Slotted(slots),
        wires=wires,
        rules=partition_rules("revenue", "rev_breakout", breakouts, ()),
    )
    assert graph.measure().width > 0


def test_switching_away_from_an_alternative_hides_its_deeper_descendants():
    # `users` (a `drivers` child) has its own two-child decomposition one
    # layer deeper. Selecting `region` must hide `users`' grandchildren too,
    # not just `users` itself -- checked from the compiled/rendered output.
    breakouts = _two_way()
    edges = (
        ("revenue", "users"),
        ("revenue", "aov"),
        ("revenue", "us"),
        ("revenue", "eu"),
        ("users", "new"),
        ("users", "returning"),
    )
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("revenue", Card("Revenue", content=(control,), width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
        ("new", Card("New", width=140)),
        ("returning", Card("Returning", width=140)),
    )
    slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
        Slot("new", 2, 0),
        Slot("returning", 2, 1),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    rules = partition_rules("revenue", "rev_breakout", breakouts, edges)
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk3")

    card_dom_ids = dict(
        zip((node_id for node_id, _ in nodes), graph._compiled.card_dom_ids, strict=True)
    )
    region_conditions, region_targets = next(
        (conditions, targets)
        for conditions, targets in graph._compiled.rules
        if any('value="region"' in condition for condition in conditions)
    )
    orphaned = {
        card_dom_ids["users"],
        card_dom_ids["aov"],
        card_dom_ids["new"],
        card_dom_ids["returning"],
    }
    assert orphaned <= set(region_targets)

    output = graph.as_raw_html()
    style = output[output.rindex("<style>") :]
    prefix = ".brk3-canvas" + "".join(f":has({condition})" for condition in region_conditions)
    expected = ",".join(f"{prefix} #{target}" for target in region_targets)
    assert f"{expected}{{display:none}}" in style
    assert graph.measure().width > 0  # the shared-position proof still accepts this graph


def test_a_descendant_shared_between_alternatives_stays_visible_under_both():
    # `total` is reachable from both `users` (drivers) and `us` (region): a
    # diamond. Switching to either alternative must not hide it, even though
    # each alternative's own exclusive descendant (`new`) still hides as
    # expected.
    breakouts = _two_way()
    edges = (
        ("revenue", "users"),
        ("revenue", "aov"),
        ("revenue", "us"),
        ("revenue", "eu"),
        ("users", "new"),
        ("users", "total"),
        ("us", "total"),
    )
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("revenue", Card("Revenue", content=(control,), width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
        ("new", Card("New", width=140)),
        ("total", Card("Total", width=140)),
    )
    slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
        Slot("new", 2, 0),
        Slot("total", 2, 1),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    rules = partition_rules("revenue", "rev_breakout", breakouts, edges)
    drivers, region = rules

    # The diamond descendant never appears in either option's hide list.
    assert "total" not in drivers.hide_cards
    assert "total" not in region.hide_cards
    # Each alternative's exclusive descendants still hide as before.
    assert set(drivers.hide_cards) == {"us", "eu"}
    assert set(region.hide_cards) == {"users", "aov", "new"}

    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk4")
    assert graph.measure().width > 0  # the shared-position proof still accepts this graph


def test_hiding_a_card_hides_its_wires_without_being_asked():
    # Per-wire DOM identity means a converging edge is never collaterally
    # hidden - the defect the hand-rolled explorations had.
    breakouts = _two_way()
    rules = partition_rules("revenue", "rev_breakout", breakouts, ())
    assert all(rule.hide_wires == () for rule in rules)

    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("revenue", Card("Revenue", content=(control,), width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
    )
    slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
    )
    wires = (
        Wire("w0", "revenue", "users"),
        Wire("w1", "revenue", "aov"),
        Wire("w2", "revenue", "us"),
        Wire("w3", "revenue", "eu"),
    )
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk")

    # The compiled CSS must actually exist for every rule.
    output = graph.as_raw_html()
    style = output[output.rindex("<style>") :]
    for conditions, targets in graph._compiled.rules:
        prefix = ".brk-canvas" + "".join(f":has({condition})" for condition in conditions)
        expected = ",".join(f"{prefix} #{target}" for target in targets)
        assert f"{expected}{{display:none}}" in style

    # Selecting "drivers" hides the region alternative's cards (us, eu) and,
    # without being told to, the wires that terminate on them (w2, w3) - not
    # the wires feeding the alternative that stays visible.
    drivers_targets = next(
        targets
        for conditions, targets in graph._compiled.rules
        if any('value="drivers"' in condition for condition in conditions)
    )
    hidden_wire_doms = {
        graph._compiled.wire_dom_ids[index]
        for index, wire in enumerate(wires)
        if wire.dst in ("us", "eu")
    }
    visible_wire_doms = {
        graph._compiled.wire_dom_ids[index]
        for index, wire in enumerate(wires)
        if wire.dst in ("users", "aov")
    }
    assert hidden_wire_doms <= set(drivers_targets)
    assert visible_wire_doms.isdisjoint(drivers_targets)


def test_shared_position_layout_is_materially_more_compact_than_distinct_positions():
    # The whole point of a shared-position breakout: alternatives occupy the
    # same boxes instead of each claiming their own column.
    breakouts = _two_way()
    control = breakout_control(breakouts, key="rev_breakout")
    wires = (
        Wire("w0", "revenue", "users"),
        Wire("w1", "revenue", "aov"),
        Wire("w2", "revenue", "us"),
        Wire("w3", "revenue", "eu"),
    )

    shared_nodes = (
        ("revenue", Card("Revenue", content=(control,), width=150)),
        ("users", Card("Users", width=150)),
        ("aov", Card("AOV", width=150)),
        ("us", Card("US", width=150)),
        ("eu", Card("EU", width=150)),
    )
    shared_slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
    )
    shared = Graph(
        shared_nodes,
        Slotted(shared_slots),
        wires=wires,
        rules=partition_rules("revenue", "rev_breakout", breakouts, ()),
    )

    distinct_nodes = (
        ("revenue", Card("Revenue", width=150)),
        ("users", Card("Users", width=150)),
        ("aov", Card("AOV", width=150)),
        ("us", Card("US", width=150)),
        ("eu", Card("EU", width=150)),
    )
    distinct_slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 2),
        Slot("eu", 1, 3),
    )
    distinct = Graph(distinct_nodes, Slotted(distinct_slots), wires=wires)

    shared_width = shared.measure().width
    distinct_width = distinct.measure().width
    assert shared_width == 368
    assert distinct_width == 740
    assert shared_width < distinct_width * 0.6


def test_nested_switchers_are_rejected_with_a_rule_not_an_internal_message():
    edges = (("revenue", "users"), ("users", "new"), ("users", "ios"))
    with pytest.raises(SpecError, match="at most one breakout switcher"):
        reject_nested_switchers(("revenue", "users"), edges)


def test_switchers_in_disjoint_branches_are_allowed():
    edges = (("root", "users"), ("root", "aov"), ("users", "new"), ("aov", "price"))
    reject_nested_switchers(("users", "aov"), edges)  # must not raise


def test_a_single_breakout_needs_no_switcher():
    with pytest.raises(SpecError, match="at least two"):
        breakout_control(
            (Breakout(key="only", label="only", op="+", children=("a",)),),
            key="k",
        )


def test_alternatives_must_be_disjoint():
    # A node in two alternatives cannot be both hidden and shown by one choice.
    overlapping = (
        Breakout(key="a", label="A", op="+", children=("shared",)),
        Breakout(key="b", label="B", op="+", children=("shared",)),
    )
    with pytest.raises(SpecError, match="disjoint"):
        partition_rules("p", "k", overlapping, ())


def test_alternatives_must_be_equally_sized():
    # Shared positions are proven per (layer, slot); unequal alternatives leave
    # a position with no occupant under one choice.
    uneven = (
        Breakout(key="a", label="A", op="+", children=("x", "y")),
        Breakout(key="b", label="B", op="+", children=("z",)),
    )
    with pytest.raises(SpecError, match="same number of children"):
        partition_rules("p", "k", uneven, ())


def test_a_descendant_stays_visible_through_an_always_visible_branch_outside_the_switcher():
    # `root` has children `rev` and `other`; `rev` switches between
    # `(users, aov)` and `(us, eu)`; both `users` and `other` point at
    # `shared`. Selecting the region alternative must not hide `shared`:
    # `other` is always visible (outside the breakout entirely) and still
    # points at it, even though the selected alternative's own closure
    # (`us`, `eu`) never reaches it -- liveness has to be judged against
    # every path that survives the option, not just the selected one.
    breakouts = _two_way()
    edges = (
        ("root", "rev"),
        ("root", "other"),
        ("rev", "users"),
        ("rev", "aov"),
        ("rev", "us"),
        ("rev", "eu"),
        ("users", "shared"),
        ("other", "shared"),
    )
    rules = partition_rules("rev", "rev_breakout", breakouts, edges)
    drivers, region = rules

    assert "shared" not in region.hide_cards
    assert set(region.hide_cards) == {"users", "aov"}
    assert set(drivers.hide_cards) == {"us", "eu"}

    # The real gate: the graph layer's shared-position proof still accepts
    # this topology, diamond and all.
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("root", Card("Root", width=140)),
        ("rev", Card("Rev", content=(control,), width=140)),
        ("other", Card("Other", width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
        ("shared", Card("Shared", width=140)),
    )
    slots = (
        Slot("root", 0, 0),
        Slot("rev", 1, 0),
        Slot("other", 1, 1),
        Slot("users", 2, 0),
        Slot("us", 2, 0),
        Slot("aov", 2, 1),
        Slot("eu", 2, 1),
        Slot("shared", 3, 0),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk5")
    assert graph.measure().width > 0
