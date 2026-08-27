"""End-to-end tests for the `DriverTree` composition-root entry point.

Every fixture uses real, hand-computed numbers: identity gaps, coverage
percentages, and correlations are worked out by hand (or verified against
`coeftable.graph.honesty`'s own pure functions) rather than asserted against
whatever the implementation happens to emit.
"""

import math
import re
from dataclasses import replace

import pytest

from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.cards.regions import Metric, Trend
from coeftable.errors import SpecError
from coeftable.format import Number, Percent
from coeftable.graph import DriverTree, GraphReport
from coeftable.graph.breakout import Breakout
from coeftable.graph.driver_tree import _CARD_WIDTH, _compute_contributions, _Topology
from coeftable.graph.honesty import log_ratio
from coeftable.graph.timeline import TimelineEvent
from coeftable.svg import _projector

_FMT = Percent(decimals=1)


def _fixture(
    *,
    chrome: CardChrome = DEFAULT_CHROME,
    events: tuple[TimelineEvent, ...] | None = None,
) -> GraphReport:
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
    if events is None:
        events = (
            TimelineEvent(at=1.0, label="Launch", color="#4C72B0", affects=("revenue", "users")),
        )
    return DriverTree(series, titles, breakouts, _FMT, x, events=events, chrome=chrome)


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


def _short_fixture(*, events: tuple[TimelineEvent, ...] = ()) -> GraphReport:
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
    return DriverTree(series, titles, breakouts, _FMT, x, events=events)


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


def test_a_switcher_parent_has_no_operator_badge_but_its_options_do():
    """A dropdown's option labels already name each operator; a badge would
    be stuck showing only the default alternative's operator, so a parent
    with two or more alternatives gets none at all.
    """
    html = _fixture().as_raw_html()
    assert re.search(r">\u00d7 decomposition</span>", html) is None
    assert re.search(r">\+ slice</span>", html) is None
    assert "by drivers (\u00d7 decomposition)" in html
    assert "by region (+ slice)" in html


def test_a_single_alternative_parent_still_shows_its_operator_badge():
    """No dropdown, no option labels: the badge is the only place the
    (fixed) operator is stated, so it must render.
    """
    html = _short_fixture().as_raw_html()
    assert re.search(r">\+ slice</span>", html) is not None


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

    graph = report.graph
    node_ids = tuple(node_id for node_id, _ in graph.nodes)
    card_dom_ids = dict(zip(node_ids, graph._compiled.card_dom_ids, strict=True))

    # Derive the pixel the fan-out's sparkline rule must land on from the
    # same projection `coeftable.svg` applies when resolving a `Trend`
    # region: `left`/`right` are non-root cards, so `_CARD_WIDTH` minus
    # `DEFAULT_CHROME`'s padding/border is the usable width `Card` hands
    # every region, and `Trend`'s own endpoint reserve narrows it further.
    usable = _CARD_WIDTH - 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    trend_defaults = Trend(x=(0.0,), y=(0.0,), x_domain=(0.0, 1.0), domain=(0.0, 1.0))
    plot_width = usable - trend_defaults.endpoint_width
    inset = trend_defaults.inset
    project = _projector((0.0, 2.0), plot_width, inset)
    expected_x = re.escape(f"{project(event.at):.2f}")
    rule = re.compile(
        rf'<line x1="{expected_x}" y1="[0-9.]+" x2="{expected_x}" y2="[0-9.]+" '
        rf'stroke="{re.escape(event.color)}"'
    )

    def card_html(node_id: str) -> str:
        dom_id = card_dom_ids[node_id]
        start = html.index(f'<div id="{dom_id}"')
        next_start = html.find('<div id="', start + 1)
        return html[start : next_start if next_start != -1 else len(html)]

    # The projected rule shows up in the affected card's own sparkline...
    assert rule.search(card_html("left"))
    # ...and nowhere in an unaffected sibling's, even though it shares the
    # same x-domain and would land on the identical pixel if it leaked.
    assert rule.search(card_html("right")) is None


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


def test_multiplicative_contribution_uses_the_shared_log_ratio_for_a_subnormal_quotient():
    """The multiplicative attribution path must reuse `honesty.log_ratio`, not a
    private copy: a subnormal quotient (the smallest subnormal divided by 1.5,
    which rounds right back to itself) needs the log-subtraction fallback, and
    a stale direct-quotient copy would silently drop the ~log(1.5) it loses.
    """
    smallest_subnormal = 5e-324
    node_series: dict[str, tuple[float, ...]] = {
        "parent": (10.0, 12.0, 15.0),
        "a": (1.5, 1.5, smallest_subnormal),
        "b": (2.0, 3.0, 4.0),
    }
    breakout = Breakout(key="k", label="L", op="x", children=("a", "b"))
    topology = _Topology(parents=("parent",), breakout_map={"parent": (breakout,)})

    contributions = _compute_contributions(topology, node_series, {})

    total_a = log_ratio(node_series["a"][-1], node_series["a"][0])
    total_b = log_ratio(node_series["b"][-1], node_series["b"][0])
    total_sum = math.fsum((total_a, total_b))
    parent_delta = 50.0  # hand-computed: (15 - 10) / 10 * 100
    expected_a = parent_delta * (total_a / total_sum)

    # The pre-fix copy took the direct quotient whenever it was merely
    # positive and finite, missing the subnormal case entirely.
    stale_ratio = node_series["a"][-1] / node_series["a"][0]
    stale_total_a = math.log(stale_ratio)
    stale_expected_a = parent_delta * (stale_total_a / math.fsum((stale_total_a, total_b)))

    assert contributions[("parent", "a")] == pytest.approx(expected_a)
    assert abs(contributions[("parent", "a")] - stale_expected_a) > 1e-8


def _zero_residual_fixture() -> GraphReport:
    """A residual that is exactly zero at one observation, never negative."""
    x = (0.0, 1.0, 2.0)
    titles = {"budget": "Budget", "paid_b": "Paid", "organic_b": "Organic"}
    series = {
        "budget": (1000.0, 1040.0, 1081.0),
        "paid_b": (600.0, 620.0, 645.0),
        "organic_b": (400.0, 335.0, 345.0),
    }
    # implied = paid_b + organic_b = (1000, 955, 990); residual = budget - implied
    #   = (0, 85, 91); gap = (0/1000 + 85/1040 + 91/1081) / 3 ~= 0.0553 (0.5%-20%).
    breakouts = {
        "budget": (
            Breakout(
                key="channel_b", label="by channel", op="+", children=("paid_b", "organic_b")
            ),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _negative_residual_fixture() -> GraphReport:
    """Children over-explain the parent at every point: the residual is negative throughout."""
    x = (0.0, 1.0, 2.0)
    titles = {"outlay": "Outlay", "paid_o": "Paid", "organic_o": "Organic"}
    series = {
        "outlay": (1000.0, 1040.0, 1081.0),
        "paid_o": (700.0, 730.0, 760.0),
        "organic_o": (400.0, 420.0, 430.0),
    }
    # implied = paid_o + organic_o = (1100, 1150, 1190); residual = outlay - implied
    #   = (-100, -110, -109); gap = (100/1000 + 110/1040 + 109/1081) / 3 ~= 0.1022 (0.5%-20%).
    breakouts = {
        "outlay": (
            Breakout(
                key="channel_o", label="by channel", op="+", children=("paid_o", "organic_o")
            ),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _trend_for(report: GraphReport, node_id: str) -> Trend:
    card = dict(report.graph.nodes)[node_id]
    for region in card.content:
        if isinstance(region, Trend):
            return region
    raise AssertionError(f"no Trend region on {node_id!r}")


def _metric_for(report: GraphReport, node_id: str) -> Metric:
    card = dict(report.graph.nodes)[node_id]
    for region in card.content:
        if isinstance(region, Metric):
            return region
    raise AssertionError(f"no Metric region on {node_id!r}")


def test_a_residual_touching_zero_renders_without_a_ribbon():
    report = _zero_residual_fixture()
    trend = _trend_for(report, "resid_budget_channel_b")
    assert trend.y == (0.0, 85.0, 91.0)
    assert trend.lower is None
    assert trend.upper is None
    assert trend.domain[0] < trend.domain[1]  # non-degenerate despite the touched zero
    assert "Unattributed" in report.as_raw_html()


def test_a_residual_that_over_explains_the_parent_is_negative_and_still_renders():
    report = _negative_residual_fixture()
    trend = _trend_for(report, "resid_outlay_channel_o")
    assert trend.y == (-100.0, -110.0, -109.0)
    assert all(value is not None and value < 0 for value in trend.y)
    assert trend.lower is None
    assert trend.upper is None
    assert trend.domain[0] < trend.domain[1]
    assert "Unattributed" in report.as_raw_html()


def test_a_normal_positive_node_series_still_gets_its_ribbon():
    """The residual fix must not strip ribbons from ordinary level series."""
    report = _short_fixture()
    trend = _trend_for(report, "paid")
    assert trend.lower is not None
    assert trend.upper is not None
    assert trend.domain[0] < trend.domain[1]


def _colliding_residual_ids_fixture() -> GraphReport:
    """Two distinct (parent, breakout-key) pairs collide on the same id:
    `("a_b", "c")` and `("a", "b_c")` both join to `resid_a_b_c`."""
    x = (0.0, 1.0, 2.0)
    titles = {"a_b": "AB", "c1": "C1", "c2": "C2", "a": "A", "d1": "D1", "d2": "D2"}
    series = {
        "a_b": (1000.0, 1040.0, 1081.0),
        "c1": (600.0, 620.0, 645.0),
        "c2": (320.0, 335.0, 345.0),
        "a": (1000.0, 1040.0, 1081.0),
        "d1": (600.0, 620.0, 645.0),
        "d2": (320.0, 335.0, 345.0),
    }
    breakouts = {
        "a_b": (Breakout(key="c", label="c", op="+", children=("c1", "c2")),),
        "a": (Breakout(key="b_c", label="b_c", op="+", children=("d1", "d2")),),
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_colliding_residual_ids_are_rejected_naming_both_pairs():
    with pytest.raises(SpecError, match="resid_a_b_c") as excinfo:
        _colliding_residual_ids_fixture()
    message = str(excinfo.value)
    assert "('a_b', 'c')" in message
    assert "('a', 'b_c')" in message


def _cyclic_breakout_fixture() -> GraphReport:
    """`root` is fine, but `a` and `b` decompose into each other: a cycle
    downstream of a legitimate root."""
    x = (0.0, 1.0, 2.0)
    titles = {"root": "Root", "a": "A", "b": "B"}
    series = {"root": (1.0, 2.0, 3.0), "a": (1.0, 2.0, 3.0), "b": (1.0, 2.0, 3.0)}
    breakouts = {
        "root": (Breakout(key="k1", label="k1", op="+", children=("a",)),),
        "a": (Breakout(key="k2", label="k2", op="+", children=("b",)),),
        "b": (Breakout(key="k3", label="k3", op="+", children=("a",)),),
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_a_cyclic_breakout_topology_is_refused_before_layout():
    """Regression: this used to overflow the recursion stack instead of
    raising a clean `SpecError`."""
    with pytest.raises(SpecError, match="acyclic"):
        _cyclic_breakout_fixture()


def _collapsed_self_cycle_fixture() -> GraphReport:
    """`p` switches between `a` and `b`, and `b` decomposes into `a`. The raw
    topology is acyclic, but collapsing `b` onto its representative (`a`,
    the default alternative's own child) yields a self-edge `a -> a`."""
    x = (0.0, 1.0, 2.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (10.0, 11.0, 12.0), "b": (10.0, 11.0, 12.0)}
    breakouts = {
        "p": (
            Breakout(key="opt_a", label="A", op="+", children=("a",)),
            Breakout(key="opt_b", label="B", op="+", children=("b",)),
        ),
        "b": (Breakout(key="only", label="Only", op="+", children=("a",)),),
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_a_collapsed_representative_self_edge_is_refused_not_a_recursion_error():
    """Regression: the acyclicity check validated only the raw breakout
    edges, but layout runs on representative-collapsed edges, which can
    introduce a cycle (here a self-edge on `a`) the raw graph never had --
    this used to overflow the recursion stack instead of raising."""
    with pytest.raises(SpecError, match="cyclic") as excinfo:
        _collapsed_self_cycle_fixture()
    assert "a" in str(excinfo.value)


def _switcher_with_residual_fixture() -> GraphReport:
    """A two-way switcher whose additive alternative falls short by ~8% and
    injects a residual: exercises the shared-slot exclusivity proof together
    with a residual hide rule on the very same select."""
    x = (0.0, 1.0, 2.0)
    titles = {
        "revenue": "Revenue",
        "users": "Users",
        "aov": "AOV",
        "paid": "Paid",
        "organic": "Organic",
    }
    series = {
        "revenue": (1000.0, 1040.0, 1081.0),
        "users": (100.0, 104.0, 108.1),  # users * aov == revenue exactly
        "aov": (10.0, 10.0, 10.0),
        "paid": (600.0, 620.0, 645.0),  # paid + organic falls short by ~8%
        "organic": (320.0, 335.0, 345.0),
    }
    breakouts = {
        "revenue": (
            Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            Breakout(key="channel", label="by channel", op="+", children=("paid", "organic")),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_a_switcher_with_an_injected_residual_builds_and_merges_the_hide_rule():
    """Regression: this combination used to fail at `Graph` construction
    because the residual's visibility was a second rule on the same option."""
    report = _switcher_with_residual_fixture()
    html = report.as_raw_html()
    assert "Unattributed" in html

    # Exactly one rule governs "drivers" being selected, and it hides both
    # channel's own subtree and the residual injected on channel's behalf.
    drivers_rules = [
        rule
        for rule in report.graph.rules
        if len(rule.when_all) == 1 and rule.when_all[0].option == "drivers"
    ]
    assert len(drivers_rules) == 1
    hidden = drivers_rules[0].hide_cards
    assert "paid" in hidden and "organic" in hidden
    assert "resid_revenue_channel" in hidden


def _nested_residual_orphan_fixture() -> GraphReport:
    """`revenue` switches drivers x vs. region +; `users` (a `drivers`
    child) has its own additive decomposition that falls short by ~8% and
    injects its own residual. Switching away from `drivers` must hide that
    nested residual too, not just `users`, `aov`, `new`, and `returning`.
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
        "revenue": (1000.0, 1040.0, 1081.0),
        "users": (1000.0, 1040.0, 1081.0),  # users * aov == revenue exactly (aov == 1)
        "aov": (1.0, 1.0, 1.0),
        "us": (600.0, 620.0, 645.0),  # us + eu == revenue exactly
        "eu": (400.0, 420.0, 436.0),
        # new + returning falls short of users by ~8%: injects a residual
        # owned by `users`, a plain non-switcher descendant one layer down.
        "new": (600.0, 620.0, 645.0),
        "returning": (320.0, 335.0, 345.0),
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


def test_switching_away_hides_a_nested_descendants_own_residual_too():
    """Regression: the edges used for switcher descendant traversal were
    captured before residuals joined the topology, so a residual injected
    by a nested (non-switcher) descendant survived as a visible orphan
    once its owner was switched away."""
    report = _nested_residual_orphan_fixture()
    assert "Unattributed" in report.as_raw_html()

    region_rule = next(
        rule
        for rule in report.graph.rules
        if len(rule.when_all) == 1 and rule.when_all[0].option == "region"
    )
    hidden = set(region_rule.hide_cards)
    assert {"users", "aov", "new", "returning", "resid_users_cohort"} <= hidden


def test_a_level_trends_endpoint_label_is_not_percent_formatted():
    """Regression: `fmt` (a percentage) used to double as `Trend.fmt`, so a
    level's own sparkline endpoint rendered as a percentage of itself."""
    html = _fixture().as_raw_html()
    assert "+1,219.0%" not in html  # the old bug: contribution fmt on a level
    # The Trend endpoint now shares the headline Metric's own plain format.
    assert html.count("1,219.0") >= 2


def test_a_custom_level_fmt_formats_only_the_trend_not_the_headline():
    report = DriverTree(
        {"root": (2.0, 4.0, 6.0), "child": (2.0, 4.0, 6.0)},
        {"root": "Root", "child": "Child"},
        {"root": (Breakout(key="k", label="k", op="+", children=("child",)),)},
        _FMT,
        (0.0, 1.0, 2.0),
        level_fmt=Number(decimals=3, prefix="$"),
    )
    trend = _trend_for(report, "root")
    assert trend.fmt(6.0) == "$6.000"
    # Inspect the headline's own resolved region rather than searching the
    # whole document: "6.0" is a substring of "$6.000", so a text search
    # cannot tell the two formatters apart.
    metric = _metric_for(report, "root")
    assert metric.fmt is not trend.fmt
    assert not metric.fmt(6.0).startswith("$")
    assert "$6.000" in report.as_raw_html()  # the Trend endpoint takes level_fmt


def test_a_custom_chrome_is_threaded_through_every_card():
    """Regression: cards used to always build with `DEFAULT_CHROME` while the
    `Graph` got the caller's, so any non-default chrome raised a mismatch."""
    chrome = replace(DEFAULT_CHROME, title_size=20)
    report = _fixture(chrome=chrome)
    for _node_id, card in report.graph.nodes:
        assert card.chrome == chrome
    assert "font-size:20px" in report.as_raw_html()


def test_an_event_affecting_an_unknown_node_is_refused():
    # A misspelled id would otherwise leave the event on the shared strip while
    # silently dropping its card marker and caption, reading as missing data.
    with pytest.raises(SpecError, match="affects unknown nodes"):
        _fixture(events=(TimelineEvent(at=1.0, label="typo", color="#c33", affects=("nope",)),))


def test_an_event_may_target_an_injected_residual():
    # Residuals join the node set late, so validation must run after they exist.
    report = _short_fixture(
        events=(TimelineEvent(at=1.0, label="ok", color="#c33", affects=("resid_spend_channel",)),)
    )
    assert report.measure().width > 0
