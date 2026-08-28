"""Public reference reconstruction of ``docs/prototype_productflow.py``.

The prototype's checkout funnel has 5 stages, 9 steps, 12 flows (5 of them
labeled), one decision, one terminal, one muted event, and 7 cards that
originate a forward/skip edge (so get a downstream fold nub). This module
builds that exact topology through the public ``ProductStep``/``FlowEdge``/
``ProductFlow`` contracts only -- no prototype import, no graph internals in
the construction path -- and pins the resulting census and semantics.
"""

from __future__ import annotations

from coeftable.cards import Badge, CardAppearance, Diagnostics, Metric, RuleStrip, TextBlock, Trend
from coeftable.format import Number, Percent
from coeftable.graph import FlowEdge, GraphReport, ProductFlow, ProductStep, Staged
from coeftable.graph.model import _NUB_RESERVE, _rects_intersect
from coeftable.theme import DEFAULT

_VALUE_FMT = Number(compact=True)
_CHANGE_FMT = Percent(signed=True, decimals=1)

# --- The literal prototype topology ----------------------------------------


def _reference_stages() -> tuple[str, ...]:
    return ("Browse", "Cart", "Checkout", "Payment", "Confirmed")


def _reference_series() -> dict[str, tuple[float, ...]]:
    """Each event/terminal step's actual weekly volume, first to last."""
    return {
        "searched": (78.0, 78.9, 79.4, 80.2, 80.0, 81.1, 81.9, 82.4, 82.2, 83.0, 83.6, 84.1),
        "viewed": (
            290.0,
            296.0,
            288.0,
            301.0,
            297.0,
            305.0,
            299.0,
            308.0,
            303.0,
            306.0,
            311.0,
            310.0,
        ),
        "added": (58.0, 58.8, 58.2, 59.5, 59.1, 60.2, 59.8, 60.9, 60.4, 61.2, 61.8, 62.0),
        "saved": (11.0, 11.2, 11.5, 11.3, 11.8, 12.0, 11.9, 12.3, 12.4, 12.6, 12.8, 13.0),
        "started": (38.0, 38.6, 38.2, 39.1, 38.8, 39.6, 39.3, 40.1, 39.8, 40.4, 40.9, 41.2),
        "paysub": (34.0, 34.5, 34.2, 35.0, 34.8, 35.5, 35.2, 35.9, 35.7, 36.3, 36.8, 37.0),
        "payfail": (4.2, 4.1, 4.15, 4.0, 4.05, 3.95, 3.9, 3.85, 3.8, 3.7, 3.65, 3.6),
        "confirmed": (30.0, 30.6, 30.2, 31.1, 30.9, 31.6, 31.3, 32.1, 31.9, 32.6, 33.1, 33.5),
    }


_DECISION_NOTE = "Branches on shipping options; no event of its own."


def _reference_steps() -> tuple[ProductStep, ...]:
    series = _reference_series()
    return (
        ProductStep(
            "searched",
            "Searched catalog",
            0,
            0,
            subtitle="search_submitted",
            series=series["searched"],
            share_of="viewed",
        ),
        ProductStep(
            "viewed",
            "Viewed product",
            0,
            1,
            subtitle="every visitor (high volume)",
            series=series["viewed"],
            muted=True,
        ),
        ProductStep(
            "added",
            "Added to cart",
            1,
            1,
            subtitle="add_to_cart",
            series=series["added"],
            share_of="viewed",
        ),
        ProductStep(
            "saved",
            "Saved for later",
            1,
            0,
            subtitle="wishlist_add",
            series=series["saved"],
            share_of="viewed",
        ),
        ProductStep(
            "started",
            "Checkout started",
            2,
            1,
            subtitle="checkout_started",
            series=series["started"],
            share_of="viewed",
        ),
        ProductStep(
            "shipping",
            "/shipping",
            2,
            2,
            subtitle="routing decision (no event)",
            kind="decision",
            note=_DECISION_NOTE,
        ),
        ProductStep(
            "paysub",
            "Payment submitted",
            3,
            1,
            subtitle="payment_submitted",
            series=series["paysub"],
            share_of="viewed",
        ),
        ProductStep(
            "payfail",
            "Payment failed",
            3,
            2,
            subtitle="payment_failed",
            series=series["payfail"],
            direction="lower_is_better",
            share_of="viewed",
        ),
        ProductStep(
            "confirmed",
            "Order confirmed",
            4,
            1,
            subtitle="purchase complete",
            kind="terminal",
            series=series["confirmed"],
            share_of="viewed",
        ),
    )


def _reference_edges() -> tuple[FlowEdge, ...]:
    return (
        FlowEdge("searched-viewed", "searched", "viewed", "forward"),
        FlowEdge("viewed-added", "viewed", "added", "forward"),
        FlowEdge("viewed-saved", "viewed", "saved", "skip", "save for later"),
        FlowEdge("saved-added", "saved", "added", "skip", "returns later"),
        FlowEdge("added-started", "added", "started", "forward"),
        FlowEdge("viewed-started", "viewed", "started", "skip", "buy now"),
        FlowEdge("started-shipping", "started", "shipping", "forward"),
        FlowEdge("shipping-paysub", "shipping", "paysub", "forward"),
        FlowEdge("paysub-payfail", "paysub", "payfail", "forward"),
        FlowEdge("payfail-paysub", "payfail", "paysub", "back", "retry"),
        FlowEdge("started-added", "started", "added", "back", "edit cart"),
        FlowEdge("paysub-confirmed", "paysub", "confirmed", "forward"),
    )


_REFERENCE_NOTE = (
    "Stage columns, weekly event volumes, and three edge kinds. Fold a "
    "card's nub to hide everything downstream; open its stats chip for the "
    "diagnostics popover. Zero JavaScript."
)


def _product_flow_reference() -> GraphReport:
    """Build the exact checkout funnel through public ProductFlow contracts."""
    return ProductFlow(
        _reference_stages(),
        _reference_steps(),
        _reference_edges(),
        title="Checkout flow",
        note=_REFERENCE_NOTE,
    )


def _card(report: GraphReport, step_id: str):
    return dict(report.graph.nodes)[step_id]


# --- Exact literal census ----------------------------------------------------


def test_reference_stage_labels_match_the_prototype_exactly():
    report = _product_flow_reference()
    assert isinstance(report.graph.layout, Staged)
    assert report.graph.layout.labels == _reference_stages()


def test_reference_has_nine_cards_twelve_wires_and_five_labeled_wires():
    report = _product_flow_reference()
    assert len(report.graph.nodes) == 9
    assert len(report.graph.wires) == 12
    assert sum(wire.label is not None for wire in report.graph.wires) == 5


def test_reference_has_seven_collapsible_fold_nubs_in_declared_order():
    report = _product_flow_reference()
    assert report.graph.collapsible == (
        "searched",
        "viewed",
        "added",
        "saved",
        "started",
        "shipping",
        "paysub",
    )


def test_reference_legend_has_exactly_three_entries():
    report = _product_flow_reference()
    legend = next(item for item in report.header if isinstance(item, RuleStrip))
    assert len(legend.entries) == 3
    assert tuple(label for label, _color, _dash in legend.entries) == (
        "forward",
        "skip",
        "loop / back",
    )
    assert tuple(dash for _label, _color, dash in legend.entries) == (
        "solid",
        "dashed",
        "dashed",
    )


def test_reference_has_exactly_one_decision_one_terminal_and_one_muted_step():
    report = _product_flow_reference()
    appearances = [card.appearance for _step_id, card in report.graph.nodes]
    assert sum(a.border == "dashed" and a.fill == "transparent" for a in appearances) == 1
    assert sum(a.border == "strong" for a in appearances) == 1
    assert sum(a.emphasis == "muted" for a in appearances) == 1
    assert _card(report, "shipping").appearance == CardAppearance(
        border="dashed",
        fill="transparent",
    )
    assert _card(report, "confirmed").appearance == CardAppearance(border="strong")
    assert _card(report, "viewed").appearance == CardAppearance(emphasis="muted")


def test_reference_html_has_no_script_tag_and_renders_deterministically():
    report = _product_flow_reference()
    html = report.as_raw_html()
    assert "<script" not in html
    assert html == report.as_raw_html()


# --- Painted markers Task 1 actually selected (border-style / border-color) -


def test_reference_html_paints_exactly_one_dashed_and_one_strong_border():
    """The one decision step is the only dashed border; the one terminal
    step is the only strong (theme-axis) border. These are the exact
    appearance markers Task 1 selected, not invented class names."""
    html = _product_flow_reference().as_raw_html()
    assert html.count("border-style:dashed") == 1
    assert html.count(f"border-color:{DEFAULT.axis}") == 1


# --- Decision / terminal / muted content semantics --------------------------


def test_decision_card_holds_only_its_nonempty_note():
    report = _product_flow_reference()
    card = _card(report, "shipping")
    assert card.content == (TextBlock(_DECISION_NOTE, variant="caption"),)


def test_terminal_card_appends_a_terminal_badge_after_its_series_content():
    report = _product_flow_reference()
    card = _card(report, "confirmed")
    metric, badge, trend, diagnostics, terminal_badge = card.content
    assert isinstance(metric, Metric)
    assert isinstance(badge, Badge)
    assert isinstance(trend, Trend)
    assert isinstance(diagnostics, Diagnostics)
    assert terminal_badge == Badge("terminal")


def test_payment_failed_uses_lower_is_better_and_reads_favorable_while_declining():
    report = _product_flow_reference()
    metric, badge, _trend, _diagnostics = _card(report, "payfail").content[:4]
    series = _reference_series()["payfail"]
    expected_change = (series[-1] / series[0] - 1.0) * 100.0
    assert expected_change < 0  # payment failures actually declined
    assert metric.role == "favorable"
    assert badge.role == "favorable"
    assert badge.text == _CHANGE_FMT(expected_change)


# --- Diagnostics: labels, folded chip text, and share_of ---------------------


def test_every_event_and_terminal_card_folds_behind_a_stats_chip():
    report = _product_flow_reference()
    for step_id in (
        "searched",
        "viewed",
        "added",
        "saved",
        "started",
        "paysub",
        "payfail",
        "confirmed",
    ):
        diagnostics = _card(report, step_id).content[3]
        assert isinstance(diagnostics, Diagnostics)
        assert diagnostics.label == "stats"


def test_every_non_viewed_step_reports_its_share_of_viewed():
    """The prototype computes 'Share of viewed' for every metric card; the
    public reference expresses that as `share_of="viewed"` on every
    event/terminal step except viewed itself (self-reference is refused)."""
    report = _product_flow_reference()
    series = _reference_series()
    viewed_now = series["viewed"][-1]
    for step_id in ("searched", "added", "saved", "started", "paysub", "payfail", "confirmed"):
        diagnostics = _card(report, step_id).content[3]
        now, start, change, share = diagnostics.items
        assert now == ("Now", _VALUE_FMT(series[step_id][-1]))
        assert start == ("Start", _VALUE_FMT(series[step_id][0]))
        change_pct = (series[step_id][-1] / series[step_id][0] - 1.0) * 100.0
        assert change == ("Change", _CHANGE_FMT(change_pct))
        share_pct = series[step_id][-1] / viewed_now * 100.0
        assert share == ("Share of Viewed product", _CHANGE_FMT(share_pct))

    # viewed itself carries no share_of (would self-reference) and so has
    # exactly the three derived entries, no fourth "share" row.
    viewed_diagnostics = _card(report, "viewed").content[3]
    assert len(viewed_diagnostics.items) == 3


# --- Header: title, legend, note ---------------------------------------------


def test_reference_header_carries_title_legend_then_note():
    report = _product_flow_reference()
    assert len(report.header) == 3
    assert report.header[0] == TextBlock("Checkout flow", variant="title")
    assert isinstance(report.header[1], RuleStrip)
    assert report.header[2] == TextBlock(_REFERENCE_NOTE, variant="caption")


# --- State target families: what a fold nub actually hides ------------------


def test_shipping_nub_hides_exactly_its_downstream_cards_and_wires():
    """`shipping` (kind=decision) is collapsible because it originates the
    forward edge to `paysub`. Folding it must hide paysub/payfail/confirmed,
    every wire strictly downstream of paysub (including the paint-only
    payfail-paysub back edge and its pill), and the wire shipping->paysub
    itself -- and nothing outside that family (started/added/saved/etc. stay
    visible)."""
    report = _product_flow_reference()
    graph = report.graph
    card_dom_ids = dict(
        zip((step_id for step_id, _card in graph.nodes), graph._compiled.card_dom_ids, strict=True)
    )
    wire_dom_ids = dict(
        zip((wire.id for wire in graph.wires), graph._compiled.wire_dom_ids, strict=True)
    )
    nub_id = graph._compiled.nub_dom_ids["shipping"]
    targets = next(
        targets
        for conditions, targets in graph._compiled.rules
        if conditions == (f"#{nub_id}:checked",)
    )
    expected_cards = {card_dom_ids[step_id] for step_id in ("paysub", "payfail", "confirmed")}
    expected_wires = {
        wire_dom_ids[edge_id]
        for edge_id in ("shipping-paysub", "paysub-payfail", "payfail-paysub", "paysub-confirmed")
    }
    expected_pill = f"{wire_dom_ids['payfail-paysub']}-pill"
    assert set(targets) == expected_cards | expected_wires | {expected_pill}


def test_searched_nub_hides_the_entire_rest_of_the_funnel():
    """`searched` is the funnel's sole entry point -- every other card is
    only reachable through it -- so its nub's target family is every other
    card, every wire, and every pill in the graph."""
    report = _product_flow_reference()
    graph = report.graph
    card_dom_ids = dict(
        zip((step_id for step_id, _card in graph.nodes), graph._compiled.card_dom_ids, strict=True)
    )
    wire_dom_ids = dict(
        zip((wire.id for wire in graph.wires), graph._compiled.wire_dom_ids, strict=True)
    )
    nub_id = graph._compiled.nub_dom_ids["searched"]
    targets = next(
        targets
        for conditions, targets in graph._compiled.rules
        if conditions == (f"#{nub_id}:checked",)
    )
    other_cards = {dom_id for step_id, dom_id in card_dom_ids.items() if step_id != "searched"}
    all_wires = set(wire_dom_ids.values())
    labeled_wire_ids = {wire.id for wire in graph.wires if wire.label is not None}
    all_pills = {f"{wire_dom_ids[wire_id]}-pill" for wire_id in labeled_wire_ids}
    assert set(targets) == other_cards | all_wires | all_pills
    assert len(all_pills) == 5


# --- Every measured card, pill, and nub stays inside the canvas -------------


def test_every_measured_card_pill_and_nub_fits_inside_the_canvas_with_no_card_overlap():
    report = _product_flow_reference()
    graph = report.graph
    measured = graph.measure()
    boxes = dict(measured.boxes)
    assert len(boxes) == 9

    for card_id, (x, y, width, height) in boxes.items():
        assert x >= 0, card_id
        assert y >= 0, card_id
        assert x + width <= measured.width, card_id
        assert y + height <= measured.height, card_id

    for wire_id, (px, py, pw, ph) in graph._layout.flow_pills:
        assert px >= 0, wire_id
        assert py >= 0, wire_id
        assert px + pw <= measured.width, wire_id
        assert py + ph <= measured.height, wire_id
    assert len(graph._layout.flow_pills) == 5

    for card_id, (ax, ay, _side) in graph._layout.nub_anchors:
        assert 0 <= ax, card_id
        assert ax + _NUB_RESERVE <= measured.width, card_id
        assert 0 <= ay - _NUB_RESERVE / 2, card_id
        assert ay + _NUB_RESERVE / 2 <= measured.height, card_id
    assert len(graph._layout.nub_anchors) == 7

    for wire_id, (_path, (ax, ay)) in graph._layout.wire_geometry:
        assert 0 <= ax <= measured.width, wire_id
        assert 0 <= ay <= measured.height, wire_id

    card_ids = list(boxes.keys())
    overlaps = [
        (a, b)
        for index, a in enumerate(card_ids)
        for b in card_ids[index + 1 :]
        if _rects_intersect(boxes[a], boxes[b])
    ]
    assert overlaps == []
