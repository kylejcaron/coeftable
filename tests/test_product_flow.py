"""Contract tests for the ProductStep/ProductFlow report builder."""

import dataclasses
import re
from typing import cast

import pytest

from coeftable.cards import (
    Badge,
    Card,
    CardAppearance,
    Diagnostics,
    Metric,
    RuleStrip,
    TextBlock,
    Trend,
)
from coeftable.errors import SpecError
from coeftable.format import Number, Percent
from coeftable.graph import EdgeStyle, FlowEdge, GraphReport, ProductFlow, ProductStep, Staged
from coeftable.theme import DEFAULT

_VALUE_FMT = Number(compact=True)
_CHANGE_FMT = Percent(signed=True, decimals=1)


def step(**changes: object) -> ProductStep:
    """Build a valid baseline ProductStep, overridden by `changes`."""
    defaults: dict[str, object] = {
        "id": "a",
        "title": "A",
        "stage": 0,
        "lane": 0,
        "series": (1.0, 2.0),
    }
    defaults.update(changes)
    return ProductStep(**defaults)  # ty: ignore[invalid-argument-type]


# --- ProductStep intrinsic validation -----------------------------------


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": ""}, "ProductStep.id"),
        ({"stage": -1}, "ProductStep.stage"),
        ({"series": (1.0,)}, "at least two"),
        ({"series": (0.0, 1.0)}, "strictly positive"),
        ({"series": (1.0, -1.0)}, "nonnegative"),
        ({"kind": "decision", "series": (), "note": None}, "decision note"),
        ({"kind": "decision", "series": (), "note": 1}, "decision note"),
        ({"kind": "decision", "series": (1.0, 2.0), "note": "branch"}, "empty series"),
    ],
)
def test_product_step_validation(changes, message):
    with pytest.raises(SpecError, match=message):
        step(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"title": ""}, "ProductStep.title"),
        ({"lane": -1}, "ProductStep.lane"),
        ({"stage": True}, "ProductStep.stage"),
        ({"subtitle": 1}, "ProductStep.subtitle"),
        ({"kind": "unknown"}, "ProductStep.kind"),
        ({"direction": "sideways"}, "ProductStep.direction"),
        ({"muted": 1}, "ProductStep.muted"),
        ({"note": "not allowed on an event"}, "only valid for a decision"),
        ({"kind": "decision", "series": (), "note": "ok", "muted": True}, "must not be muted"),
        (
            {"kind": "decision", "series": (), "note": "ok", "share_of": "other"},
            "must not set share_of",
        ),
        ({"share_of": 3}, "ProductStep.share_of"),
        ({"diagnostics": (("only-one-field",),)}, "must be a \\(label, value\\) pair"),
        ({"diagnostics": ((1, "x"),)}, "ProductStep.diagnostics\\[0\\]\\[0\\]"),
        ({"diagnostics": (("", "x"),)}, "ProductStep.diagnostics\\[0\\]\\[0\\]"),
        ({"diagnostics": (("k", object()),)}, "ProductStep.diagnostics\\[0\\]\\[1\\]"),
        ({"series": "not-a-sequence"}, "ProductStep.series"),
        ({"series": (float("nan"), 1.0)}, "ProductStep.series\\[0\\]"),
    ],
)
def test_product_step_additional_validation(changes, message):
    with pytest.raises(SpecError, match=message):
        step(**changes)


def test_product_step_is_frozen_and_slotted():
    instance = step()
    assert dataclasses.is_dataclass(instance)
    assert hasattr(ProductStep, "__slots__")
    assert not hasattr(instance, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.title = "nope"


def test_product_step_snapshots_series_and_diagnostics_inputs():
    series = [1.0, 2.0, 3.0]
    diagnostics = [("k", 1.0)]
    instance = step(series=series, diagnostics=diagnostics)
    series.append(99.0)
    diagnostics.append(("mutated", 2.0))
    assert instance.series == (1.0, 2.0, 3.0)
    assert instance.diagnostics == (("k", 1.0),)
    assert isinstance(instance.series, tuple)
    assert isinstance(instance.diagnostics, tuple)


def test_product_step_accepts_a_string_diagnostic_value_unchanged():
    instance = step(diagnostics=(("Cohort", "US"),))
    assert instance.diagnostics == (("Cohort", "US"),)


def test_product_step_decision_defaults_are_valid():
    instance = step(kind="decision", series=(), note="Explain the branch")
    assert instance.series == ()
    assert instance.note == "Explain the branch"


# --- ProductFlow fixtures -------------------------------------------------


def _funnel_stages() -> tuple[str, ...]:
    return ("Viewed", "Started", "Purchased")


def _funnel_steps() -> tuple[ProductStep, ...]:
    return (
        ProductStep(
            "viewed",
            "Viewed",
            0,
            0,
            series=(1000.0, 1200.0),
            diagnostics=(("Source", "organic"),),
        ),
        ProductStep(
            "started",
            "Started checkout",
            1,
            0,
            series=(500.0, 400.0),
            direction="lower_is_better",
        ),
        ProductStep(
            "decide",
            "Choose a plan",
            1,
            1,
            kind="decision",
            series=(),
            note="Reader picks monthly or annual",
        ),
        ProductStep(
            "purchased",
            "Purchased",
            2,
            0,
            kind="terminal",
            series=(100.0, 150.0),
            share_of="viewed",
        ),
    )


def _funnel_edges() -> tuple[FlowEdge, ...]:
    return (
        FlowEdge("viewed-started", "viewed", "started", "forward"),
        FlowEdge("started-purchased", "started", "purchased", "forward"),
        FlowEdge("viewed-purchased", "viewed", "purchased", "skip"),
        FlowEdge("purchased-viewed", "purchased", "viewed", "back"),
    )


def _funnel_report(**overrides: object) -> GraphReport:
    kwargs: dict[str, object] = {
        "title": "Checkout flow",
        "note": "Zero JS",
    }
    kwargs.update(overrides)
    return ProductFlow(_funnel_stages(), _funnel_steps(), _funnel_edges(), **kwargs)  # ty: ignore[invalid-argument-type]


def _card(report: GraphReport, step_id: str) -> Card:
    return dict(report.graph.nodes)[step_id]


def _series_content(card: Card) -> tuple[Metric, Badge, Trend, Diagnostics]:
    metric, badge, trend, diagnostics = card.content[:4]
    return (
        cast(Metric, metric),
        cast(Badge, badge),
        cast(Trend, trend),
        cast(Diagnostics, diagnostics),
    )


# --- ProductFlow composition ----------------------------------------------


def test_product_flow_composes_a_deterministic_staged_graph_report():
    report = _funnel_report()
    assert isinstance(report, GraphReport)
    assert isinstance(report.graph.layout, Staged)
    assert report.graph.layout.labels == _funnel_stages()
    assert report.graph.collapsible == ("viewed", "started")
    html = report.as_raw_html()
    for text in ("Checkout flow", "forward", "skip", "back", "terminal", "Share of Viewed"):
        assert text in html
    assert "<script" not in html
    assert html == report.as_raw_html()


def test_product_flow_node_order_matches_declared_step_order():
    report = _funnel_report()
    assert tuple(node_id for node_id, _card in report.graph.nodes) == (
        "viewed",
        "started",
        "decide",
        "purchased",
    )


def test_product_flow_header_carries_title_legend_then_note():
    report = _funnel_report()
    assert len(report.header) == 3
    assert isinstance(report.header[0], TextBlock)
    assert report.header[0].text == "Checkout flow"
    assert report.header[0].variant == "title"
    assert isinstance(report.header[1], RuleStrip)
    assert isinstance(report.header[2], TextBlock)
    assert report.header[2].text == "Zero JS"
    assert report.header[2].variant == "caption"


def test_product_flow_header_omits_title_and_note_when_absent():
    report = ProductFlow(_funnel_stages(), _funnel_steps(), _funnel_edges())
    assert len(report.header) == 1
    assert isinstance(report.header[0], RuleStrip)


def test_product_flow_default_graph_and_legend_distinguish_skip_from_back():
    report = _funnel_report()
    graph_styles = dict(report.graph.edge_styles)
    assert "skip" not in graph_styles
    assert graph_styles["back"] == EdgeStyle(DEFAULT.unfavorable, dash=(2.0, 3.0))

    legend = report.header[1]
    assert isinstance(legend, RuleStrip)
    entries = dict((label, (color, dash)) for label, color, dash in legend.entries)
    assert entries["forward"] == (DEFAULT.axis, "solid")
    assert entries["skip"] == (DEFAULT.muted, "dashed")
    assert entries["loop / back"] == (DEFAULT.unfavorable, "dashed")
    assert entries["skip"] != entries["loop / back"]


def test_product_flow_caller_style_keeps_width_and_dash_period_edge_only():
    style = EdgeStyle("#123456", width=4.0, dash=(7.0, 5.0))
    report = _funnel_report(styles={"back": style})
    graph_styles = dict(report.graph.edge_styles)
    assert graph_styles["back"] == style

    legend = report.header[1]
    assert isinstance(legend, RuleStrip)
    entries = dict((label, (color, dash)) for label, color, dash in legend.entries)
    assert entries["loop / back"] == ("#123456", "dashed")


def test_product_flow_collapsible_inference_ignores_paint_only_back_edges():
    report = _funnel_report()
    assert "purchased" not in report.graph.collapsible
    assert "decide" not in report.graph.collapsible


# --- Card content and roles ------------------------------------------------


def test_rising_higher_is_better_event_is_favorable_with_expected_metrics():
    report = _funnel_report()
    card = _card(report, "viewed")
    metric, badge, trend, diagnostics = card.content
    assert isinstance(metric, Metric)
    assert metric.value == 1200.0
    assert metric.role == "favorable"
    assert isinstance(badge, Badge)
    assert badge.text == _CHANGE_FMT(20.0)
    assert badge.role == "favorable"
    assert isinstance(trend, Trend)
    assert trend.y == (1000.0, 1200.0)
    assert trend.show_axis is False
    assert trend.role == "favorable"
    assert isinstance(diagnostics, Diagnostics)
    assert diagnostics.items[0] == ("Now", _VALUE_FMT(1200.0))
    assert diagnostics.items[1] == ("Start", _VALUE_FMT(1000.0))
    assert diagnostics.items[2] == ("Change", _CHANGE_FMT(20.0))
    assert diagnostics.items[3] == ("Source", "organic")


def test_falling_lower_is_better_event_is_favorable():
    report = _funnel_report()
    metric, badge, trend, _diagnostics = _series_content(_card(report, "started"))
    assert metric.role == "favorable"
    assert badge.role == "favorable"
    assert trend.direction == "lower_is_better"
    assert badge.text == _CHANGE_FMT(-20.0)


def test_falling_higher_is_better_event_is_unfavorable():
    stages = ("A",)
    steps = (ProductStep("abandoned", "Abandoned", 0, 0, series=(300.0, 150.0)),)
    report = ProductFlow(stages, steps, ())
    metric, badge, _trend, _diagnostics = _series_content(_card(report, "abandoned"))
    assert metric.role == "unfavorable"
    assert badge.role == "unfavorable"


def test_flat_series_is_inconclusive():
    stages = ("A",)
    steps = (ProductStep("flat", "Flat", 0, 0, series=(50.0, 50.0)),)
    report = ProductFlow(stages, steps, ())
    metric, badge, _trend, _diagnostics = _series_content(_card(report, "flat"))
    assert metric.role == "inconclusive"
    assert badge.role == "inconclusive"


def test_terminal_card_adds_a_terminal_badge_and_strong_appearance():
    report = _funnel_report()
    card = _card(report, "purchased")
    *_content, terminal_badge = card.content
    assert isinstance(terminal_badge, Badge)
    assert terminal_badge.text == "terminal"
    assert terminal_badge.role == "neutral"
    assert card.appearance == CardAppearance(border="strong", fill="surface")


def test_decision_card_is_dashed_transparent_and_holds_only_its_note():
    report = _funnel_report()
    card = _card(report, "decide")
    assert card.appearance == CardAppearance(border="dashed", fill="transparent")
    assert len(card.content) == 1
    text_block = card.content[0]
    assert isinstance(text_block, TextBlock)
    assert text_block.text == "Reader picks monthly or annual"
    assert text_block.variant == "caption"


def test_event_card_uses_default_appearance():
    report = _funnel_report()
    assert _card(report, "viewed").appearance == CardAppearance()


def test_muted_step_uses_muted_emphasis_without_changing_its_border():
    stages = ("A",)
    steps = (ProductStep("hi_volume", "High volume", 0, 0, series=(10.0, 12.0), muted=True),)
    report = ProductFlow(stages, steps, ())
    card = _card(report, "hi_volume")
    assert card.appearance == CardAppearance(emphasis="muted")


def test_muted_terminal_step_combines_strong_border_with_muted_emphasis():
    stages = ("A",)
    steps = (
        ProductStep("final", "Final", 0, 0, kind="terminal", series=(10.0, 12.0), muted=True),
    )
    report = ProductFlow(stages, steps, ())
    card = _card(report, "final")
    assert card.appearance == CardAppearance(border="strong", emphasis="muted")


def test_share_of_diagnostic_reports_the_referenced_steps_percentage():
    report = _funnel_report()
    diagnostics = _card(report, "purchased").content[3]
    assert isinstance(diagnostics, Diagnostics)
    labels = [label for label, _value in diagnostics.items]
    assert "Share of Viewed" in labels
    share_value = dict(diagnostics.items)["Share of Viewed"]
    assert share_value == _CHANGE_FMT(150.0 / 1200.0 * 100.0)


def test_caller_diagnostics_are_appended_after_derived_entries():
    stages = ("A",)
    steps = (
        ProductStep(
            "x",
            "X",
            0,
            0,
            series=(10.0, 20.0),
            diagnostics=(("Cohort", "US"), ("Sample", 42.0)),
        ),
    )
    report = ProductFlow(stages, steps, ())
    diagnostics = _card(report, "x").content[3]
    assert isinstance(diagnostics, Diagnostics)
    assert diagnostics.items[-2:] == (("Cohort", "US"), ("Sample", 42.0))


def test_default_formatters_are_compact_number_and_signed_percent():
    report = _funnel_report()
    metric, badge, _trend, _diagnostics = _series_content(_card(report, "started"))
    assert metric.fmt(400.0) == Number(compact=True)(400.0)
    assert badge.text == Percent(signed=True, decimals=1)(-20.0)


def test_custom_formatters_are_applied_to_metric_trend_badge_and_diagnostics():
    value_fmt = Number(decimals=0, prefix="$")
    change_fmt = Percent(decimals=0)
    report = _funnel_report(value_fmt=value_fmt, change_fmt=change_fmt)
    card = _card(report, "viewed")
    metric, badge, trend, diagnostics = _series_content(card)
    assert metric.fmt is value_fmt
    assert trend.fmt is value_fmt
    (spark,) = trend.resolve(width=220, theme=report.graph.theme, chrome=card.chrome)
    assert f">{value_fmt(1200.0)}<" in spark.svg
    assert badge.text == change_fmt(20.0)
    assert diagnostics.items[0] == ("Now", value_fmt(1200.0))


# --- ProductFlow cross-step and structural validation ----------------------


def test_product_flow_rejects_duplicate_stage_names():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.stages must be unique")):
        ProductFlow(("A", "A"), (step(stage=0),), ())


def test_product_flow_rejects_empty_stages():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.stages must not be empty")):
        ProductFlow((), (step(),), ())


def test_product_flow_rejects_a_non_sequence_stages_argument():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.stages")):
        ProductFlow("AB", (step(),), ())


def test_product_flow_rejects_empty_steps():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.steps must not be empty")):
        ProductFlow(("A",), (), ())


def test_product_flow_rejects_a_step_that_is_not_a_product_step():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.steps[0] must be a ProductStep")):
        ProductFlow(("A",), (("not", "a", "step"),), ())  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_duplicate_step_ids():
    steps = (step(id="dup", stage=0), step(id="dup", stage=0, lane=1))
    with pytest.raises(SpecError, match=re.escape("ProductFlow.steps ids must be unique")):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_step_stage_out_of_range():
    with pytest.raises(SpecError, match="stage is out of range"):
        ProductFlow(("A",), (step(stage=1),), ())


def test_product_flow_rejects_sparse_lane_placements():
    steps = (step(id="a", stage=0, lane=0), step(id="b", stage=0, lane=2))
    with pytest.raises(SpecError, match="dense from zero"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_shared_stage_lane_position():
    steps = (step(id="a", stage=0, lane=0), step(id="b", stage=0, lane=0))
    with pytest.raises(SpecError, match="must not share a stage/lane"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_self_referencing_share_of():
    steps = (ProductStep("a", "A", 0, 0, series=(1.0, 2.0), share_of="a"),)
    with pytest.raises(SpecError, match="share_of must reference a distinct step"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_an_unknown_share_of_target():
    steps = (ProductStep("a", "A", 0, 0, series=(1.0, 2.0), share_of="missing"),)
    with pytest.raises(SpecError, match="share_of references an unknown step"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_decision_share_of_target():
    steps = (
        ProductStep("a", "A", 0, 0, series=(1.0, 2.0), share_of="d"),
        ProductStep("d", "D", 0, 1, kind="decision", series=(), note="explain"),
    )
    with pytest.raises(SpecError, match="share_of must reference a non-decision step"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_zero_denominator_share_of_target():
    steps = (
        ProductStep("a", "A", 0, 0, series=(1.0, 2.0), share_of="zero"),
        ProductStep("zero", "Zero", 0, 1, series=(10.0, 0.0)),
    )
    with pytest.raises(SpecError, match="share_of references a zero denominator"):
        ProductFlow(("A",), steps, ())


def test_product_flow_rejects_a_malformed_edge():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.edges[0] must be a FlowEdge")):
        ProductFlow(("A", "B"), (step(stage=0), step(id="b", stage=1)), (("not", "an", "edge"),))  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_a_non_sequence_edges_argument():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.edges")):
        ProductFlow(("A",), (step(),), edges=5)  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_a_non_callable_value_fmt():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.value_fmt must be callable")):
        ProductFlow(("A",), (step(),), (), value_fmt="nope")  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_a_non_callable_change_fmt():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.change_fmt must be callable")):
        ProductFlow(("A",), (step(),), (), change_fmt="nope")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("width", [0, -10, 1.5])
def test_product_flow_rejects_a_non_positive_card_width(width):
    message = re.escape("ProductFlow.card_width must be a positive int")
    with pytest.raises(SpecError, match=message):
        ProductFlow(("A",), (step(),), (), card_width=width)


def test_product_flow_rejects_a_non_str_title():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.title must be a str")):
        ProductFlow(("A",), (step(),), (), title=123)  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_a_non_str_note():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.note must be a str")):
        ProductFlow(("A",), (step(),), (), note=123)  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_an_invalid_theme():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.theme must be a Theme")):
        ProductFlow(("A",), (step(),), (), theme="nope")  # ty: ignore[invalid-argument-type]


def test_product_flow_rejects_an_invalid_chrome():
    with pytest.raises(SpecError, match=re.escape("ProductFlow.chrome must be a CardChrome")):
        ProductFlow(("A",), (step(),), (), chrome="nope")  # ty: ignore[invalid-argument-type]


def test_product_flow_snapshots_stage_step_and_edge_sequences():
    stages = ["Viewed", "Started", "Purchased"]
    steps = list(_funnel_steps())
    edges = list(_funnel_edges())
    report = ProductFlow(stages, steps, edges, title="Checkout flow", note="Zero JS")
    stages.append("Mutated")
    steps.append(step(id="mutated", stage=0))
    edges.clear()
    assert isinstance(report.graph.layout, Staged)
    assert report.graph.layout.labels == ("Viewed", "Started", "Purchased")
    assert tuple(node_id for node_id, _card in report.graph.nodes) == (
        "viewed",
        "started",
        "decide",
        "purchased",
    )
    assert len(report.graph.wires) == len(_funnel_edges())


# --- Same-stage and adjacent-skip literal prototype topology --------------


def _literal_prototype_stages() -> tuple[str, ...]:
    return ("Browse", "Cart", "Checkout", "Payment", "Confirmed")


def _literal_prototype_steps() -> tuple[ProductStep, ...]:
    return (
        ProductStep("searched", "Searched catalog", 0, 0, series=(78.0, 84.1)),
        ProductStep("viewed", "Viewed product", 0, 1, series=(290.0, 310.0), muted=True),
        ProductStep("added", "Added to cart", 1, 1, series=(58.0, 62.0)),
        ProductStep("saved", "Saved for later", 1, 0, series=(11.0, 13.0)),
        ProductStep("started", "Checkout started", 2, 1, series=(38.0, 41.2)),
        ProductStep(
            "shipping", "/shipping", 2, 2, kind="decision", series=(), note="routing decision"
        ),
        ProductStep("paysub", "Payment submitted", 3, 1, series=(34.0, 37.0)),
        ProductStep(
            "payfail", "Payment failed", 3, 2, series=(4.2, 3.6), direction="lower_is_better"
        ),
        ProductStep("confirmed", "Order confirmed", 4, 1, kind="terminal", series=(30.0, 33.5)),
    )


def _literal_prototype_edges() -> tuple[FlowEdge, ...]:
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


def test_product_flow_constructs_every_literal_prototype_edge_shape():
    """The literal prototype's 12 flows include five edge shapes R6's
    original geometry rules rejected outright: three same-stage forwards
    (searched to viewed, started to shipping, paysub to payfail), one
    same-stage skip (saved to added), and one adjacent-stage skip (viewed
    to saved). All twelve must construct and route."""
    report = ProductFlow(
        _literal_prototype_stages(), _literal_prototype_steps(), _literal_prototype_edges()
    )
    assert len(report.graph.nodes) == 9
    assert len(report.graph.wires) == 12
    same_stage_ids = ("searched-viewed", "started-shipping", "paysub-payfail", "saved-added")
    wire_geometry = dict(report.graph._layout.wire_geometry)
    for wire_id in same_stage_ids:
        assert wire_id in wire_geometry
    assert report.as_raw_html() == report.as_raw_html()
