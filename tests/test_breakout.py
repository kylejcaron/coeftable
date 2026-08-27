import pytest

from coeftable.cards import Card
from coeftable.errors import SpecError
from coeftable.graph import Graph, Slot, Slotted, Wire
from coeftable.graph.breakout import (
    Breakout,
    breakout_control,
    partition_rules,
    reject_switcher_conjunctions,
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
        ("drivers", "by drivers \u00d7"),
        ("region", "by region +"),
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


def test_switching_the_outermost_option_away_hides_the_nested_switcher_and_its_alternatives():
    # `users` (a `drivers` child) is itself a switcher: `funnel` x vs
    # `country` +. Selecting `region` on the outer switcher must hide
    # `users` -- the nested switcher's own card -- and every one of its
    # alternatives' cards, checked from the compiled/rendered rules, not
    # just the `hide_cards` field.
    breakouts = _two_way()
    nested = (
        Breakout(key="funnel", label="by funnel", op="x", children=("sessions", "conv")),
        Breakout(key="country", label="by country", op="+", children=("cohort_a", "cohort_b")),
    )
    edges = (
        ("revenue", "users"),
        ("revenue", "aov"),
        ("revenue", "us"),
        ("revenue", "eu"),
        ("users", "sessions"),
        ("users", "conv"),
        ("users", "cohort_a"),
        ("users", "cohort_b"),
    )
    control = breakout_control(breakouts, key="rev_breakout")
    nested_control = breakout_control(nested, key="users_breakout")
    nodes = (
        ("revenue", Card("Revenue", content=(control,), width=140)),
        ("users", Card("Users", content=(nested_control,), width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
        ("sessions", Card("Sessions", width=140)),
        ("conv", Card("Conv", width=140)),
        ("cohort_a", Card("Cohort A", width=140)),
        ("cohort_b", Card("Cohort B", width=140)),
    )
    slots = (
        Slot("revenue", 0, 0),
        Slot("users", 1, 0),
        Slot("aov", 1, 1),
        Slot("us", 1, 0),
        Slot("eu", 1, 1),
        Slot("sessions", 2, 0),
        Slot("conv", 2, 1),
        Slot("cohort_a", 2, 0),
        Slot("cohort_b", 2, 1),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    rules = partition_rules("revenue", "rev_breakout", breakouts, edges) + partition_rules(
        "users", "users_breakout", nested, edges
    )
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brknest")

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
        card_dom_ids["sessions"],
        card_dom_ids["conv"],
        card_dom_ids["cohort_a"],
        card_dom_ids["cohort_b"],
    }
    assert orphaned <= set(region_targets)

    output = graph.as_raw_html()
    style = output[output.rindex("<style>") :]
    prefix = ".brknest-canvas" + "".join(f":has({condition})" for condition in region_conditions)
    expected = ",".join(f"{prefix} #{target}" for target in region_targets)
    assert f"{expected}{{display:none}}" in style
    assert graph.measure().width > 0  # the relaxed exclusivity proof still accepts this


def test_switchers_in_disjoint_branches_are_allowed():
    users_breakouts = (
        Breakout(key="new", label="New", op="+", children=("new",)),
        Breakout(key="old", label="Old", op="+", children=("old",)),
    )
    aov_breakouts = (
        Breakout(key="price", label="Price", op="+", children=("price",)),
        Breakout(key="volume", label="Volume", op="+", children=("volume",)),
    )
    edges = (
        ("root", "users"),
        ("root", "aov"),
        ("users", "new"),
        ("users", "old"),
        ("aov", "price"),
        ("aov", "volume"),
    )
    reject_switcher_conjunctions(
        {"users": users_breakouts, "aov": aov_breakouts}, edges
    )  # must not raise


def test_a_descendant_gated_by_two_independent_switchers_is_rejected():
    # `a` and `b` are non-nested switchers (neither reachable from the
    # other): `a1`/`b1` both lead to `shared`, `a2`/`b2` lead nowhere near
    # it, and `shared` has no other, unconditional path. Each switcher's
    # own liveness proof would see the *other* switcher's still-unpruned
    # `a1`/`b1` edge and (correctly, from its own narrow view) call
    # `shared` safe -- but selecting `a2` and `b2` together leaves nothing
    # pointing at it. That combination is real and selectable, so the
    # topology must be refused up front rather than silently orphaning it.
    a_breakouts = (
        Breakout(key="a1", label="A1", op="+", children=("a1",)),
        Breakout(key="a2", label="A2", op="+", children=("a2",)),
    )
    b_breakouts = (
        Breakout(key="b1", label="B1", op="+", children=("b1",)),
        Breakout(key="b2", label="B2", op="+", children=("b2",)),
    )
    edges = (
        ("root", "a"),
        ("root", "b"),
        ("a", "a1"),
        ("a", "a2"),
        ("b", "b1"),
        ("b", "b2"),
        ("a1", "shared"),
        ("b1", "shared"),
    )
    with pytest.raises(SpecError, match=r"'shared'.*more than one breakout switcher"):
        reject_switcher_conjunctions({"a": a_breakouts, "b": b_breakouts}, edges)


def test_a_descendant_shared_by_two_switchers_with_an_unconditional_path_is_allowed():
    # Same two switchers and shared descendant as above, but `other` sits
    # outside both switchers entirely and always points at `shared`. No
    # combination of options can orphan it, so this must not raise.
    a_breakouts = (
        Breakout(key="a1", label="A1", op="+", children=("a1",)),
        Breakout(key="a2", label="A2", op="+", children=("a2",)),
    )
    b_breakouts = (
        Breakout(key="b1", label="B1", op="+", children=("b1",)),
        Breakout(key="b2", label="B2", op="+", children=("b2",)),
    )
    edges = (
        ("root", "a"),
        ("root", "b"),
        ("root", "other"),
        ("a", "a1"),
        ("a", "a2"),
        ("b", "b1"),
        ("b", "b2"),
        ("a1", "shared"),
        ("b1", "shared"),
        ("other", "shared"),
    )
    reject_switcher_conjunctions({"a": a_breakouts, "b": b_breakouts}, edges)  # must not raise


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


def test_a_direct_child_of_an_unselected_alternative_is_always_hidden():
    # `us` is `region`'s own direct child -- it defines the shared position
    # opposite `users` (drivers' equivalent child). `other` sits outside the
    # switcher entirely and also points straight at `us`, same as the
    # always-visible-branch case above, except the reachable node here *is*
    # the position-defining child itself, not a deeper descendant. The
    # liveness exemption must never spare a breakout's own direct children:
    # doing so would leave the shared position with two visible occupants
    # (`users` and `us`) when `drivers` is selected, which the graph layer's
    # exclusivity proof must reject.
    breakouts = _two_way()
    edges = (
        ("root", "rev"),
        ("root", "other"),
        ("rev", "users"),
        ("rev", "aov"),
        ("rev", "us"),
        ("rev", "eu"),
        ("other", "us"),
    )
    rules = partition_rules("rev", "rev_breakout", breakouts, edges)
    drivers, region = rules

    assert "us" in drivers.hide_cards
    assert set(drivers.hide_cards) == {"us", "eu"}
    assert set(region.hide_cards) == {"users", "aov"}

    # The real gate: the graph layer's shared-position proof still accepts
    # this topology -- each shared position ends with exactly one visible
    # occupant under every option.
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("root", Card("Root", width=140)),
        ("rev", Card("Rev", content=(control,), width=140)),
        ("other", Card("Other", width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
    )
    slots = (
        Slot("root", 0, 0),
        Slot("rev", 1, 0),
        Slot("other", 1, 1),
        Slot("users", 2, 0),
        Slot("us", 2, 0),
        Slot("aov", 2, 1),
        Slot("eu", 2, 1),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk6")
    assert graph.measure().width > 0


def test_a_descendant_reachable_only_through_a_forcibly_hidden_direct_child_is_hidden():
    # `us` is `region`'s own direct child, always hidden when `drivers` is
    # selected (see above). `other` sits outside the switcher and also
    # points at `us`, and `us` has its own further child `us_detail`. The
    # liveness walk must not treat `us_detail` as reachable just because
    # `other -> us` keeps `us` itself nominally reachable: `us` disappears
    # when `drivers` is selected regardless of `other`, so nothing beyond
    # it survives either, and `us_detail` would be orphaned in the DOM if
    # left visible.
    breakouts = _two_way()
    edges = (
        ("root", "rev"),
        ("root", "other"),
        ("rev", "users"),
        ("rev", "aov"),
        ("rev", "us"),
        ("rev", "eu"),
        ("other", "us"),
        ("us", "us_detail"),
    )
    rules = partition_rules("rev", "rev_breakout", breakouts, edges)
    drivers, region = rules

    assert "us" in drivers.hide_cards
    assert "us_detail" in drivers.hide_cards
    assert set(drivers.hide_cards) == {"us", "eu", "us_detail"}
    assert set(region.hide_cards) == {"users", "aov"}

    # The real gate: the graph layer still accepts this topology.
    control = breakout_control(breakouts, key="rev_breakout")
    nodes = (
        ("root", Card("Root", width=140)),
        ("rev", Card("Rev", content=(control,), width=140)),
        ("other", Card("Other", width=140)),
        ("users", Card("Users", width=140)),
        ("aov", Card("AOV", width=140)),
        ("us", Card("US", width=140)),
        ("eu", Card("EU", width=140)),
        ("us_detail", Card("US Detail", width=140)),
    )
    slots = (
        Slot("root", 0, 0),
        Slot("rev", 1, 0),
        Slot("other", 1, 1),
        Slot("users", 2, 0),
        Slot("us", 2, 0),
        Slot("aov", 2, 1),
        Slot("eu", 2, 1),
        Slot("us_detail", 3, 0),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk7")
    assert graph.measure().width > 0


def test_an_option_contributing_multiple_children_to_a_shared_descendant_still_gates_it():
    # `a` and `b` are independent switchers. `a`'s first option contributes
    # *two* children (`a1`, `a2`) that both reach `shared`; its second
    # option (`a3`, `a4`) reaches nowhere near it. Counting only switchers
    # where exactly one direct child reaches the descendant would miss `a`
    # entirely here, even though selecting `a`'s second option excludes
    # `shared` just as surely as a single-child option would. Combined with
    # `b` (single-child gating, as in the simpler case above), selecting
    # `a`'s second option and `b`'s second option together orphans `shared`.
    a_breakouts = (
        Breakout(key="a_first", label="A first", op="+", children=("a1", "a2")),
        Breakout(key="a_second", label="A second", op="+", children=("a3", "a4")),
    )
    b_breakouts = (
        Breakout(key="b1", label="B1", op="+", children=("b1",)),
        Breakout(key="b2", label="B2", op="+", children=("b2",)),
    )
    edges = (
        ("root", "a"),
        ("root", "b"),
        ("a", "a1"),
        ("a", "a2"),
        ("a", "a3"),
        ("a", "a4"),
        ("a1", "shared"),
        ("a2", "shared"),
        ("b", "b1"),
        ("b", "b2"),
        ("b1", "shared"),
    )
    with pytest.raises(SpecError, match=r"'shared'.*more than one breakout switcher"):
        reject_switcher_conjunctions({"a": a_breakouts, "b": b_breakouts}, edges)


def test_real_option_boundaries_reject_orphaning_across_one_child_options():
    # `a`'s real boundaries are four one-child options (`a1`..`a4`); only
    # `a1` and `a3` reach `shared`. A gate that guesses at option
    # boundaries instead of reading the real `Breakout` declarations could
    # hypothesize a contiguous two-child split -- `(a1, a2)` and `(a3,
    # a4)` -- where both halves contain a reaching child, and wrongly
    # conclude `a` is no threat. The real boundaries are one child each,
    # so selecting `a2` truly excludes `shared` via `a`. Combined with an
    # independent switcher `b` (single-child gating, as in the simpler
    # cases above), selecting `a2` and `b2` together orphans `shared`.
    a_breakouts = (
        Breakout(key="a1", label="A1", op="+", children=("a1",)),
        Breakout(key="a2", label="A2", op="+", children=("a2",)),
        Breakout(key="a3", label="A3", op="+", children=("a3",)),
        Breakout(key="a4", label="A4", op="+", children=("a4",)),
    )
    b_breakouts = (
        Breakout(key="b1", label="B1", op="+", children=("b1",)),
        Breakout(key="b2", label="B2", op="+", children=("b2",)),
    )
    edges = (
        ("root", "a"),
        ("root", "b"),
        ("a", "a1"),
        ("a", "a2"),
        ("a", "a3"),
        ("a", "a4"),
        ("b", "b1"),
        ("b", "b2"),
        ("a1", "shared"),
        ("a3", "shared"),
        ("b1", "shared"),
    )
    with pytest.raises(SpecError, match=r"'shared'.*more than one breakout switcher"):
        reject_switcher_conjunctions({"a": a_breakouts, "b": b_breakouts}, edges)


def test_two_switchers_whose_every_option_reaches_a_descendant_are_allowed():
    # `a` and `b` are independent switchers, each with two two-child
    # options. `a`'s first option contributes `a1` (reaches `shared`) and
    # `a2` (doesn't); its second option contributes `a3` (reaches) and
    # `a4` (doesn't) -- so *every* option of `a` keeps `shared` alive no
    # matter which is picked. Same shape for `b` via `b1`..`b4`. Treating
    # the raw union of each switcher's reaching children as one excludable
    # group -- ignoring that `a1`/`a3` sit in different options -- would
    # wrongly conclude both switchers gate `shared` and that selecting
    # `a`'s and `b`'s non-`a1`/`b1` options together orphans it. No real
    # selection can ever exclude `shared`, so this must not raise, and the
    # graph layer must accept the resulting topology.
    a_breakouts = (
        Breakout(key="a_first", label="A first", op="+", children=("a1", "a2")),
        Breakout(key="a_second", label="A second", op="+", children=("a3", "a4")),
    )
    b_breakouts = (
        Breakout(key="b_first", label="B first", op="+", children=("b1", "b2")),
        Breakout(key="b_second", label="B second", op="+", children=("b3", "b4")),
    )
    edges = (
        ("root", "a"),
        ("root", "b"),
        ("a", "a1"),
        ("a", "a2"),
        ("a", "a3"),
        ("a", "a4"),
        ("b", "b1"),
        ("b", "b2"),
        ("b", "b3"),
        ("b", "b4"),
        ("a1", "shared"),
        ("a3", "shared"),
        ("b1", "shared"),
        ("b3", "shared"),
    )
    reject_switcher_conjunctions({"a": a_breakouts, "b": b_breakouts}, edges)  # must not raise

    # The real gate: the full topology, wired up as `DriverTree` would,
    # still builds -- `partition_rules` never hid `shared` here either.
    control_a = breakout_control(a_breakouts, key="a_breakout")
    control_b = breakout_control(b_breakouts, key="b_breakout")
    rules = partition_rules("a", "a_breakout", a_breakouts, edges) + partition_rules(
        "b", "b_breakout", b_breakouts, edges
    )
    nodes = (
        ("root", Card("Root", width=140)),
        ("a", Card("A", content=(control_a,), width=140)),
        ("b", Card("B", content=(control_b,), width=140)),
        ("a1", Card("A1", width=140)),
        ("a2", Card("A2", width=140)),
        ("a3", Card("A3", width=140)),
        ("a4", Card("A4", width=140)),
        ("b1", Card("B1", width=140)),
        ("b2", Card("B2", width=140)),
        ("b3", Card("B3", width=140)),
        ("b4", Card("B4", width=140)),
        ("shared", Card("Shared", width=140)),
    )
    slots = (
        Slot("root", 0, 0),
        Slot("a", 1, 0),
        Slot("b", 1, 1),
        Slot("a1", 2, 0),
        Slot("a3", 2, 0),
        Slot("a2", 2, 1),
        Slot("a4", 2, 1),
        Slot("b1", 2, 2),
        Slot("b3", 2, 2),
        Slot("b2", 2, 3),
        Slot("b4", 2, 3),
        Slot("shared", 3, 0),
    )
    wires = tuple(Wire(f"w{i}", src, dst) for i, (src, dst) in enumerate(edges))
    graph = Graph(nodes, Slotted(slots), wires=wires, rules=rules, dom_prefix="brk8")
    assert graph.measure().width > 0


def test_a_descendant_shared_across_a_nested_boundary_is_rejected():
    # `users` is nested inside `revenue`'s `drivers` alternative and is
    # itself a switcher (`funnel` x `country`). `shared` hangs off both
    # `sessions` (inside `users`' `funnel` alternative) and `intl` (inside
    # `revenue`'s *other*, sibling `region` alternative) -- a branch the
    # nested switcher never touches. Selecting `drivers` alone leaves
    # `shared` live via `sessions`, so `revenue`'s own rule spares it;
    # selecting `country` alone leaves it live via `intl`, so `users`' own
    # rule spares it too. Neither switcher's own liveness proof sees the
    # other's simultaneous choice, but `drivers` + `country` together hide
    # both `sessions` and `intl` and leave `shared` with no visible
    # parent. Nesting does not excuse this: `revenue`'s excluding branch
    # here (`region`) is not the branch carrying the nested switcher, so
    # its rule does not already cover the nested switcher's own worst
    # case, and the topology must be refused up front.
    rev_breakouts = (
        Breakout(key="drivers", label="Drivers", op="x", children=("users", "aov")),
        Breakout(key="region", label="Region", op="+", children=("na", "intl")),
    )
    users_breakouts = (
        Breakout(key="funnel", label="Funnel", op="x", children=("sessions", "conv")),
        Breakout(key="country", label="Country", op="+", children=("us_u", "eu_u")),
    )
    edges = (
        ("revenue", "users"),
        ("revenue", "aov"),
        ("revenue", "na"),
        ("revenue", "intl"),
        ("users", "sessions"),
        ("users", "conv"),
        ("users", "us_u"),
        ("users", "eu_u"),
        ("sessions", "shared"),
        ("intl", "shared"),
    )
    with pytest.raises(SpecError, match=r"'shared'.*more than one breakout switcher"):
        reject_switcher_conjunctions({"revenue": rev_breakouts, "users": users_breakouts}, edges)
