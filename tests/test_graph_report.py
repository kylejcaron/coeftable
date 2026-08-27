import pytest

from coeftable.cards import Callout, Card, InlineSvg, TextBlock
from coeftable.errors import SpecError
from coeftable.graph import Graph, GraphReport, Slot, Slotted


def _graph() -> Graph:
    nodes = (("a", Card("A", width=120)), ("b", Card("B", width=120)))
    slots = (Slot("a", 0, 0), Slot("b", 1, 0))
    return Graph(nodes, Slotted(slots))


def test_report_height_is_the_sum_of_its_measured_parts():
    graph = _graph()
    strip = InlineSvg('<svg width="200" height="40"></svg>', 200, 40)
    report = GraphReport(graph, header=(strip,), gap=10)
    measured = report.measure()
    assert measured.height == 40 + 10 + graph.measure().height
    assert measured.graph_top == 40 + 10


def test_report_width_is_the_widest_part():
    graph = _graph()
    wide = InlineSvg('<svg width="900" height="20"></svg>', 900, 20)
    report = GraphReport(graph, header=(wide,))
    assert report.measure().width == 900


def test_report_with_no_furniture_matches_the_bare_graph():
    graph = _graph()
    report = GraphReport(graph)
    assert report.measure().height == graph.measure().height
    assert report.measure().graph_top == 0


def test_report_renders_header_then_graph_then_footer_in_order():
    graph = _graph()
    report = GraphReport(
        graph,
        header=(TextBlock("above", variant="caption"),),
        footer=(Callout("below", role="unfavorable"),),
    )
    html = report.as_raw_html()
    assert html.index("above") < html.index("g0-card-0") < html.index("below")


def test_report_renders_in_a_notebook():
    assert GraphReport(_graph())._repr_html_().startswith("<div")


def test_report_rejects_a_non_graph():
    with pytest.raises(SpecError, match=r"GraphReport\.graph must be a Graph"):
        GraphReport(object())  # ty: ignore[invalid-argument-type]


def test_report_rejects_a_negative_gap():
    with pytest.raises(SpecError, match=r"GraphReport\.gap must be a non-negative int"):
        GraphReport(_graph(), gap=-1)


def test_report_gap_applies_only_between_present_sections():
    # A footer-only report must not reserve a leading gap.
    graph = _graph()
    strip = InlineSvg('<svg width="100" height="30"></svg>', 100, 30)
    report = GraphReport(graph, footer=(strip,), gap=12)
    assert report.measure().graph_top == 0
    assert report.measure().height == graph.measure().height + 12 + 30
