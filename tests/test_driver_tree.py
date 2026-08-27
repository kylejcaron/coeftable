"""End-to-end tests for the `DriverTree` composition-root entry point.

Every fixture uses real, hand-computed numbers: identity gaps, coverage
percentages, and correlations are worked out by hand (or verified against
`coeftable.graph.honesty`'s own pure functions) rather than asserted against
whatever the implementation happens to emit.
"""

import re

import pytest

from coeftable.errors import SpecError
from coeftable.format import Percent
from coeftable.graph import DriverTree, GraphReport
from coeftable.graph.breakout import Breakout
from coeftable.graph.timeline import TimelineEvent

_FMT = Percent(decimals=1)


def _fixture() -> GraphReport:
    """A two-way revenue switcher (drivers x vs. region +), both exact."""
    x = (0.0, 1.0, 2.0, 3.0)
    titles = {"revenue": "Revenue", "users": "Users", "aov": "AOV", "us": "US", "eu": "EU"}
    series = {
        # revenue = users * aov exactly, and = us + eu exactly: gap 0 both ways.
        "revenue": (1000.0, 1071.0, 1144.0, 1219.0),
        "users": (100.0, 105.0, 110.0, 115.0),
        "aov": (10.0, 10.2, 10.4, 10.6),
        "us": (600.0, 640.0, 680.0, 720.0),
        "eu": (400.0, 431.0, 464.0, 499.0),
    }
    breakouts = {
        "revenue": (
            Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            Breakout(key="region", label="by region", op="+", children=("us", "eu")),
        )
    }
    events = (
        TimelineEvent(at=1.0, label="Launch", color="#4C72B0", affects=("revenue", "users")),
    )
    return DriverTree(series, titles, breakouts, _FMT, x, events=events)


def _noisy_fixture() -> GraphReport:
    """One clean grower and one noisy-flat child (the pinned honesty fixture)."""
    child1 = (200.0, 210.0, 220.0, 230.0, 240.0, 250.0)
    child2 = (100.0, 108.0, 94.0, 106.0, 97.0, 101.0)  # from tests/test_honesty.py
    parent = tuple(a + b for a, b in zip(child1, child2, strict=True))
    x = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
    titles = {"combo": "Combo", "child1": "Child1", "child2": "Child2"}
    series = {"combo": parent, "child1": child1, "child2": child2}
    breakouts = {
        "combo": (Breakout(key="split", label="by split", op="+", children=("child1", "child2")),)
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _short_fixture() -> GraphReport:
    """Additive split that covers ~92% of its parent (gap ~8%): injects a residual."""
    x = (0.0, 1.0, 2.0)
    titles = {"spend": "Spend", "paid": "Paid", "organic": "Organic"}
    series = {
        "spend": (1000.0, 1040.0, 1081.0),
        "paid": (600.0, 620.0, 645.0),
        "organic": (320.0, 335.0, 345.0),
    }
    # implied = paid + organic = (920, 955, 990); gap = mean(|spend-implied|/spend)
    #   = (80/1000 + 85/1040 + 91/1081) / 3 ≈ 0.0820  (8%, between 0.5% and 20%)
    breakouts = {
        "spend": (
            Breakout(key="channel", label="by channel", op="+", children=("paid", "organic")),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _broken_fixture() -> GraphReport:
    """A + B is exactly 55% of the parent at every point: explains under 80%."""
    x = (0.0, 1.0, 2.0)
    titles = {"weak": "Weak Metric", "a": "A", "b": "B"}
    series = {
        "weak": (100.0, 110.0, 121.0),
        "a": (30.0, 33.0, 36.3),  # exactly 30% of weak at every point
        "b": (25.0, 27.5, 30.25),  # exactly 25% of weak at every point
    }
    breakouts = {"weak": (Breakout(key="split", label="by split", op="+", children=("a", "b")),)}
    return DriverTree(series, titles, breakouts, _FMT, x)


def _mult_gap_fixture() -> GraphReport:
    """A multiplicative split short by ~8.9%: gap is reported, never patched."""
    x = (0.0, 1.0, 2.0)
    titles = {"rev2": "Rev2", "childA": "ChildA", "childB": "ChildB"}
    series = {
        "rev2": (100.0, 120.0, 144.0),
        "childA": (10.0, 11.0, 12.0),
        "childB": (9.0, 10.0, 11.0),
    }
    # product = (90, 110, 132); gap = mean(|rev2-product|/rev2)
    #   = (10/100 + 10/120 + 12/144) / 3 ≈ 0.0889 (8.9%, between 0.5% and 20%)
    breakouts = {
        "rev2": (
            Breakout(key="factors", label="by factors", op="x", children=("childA", "childB")),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _tradeoff_fixture() -> GraphReport:
    """Two siblings whose weekly log-changes are an exact negative linear pair (r=-1)."""
    import math

    a_changes = [0.3, 0.1, 0.25, 0.05]
    b_changes = [-0.2 * change - 0.5 for change in a_changes]  # linear in a_changes => r == -1.0
    a = [100.0]
    for change in a_changes:
        a.append(a[-1] * math.exp(change))
    b = [100.0]
    for change in b_changes:
        b.append(b[-1] * math.exp(change))
    parent = tuple(x + y for x, y in zip(a, b, strict=True))
    x = (0.0, 1.0, 2.0, 3.0, 4.0)
    titles = {"combo": "Combo", "a": "A Metric", "b": "B Metric"}
    series = {"combo": parent, "a": tuple(a), "b": tuple(b)}
    breakouts = {"combo": (Breakout(key="split", label="by split", op="+", children=("a", "b")),)}
    return DriverTree(series, titles, breakouts, _FMT, x)


def _event_fanout_fixture() -> tuple[GraphReport, TimelineEvent]:
    x = (0.0, 1.0, 2.0)
    titles = {"hub": "Hub", "left": "Left", "right": "Right"}
    series = {"hub": (50.0, 55.0, 60.0), "left": (20.0, 22.0, 24.0), "right": (30.0, 33.0, 36.0)}
    breakouts = {
        "hub": (Breakout(key="split", label="by split", op="+", children=("left", "right")),)
    }
    event = TimelineEvent(
        at=1.0, label="Migration", color="#AA2233", affects=("left",), dash="solid"
    )
    return DriverTree(series, titles, breakouts, _FMT, x, events=(event,)), event


def _nested_fixture() -> GraphReport:
    """`mid` is both a child of the `root` switcher and a switcher itself: nested."""
    titles = {
        "root": "Root",
        "mid": "Mid",
        "leaf1": "Leaf1",
        "mid2": "Mid2",
        "leaf2": "Leaf2",
        "x1": "X1",
        "x2": "X2",
        "x3": "X3",
        "x4": "X4",
    }
    series = {name: (10.0, 11.0, 12.0) for name in titles}
    breakouts = {
        "root": (
            Breakout(key="a", label="A", op="+", children=("mid", "leaf1")),
            Breakout(key="b", label="B", op="+", children=("mid2", "leaf2")),
        ),
        "mid": (
            Breakout(key="c", label="C", op="+", children=("x1", "x2")),
            Breakout(key="d", label="D", op="+", children=("x3", "x4")),
        ),
    }
    return DriverTree(series, titles, breakouts, _FMT, (0.0, 1.0, 2.0))


def _orphan_fixture() -> GraphReport:
    """`revenue` switches drivers x vs. region +; `users` (a `drivers` child)
    has its own always-on two-child decomposition. Switching `revenue` away
    from `drivers` must hide `users`' grandchildren too, not just `users`.
    """
    x = (0.0, 1.0, 2.0)
    titles = {
        "revenue": "Revenue",
        "users": "Users",
        "aov": "AOV",
        "us": "US",
        "eu": "EU",
        "new": "New",
        "returning": "Returning",
    }
    series = {
        # revenue = users * aov exactly, and = us + eu exactly: gap 0 both ways.
        "revenue": (1000.0, 1100.0, 1200.0),
        "users": (100.0, 110.0, 120.0),
        "aov": (10.0, 10.0, 10.0),
        "us": (600.0, 660.0, 720.0),
        "eu": (400.0, 440.0, 480.0),
        # users = new + returning exactly: users' own always-on decomposition.
        "new": (60.0, 66.0, 72.0),
        "returning": (40.0, 44.0, 48.0),
    }
    breakouts = {
        "revenue": (
            Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            Breakout(key="region", label="by region", op="+", children=("us", "eu")),
        ),
        "users": (
            Breakout(key="cohort", label="by cohort", op="+", children=("new", "returning")),
        ),
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_driver_tree_builds_a_report_with_a_timeline_and_switcher():
    report = _fixture()
    assert isinstance(report, GraphReport)
    assert report.measure().graph_top > 0  # strip reserved space
    html = report.as_raw_html()
    assert "<select" in html
    assert "<script" not in html  # zero-JS law


def test_an_inconclusive_delta_renders_muted_with_an_ns_marker():
    html = _noisy_fixture().as_raw_html()
    assert html.count("\u00b7 ns") == 1  # exactly the noisy child's own wire


def test_a_short_additive_decomposition_injects_a_residual_child():
    html = _short_fixture().as_raw_html()
    assert "Unattributed" in html
    assert "identity residual (8% of Spend)" in html


def test_a_decomposition_explaining_under_eighty_percent_is_refused():
    with pytest.raises(SpecError, match="explains"):
        _broken_fixture()


def test_a_decomposition_explaining_under_eighty_percent_states_exact_coverage():
    with pytest.raises(SpecError, match=r"explains 55\.0% of 'Weak Metric'"):
        _broken_fixture()


def test_a_multiplicative_gap_is_reported_not_patched():
    html = _mult_gap_fixture().as_raw_html()
    assert "Unattributed" not in html
    assert "gap 9%" in html


def test_anticorrelated_siblings_raise_a_trade_off_callout():
    html = _tradeoff_fixture().as_raw_html()
    assert "trade-off: A Metric \u2194 B Metric" in html


def test_the_accounting_disclaimer_is_present_verbatim():
    html = _fixture().as_raw_html()
    assert "not causal impact and not levers" in html
    assert "realized 3-week change" in html


def test_an_event_reaches_every_affected_card_and_no_others():
    report, event = _event_fanout_fixture()
    html = report.as_raw_html()
    # One pin on the timeline strip plus one caption on the single affected
    # card ("left"): if the event had also reached "hub" or "right" (or
    # missed "left"), this count would be off.
    assert html.count(event.label) == 2


def test_a_nested_switcher_is_refused_with_the_documented_rule():
    with pytest.raises(SpecError, match="at most one breakout switcher"):
        _nested_fixture()


def test_switching_away_from_drivers_hides_users_own_decomposition_too():
    report = _orphan_fixture()
    graph = report.graph
    node_ids = tuple(node_id for node_id, _ in graph.nodes)
    card_dom_ids = dict(zip(node_ids, graph._compiled.card_dom_ids, strict=True))

    region_conditions, region_targets = next(
        (conditions, targets)
        for conditions, targets in graph._compiled.rules
        if any('value="region"' in condition for condition in conditions)
    )
    orphaned = {card_dom_ids["users"], card_dom_ids["new"], card_dom_ids["returning"]}
    assert orphaned <= set(region_targets)

    html = report.as_raw_html()
    style = html[html.rindex("<style>") :]
    prefix = ".g0-canvas" + "".join(f":has({condition})" for condition in region_conditions)
    expected = ",".join(f"{prefix} #{target}" for target in region_targets)
    assert f"{expected}{{display:none}}" in style


def test_output_is_deterministic():
    assert _fixture().as_raw_html() == _fixture().as_raw_html()


def test_series_missing_a_declared_node_is_a_spec_error():
    x = (0.0, 1.0, 2.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0)}  # "b" missing
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    with pytest.raises(SpecError, match="series is missing an entry for 'b'"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_unequal_alternative_sizes_are_refused_before_layout():
    x = (0.0, 1.0, 2.0)
    titles = {"p": "P", "a": "A", "b": "B", "c": "C"}
    series = {name: (10.0, 11.0, 12.0) for name in titles}
    breakouts = {
        "p": (
            Breakout(key="one", label="One", op="+", children=("a", "b")),
            Breakout(key="two", label="Two", op="+", children=("c",)),
        )
    }
    with pytest.raises(SpecError, match="same number of children"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_gap_badge_text_matches_hand_computed_percentage():
    html = _mult_gap_fixture().as_raw_html()
    assert re.search(r"factors gap 9%", html)
