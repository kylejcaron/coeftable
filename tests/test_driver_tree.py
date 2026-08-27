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

from coeftable.cards.adornments import Callout, TextBlock
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.cards.regions import Metric, Trend
from coeftable.errors import SpecError
from coeftable.format import Number, Percent
from coeftable.graph import DriverTree, GraphReport
from coeftable.graph.breakout import Breakout
from coeftable.graph.driver_tree import (
    _CARD_WIDTH,
    _compute_contributions,
    _Topology,
)
from coeftable.graph.honesty import log_ratio
from coeftable.graph.timeline import TimelineEvent
from coeftable.svg import _projector

_FMT = Percent(decimals=1)


def _fixture(
    *,
    chrome: CardChrome = DEFAULT_CHROME,
    events: tuple[TimelineEvent, ...] | None = None,
    caption: str | None = None,
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
    return DriverTree(
        series, titles, breakouts, _FMT, x, events=events, chrome=chrome, caption=caption
    )


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
    """A multiplicative split short by ~8.9% on average, ~10% at the start
    endpoint: gap is reported (the larger of the two), never patched."""
    x = (0.0, 1.0, 2.0)
    titles = {"rev2": "Rev2", "childA": "ChildA", "childB": "ChildB"}
    series = {
        "rev2": (100.0, 120.0, 144.0),
        "childA": (10.0, 11.0, 12.0),
        "childB": (9.0, 10.0, 11.0),
    }
    # product = (90, 110, 132); mean gap = mean(|rev2-product|/rev2)
    #   = (10/100 + 10/120 + 12/144) / 3 ≈ 0.0889 (8.9%, between 0.5% and 20%)
    # endpoint gap = max(|100-90|/100, |144-132|/144) = max(0.10, 0.0833) = 0.10
    # combined gap = max(mean, endpoint) = 0.10 (10%): the badge shows the
    # larger, worse-case discrepancy, not the averaged-away smaller one.
    breakouts = {
        "rev2": (
            Breakout(key="factors", label="by factors", op="x", children=("childA", "childB")),
        )
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def _tradeoff_fixture() -> GraphReport:
    """Two siblings whose weekly log-changes are an exact negative linear pair
    (r=-1), plus a second, unrelated breakout so `combo` is an actual
    switcher: a fixture with only one breakout is never a switcher (see
    `_Topology.switcher_parents`), so it cannot exercise a card hiding with
    its alternative."""
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
    # `c` and `d` split the same parent evenly, so they move in lockstep with
    # each other (r=1, never a trade-off) and explain `combo` exactly, unlike
    # `a`/`b`'s trade-off pair.
    c = tuple(value / 2.0 for value in parent)
    d = c
    x = (0.0, 1.0, 2.0, 3.0, 4.0)
    titles = {
        "combo": "Combo",
        "a": "A Metric",
        "b": "B Metric",
        "c": "C Metric",
        "d": "D Metric",
    }
    series = {"combo": parent, "a": tuple(a), "b": tuple(b), "c": c, "d": d}
    breakouts = {
        "combo": (
            Breakout(key="split", label="by split", op="+", children=("a", "b")),
            Breakout(key="alt", label="by alt", op="+", children=("c", "d")),
        )
    }
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
    series = {
        "root": (100.0, 110.0, 121.0),
        # `a` = mid + leaf1: exact at every point.
        "mid": (60.0, 66.0, 72.6),
        "leaf1": (40.0, 44.0, 48.4),
        # `b` = mid2 + leaf2: exact at every point.
        "mid2": (70.0, 77.0, 84.7),
        "leaf2": (30.0, 33.0, 36.3),
        # `mid`'s own switcher: `c` = x1 + x2, `d` = x3 + x4, both exact.
        "x1": (36.0, 39.6, 43.56),
        "x2": (24.0, 26.4, 29.04),
        "x3": (42.0, 46.2, 50.82),
        "x4": (18.0, 19.8, 21.78),
    }
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
    assert "by drivers \u00d7" in html
    assert "by region +" in html


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
    assert "gap 10%" in html


def test_anticorrelated_siblings_raise_a_trade_off_callout():
    html = _tradeoff_fixture().as_raw_html()
    assert "trade-off: A Metric \u2194 B Metric" in html


def test_no_caption_renders_by_default():
    report = _fixture()
    card = dict(report.graph.nodes)["revenue"]
    assert not any(isinstance(item, TextBlock) for item in card.content)


def _wide_span_fixture() -> GraphReport:
    """Same identity shape as `_fixture`, but `x` is irregularly spaced with
    a span of 20 units rather than 3: pins a caption's `{weeks}` substitution
    to the coordinates' own span, not to `len(x) - 1`."""
    x = (0.0, 10.0, 20.0)
    titles = {"total": "Total", "a": "A", "b": "B"}
    series = {
        "total": (100.0, 110.0, 121.0),
        "a": (60.0, 66.0, 72.6),
        "b": (40.0, 44.0, 48.4),
    }
    breakouts = {"total": (Breakout(key="split", label="by split", op="+", children=("a", "b")),)}
    return DriverTree(series, titles, breakouts, _FMT, x, caption="realized {weeks}-week change")


def test_a_captions_weeks_placeholder_describes_the_actual_span_not_the_observation_count():
    html = _wide_span_fixture().as_raw_html()
    assert "realized 20-week change" in html
    assert "realized 2-week change" not in html


def _fractional_span_fixture() -> GraphReport:
    """Same identity shape as `_fixture`, but `x` spans a fractional number
    of weeks: exercises `_format_period_count`'s non-whole-number branch,
    which `_wide_span_fixture` (a whole-number span) never touches."""
    x = (0.0, 1.25, 2.5)
    titles = {"total": "Total", "a": "A", "b": "B"}
    series = {
        "total": (100.0, 110.0, 121.0),
        "a": (60.0, 66.0, 72.6),
        "b": (40.0, 44.0, 48.4),
    }
    breakouts = {"total": (Breakout(key="split", label="by split", op="+", children=("a", "b")),)}
    return DriverTree(series, titles, breakouts, _FMT, x, caption="realized {weeks}-week change")


def test_a_captions_weeks_placeholder_formats_a_fractional_span_without_a_trailing_zero():
    html = _fractional_span_fixture().as_raw_html()
    assert "realized 2.5-week change" in html


def test_a_supplied_caption_renders_verbatim():
    html = _fixture(caption="Ask finance before repeating these numbers.").as_raw_html()
    assert "Ask finance before repeating these numbers." in html


def test_a_supplied_caption_still_substitutes_weeks():
    html = _fixture(caption="Covers the last {weeks} weeks only.").as_raw_html()
    assert "Covers the last 3 weeks only." in html


def test_a_supplied_caption_with_unrelated_braces_does_not_raise():
    text = "Formula: {a} + {b} is literal text, only {weeks} is substituted."
    html = _fixture(caption=text).as_raw_html()
    assert "Formula: {a} + {b} is literal text, only 3 is substituted." in html


def test_caption_must_be_a_str_or_none():
    with pytest.raises(SpecError, match="caption must be a str or None"):
        _fixture(caption=123)  # ty: ignore[invalid-argument-type]


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


def test_a_nested_switcher_is_accepted_and_the_ancestors_rule_covers_it():
    report = _nested_fixture()
    html = report.as_raw_html()
    assert html.count("<select") == 2
    assert "<script" not in html

    graph = report.graph
    node_ids = tuple(node_id for node_id, _ in graph.nodes)
    card_dom_ids = dict(zip(node_ids, graph._compiled.card_dom_ids, strict=True))

    b_conditions, b_targets = next(
        (conditions, targets)
        for conditions, targets in graph._compiled.rules
        if any('value="b"' in condition for condition in conditions)
    )
    # Selecting `b` switches the whole `mid` branch away: `mid`'s own
    # switcher card and every one of its alternatives must be hidden,
    # checked from the compiled rules, not just `hide_cards`.
    switched_away = {card_dom_ids[n] for n in ("mid", "leaf1", "x1", "x2", "x3", "x4")}
    assert switched_away <= set(b_targets)

    _a_conditions, a_targets = next(
        (conditions, targets)
        for conditions, targets in graph._compiled.rules
        if any('value="a"' in condition for condition in conditions)
    )
    # Selecting `a` keeps `mid` (and its nested switcher) visible; only
    # `b`'s own alternative is hidden.
    assert switched_away.isdisjoint(a_targets)
    assert {card_dom_ids["mid2"], card_dom_ids["leaf2"]} <= set(a_targets)

    style_output = html[html.rindex("<style>") :]
    prefix = ".g0-canvas" + "".join(f":has({condition})" for condition in b_conditions)
    expected = ",".join(f"{prefix} #{target}" for target in b_targets)
    assert f"{expected}{{display:none}}" in style_output
    assert report.measure().width > 0


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


def _three_level_nested_fixture() -> GraphReport:
    """Every level switches: `revenue` -> `users` -> `sessions`, each with
    its own two-way switcher, all three exact identities."""
    series = {
        "revenue": (1000.0, 1100.0, 1210.0),
        "users": (100.0, 110.0, 121.0),
        "aov": (10.0, 10.0, 10.0),
        "na": (600.0, 660.0, 726.0),
        "intl": (400.0, 440.0, 484.0),
        "sessions": (50.0, 55.0, 60.5),
        "conv": (2.0, 2.0, 2.0),
        "us_u": (60.0, 66.0, 72.6),
        "eu_u": (40.0, 44.0, 48.4),
        "web": (30.0, 33.0, 36.3),
        "app": (20.0, 22.0, 24.2),
        "paid": (35.0, 38.5, 42.35),
        "organic": (15.0, 16.5, 18.15),
    }
    titles = {name: name.replace("_", " ").title() for name in series}
    breakouts = {
        "revenue": (
            Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            Breakout(key="region", label="by region", op="+", children=("na", "intl")),
        ),
        "users": (
            Breakout(key="funnel", label="by funnel", op="x", children=("sessions", "conv")),
            Breakout(key="country", label="by country", op="+", children=("us_u", "eu_u")),
        ),
        "sessions": (
            Breakout(key="platform", label="by platform", op="+", children=("web", "app")),
            Breakout(key="channel", label="by channel", op="+", children=("paid", "organic")),
        ),
    }
    return DriverTree(series, titles, breakouts, _FMT, x=(0.0, 1.0, 2.0))


def test_a_three_level_nested_driver_tree_builds_with_a_switcher_at_every_level():
    report = _three_level_nested_fixture()
    html = report.as_raw_html()
    assert html.count("<select") == 3
    assert "<script" not in html
    measured = report.measure()
    assert measured.width > 0
    assert measured.height > 0


def test_a_card_gated_by_two_sibling_switchers_is_still_refused():
    # `a` and `b` are independent (sibling) switchers under `root`, not
    # nested inside one another; `shared` is reachable only through each
    # switcher's first option, so no single rule ever accounts for hiding
    # it. Removing the nesting rejection must not remove this guard.
    x = (0.0, 1.0, 2.0)
    titles = {name: name for name in ("root", "a", "b", "a1", "a2", "b1", "b2", "shared")}
    series = {
        "root": (100.0, 110.0, 120.0),
        "a": (50.0, 55.0, 60.0),
        "b": (50.0, 55.0, 60.0),
        "a1": (50.0, 55.0, 60.0),
        "a2": (50.0, 55.0, 60.0),
        "b1": (50.0, 55.0, 60.0),
        "b2": (50.0, 55.0, 60.0),
        "shared": (50.0, 55.0, 60.0),
    }
    breakouts = {
        "root": (Breakout(key="split", label="split", op="+", children=("a", "b")),),
        "a": (
            Breakout(key="opt1", label="opt1", op="+", children=("a1",)),
            Breakout(key="opt2", label="opt2", op="+", children=("a2",)),
        ),
        "b": (
            Breakout(key="opt1", label="opt1", op="+", children=("b1",)),
            Breakout(key="opt2", label="opt2", op="+", children=("b2",)),
        ),
        "a1": (Breakout(key="k", label="k", op="+", children=("shared",)),),
        "b1": (Breakout(key="k", label="k", op="+", children=("shared",)),),
    }
    with pytest.raises(SpecError, match=r"'shared'.*more than one breakout switcher"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_descending_x_is_refused_naming_the_offending_index():
    x = (2.0, 1.0, 0.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    with pytest.raises(SpecError, match=r"strictly increasing.*x\[1\]=1\.0.*x\[0\]=2\.0"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_duplicate_x_is_refused_naming_the_offending_index():
    x = (0.0, 1.0, 1.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    with pytest.raises(SpecError, match=r"strictly increasing.*x\[2\]=1\.0.*x\[1\]=1\.0"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_unequal_spacing_is_refused_naming_the_offending_gaps():
    x = (0.0, 1.0, 3.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    match = r"evenly spaced.*x\[2\] - x\[1\]=2\.0.*x\[1\] - x\[0\]=1\.0"
    with pytest.raises(SpecError, match=match):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_binary_rounded_uniform_spacing_is_accepted():
    """`(0.1, 0.2, 0.3)` is mathematically uniform, but `0.3 - 0.2` and
    `0.2 - 0.1` differ in their last bits under binary rounding -- an exact
    equality check would wrongly refuse it. The tolerance must accept it."""
    x = (0.1, 0.2, 0.3)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    DriverTree(series, titles, breakouts, _FMT, x)


def test_small_magnitude_unequal_spacing_is_still_refused():
    """The tolerance combines a relative component sized to the gap
    magnitude with an absolute floor sized to the coordinates' own
    floating-point resolution (a small multiple of `math.ulp`), not a
    blanket floor: a real ~50% spacing irregularity among small gaps
    must still be refused, not waved through as rounding noise."""
    x = (0.1, 0.2, 0.35)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    with pytest.raises(SpecError, match="evenly spaced"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_uniform_spacing_shifted_to_a_large_origin_is_still_accepted():
    """Translation invariance: `(0.1, 0.2, 0.3)` shifted to a large origin
    (e.g. `(1_000_000.0, 1_000_000.1, 1_000_000.2, 1_000_000.3)`) is exactly
    as uniform mathematically, but subtracting two similarly large floats
    loses absolute precision that swamps a purely relative tolerance sized
    to the (small) gap alone -- a relative-only check would wrongly refuse
    it. The absolute floor, scaled to the coordinates' own magnitude, must
    accept it."""
    x = tuple(1_000_000.0 + 0.1 * i for i in range(4))
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {
        "p": (10.0, 11.0, 12.0, 13.0),
        "a": (5.0, 5.5, 6.0, 6.5),
        "b": (5.0, 5.5, 6.0, 6.5),
    }
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    DriverTree(series, titles, breakouts, _FMT, x)


def test_uniform_spacing_at_a_1e9_origin_is_accepted():
    """The absolute floor must track `math.ulp(magnitude)`, not a fixed
    fraction of `magnitude`: at a magnitude around `1e9`, `1e-9 *
    magnitude` would itself be about `1`, which is far too coarse. A
    genuinely uniform sequence shifted to this origin must still be
    accepted."""
    x = tuple(1_000_000_000.0 + 0.1 * i for i in range(4))
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {
        "p": (10.0, 11.0, 12.0, 13.0),
        "a": (5.0, 5.5, 6.0, 6.5),
        "b": (5.0, 5.5, 6.0, 6.5),
    }
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    DriverTree(series, titles, breakouts, _FMT, x)


def test_large_magnitude_unequal_spacing_is_refused_not_swallowed():
    """A fixed-fraction-of-magnitude absolute floor (e.g. `1e-9 *
    magnitude`) would be about `1` at a magnitude of `1e9`, so gaps of
    `1` and `2` would wrongly compare equal there. The floor must instead
    track floating-point resolution at that magnitude, so this real
    doubling of the gap is still refused."""
    x = (1_000_000_000.0, 1_000_000_001.0, 1_000_000_003.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {"p": (10.0, 11.0, 12.0), "a": (5.0, 5.5, 6.0), "b": (5.0, 5.5, 6.0)}
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    with pytest.raises(SpecError, match="evenly spaced"):
        DriverTree(series, titles, breakouts, _FMT, x)


def test_equal_non_unit_spacing_is_accepted_with_a_correct_weeks_substitution():
    """Coordinates need not be unit-spaced, only *evenly* spaced."""
    x = (0.0, 7.0, 14.0, 21.0)
    titles = {"p": "P", "a": "A", "b": "B"}
    series = {
        # a + b = p exactly at every point: no gap, no residual.
        "p": (100.0, 110.0, 121.0, 133.0),
        "a": (60.0, 66.0, 72.6, 79.8),
        "b": (40.0, 44.0, 48.4, 53.2),
    }
    breakouts = {"p": (Breakout(key="k", label="K", op="+", children=("a", "b")),)}
    html = DriverTree(
        series, titles, breakouts, _FMT, x, caption="realized {weeks}-week change"
    ).as_raw_html()
    assert "realized 21-week change" in html


def test_gap_badge_text_matches_hand_computed_percentage():
    html = _mult_gap_fixture().as_raw_html()
    assert re.search(r"factors gap 10%", html)


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


def test_offsetting_multiplicative_factors_report_large_opposite_shares_not_zero():
    """Regression: users roughly doubling (100 -> 200) while aov roughly
    halves (10 -> 5) used to leave the parent flat at 1000 and collapse both
    edge labels to 0.0%, because the old scale (parent_delta / total_sum)
    multiplied every share by the parent's own ~0 delta. The continuous-limit
    fix reports the two real, opposite moves as roughly +/-69 log points
    instead of hiding them as nothing happening.
    """
    topology = _Topology(
        parents=("revenue",),
        breakout_map={
            "revenue": (
                Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            )
        },
    )
    node_series: dict[str, tuple[float, ...]] = {
        "revenue": (1000.0, 1000.0, 1000.0),
        "users": (100.0, 150.0, 200.0),
        "aov": (10.0, 7.5, 5.0),
    }

    contributions = _compute_contributions(topology, node_series, {})
    users_share = contributions[("revenue", "users")]
    aov_share = contributions[("revenue", "aov")]

    assert users_share > 50.0
    assert aov_share < -50.0
    assert users_share == pytest.approx(-aov_share, rel=1e-9)
    assert users_share == pytest.approx(math.log(2.0) * 100.0)


def test_multiplicative_contribution_still_sums_to_the_parents_total_change():
    """Sanity check for the near-zero fallback: an ordinary, non-flat
    multiplicative decomposition (users and aov both genuinely growing) must
    still apportion the parent's exact percentage change across its
    children, the way the un-patched formula always did.
    """
    topology = _Topology(
        parents=("revenue",),
        breakout_map={
            "revenue": (
                Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            )
        },
    )
    node_series: dict[str, tuple[float, ...]] = {
        "revenue": (1000.0, 1035.0, 1071.0),
        "users": (100.0, 102.0, 105.0),
        "aov": (10.0, 10.1, 10.2),
    }

    contributions = _compute_contributions(topology, node_series, {})
    total = contributions[("revenue", "users")] + contributions[("revenue", "aov")]
    parent_delta = (1071.0 - 1000.0) / 1000.0 * 100.0

    assert total == pytest.approx(parent_delta)


def _near_cancel_mismatch_series():
    """Users double (100 -> 200) while aov nearly, but not exactly, halves
    (10 -> 5.0000000005): the combined log ratio lands at ~1e-10, well
    below the near-cancellation floor. Unlike the fixtures above, revenue
    does *not* track users * aov at every period -- it is an approximate
    decomposition, not an exact one -- so the near-cancellation limit must
    not apply here.
    """
    x = (0.0, 1.0, 2.0)
    titles = {"revenue": "Revenue", "users": "Users", "aov": "AOV"}
    series = {
        "revenue": (1000.0, 1080.0, 1158.0),
        "users": (100.0, 150.0, 200.0),
        "aov": (10.0, 7.5, 5.0000000005),
    }
    # product = (1000, 1125, 1000.0000001); mean gap = mean(|revenue-product|/revenue)
    #   = (0/1000 + 45/1080 + 157.9999999/1158) / 3 ~= 0.0594 (~6%)
    # endpoint gap = max(0/1000, 157.9999999/1158) ~= 0.1364 (~14%)
    # combined gap = max(mean, endpoint) ~= 0.1364 (14%, between 0.5% and 20%)
    breakouts = {
        "revenue": (
            Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
        )
    }
    return series, titles, breakouts, x


def test_a_near_cancelling_approximate_decomposition_sums_to_the_parent_and_flags_the_gap():
    """Regression for the fix to the fix: near-cancellation used to collapse
    every share to ~0% whenever the combined log ratio was tiny, even when
    the parent's own change disagreed with that -- e.g. revenue moving
    +15.8% while users/aov merely offset each other. The shares must sum
    to what the parent actually did, and the mismatch must show up as a
    gap badge rather than being smoothed away.
    """
    series, titles, breakouts, x = _near_cancel_mismatch_series()
    topology = _Topology(parents=("revenue",), breakout_map={"revenue": breakouts["revenue"]})
    contributions = _compute_contributions(topology, dict(series), {})
    users_share = contributions[("revenue", "users")]
    aov_share = contributions[("revenue", "aov")]
    parent_delta = (1158.0 - 1000.0) / 1000.0 * 100.0

    assert users_share + aov_share == pytest.approx(parent_delta)
    # Not the old bug's flat +/-69.31% (log(2) * 100) that summed to ~0.
    assert abs(users_share) > 1000.0

    html = DriverTree(series, titles, breakouts, _FMT, x).as_raw_html()
    assert re.search(r"drivers gap 14%", html)


def test_a_small_endpoint_agreement_does_not_override_a_disagreeing_path():
    """Regression: an endpoint-only identity check could say 'the identity
    holds' (endpoints ~0.4% apart, under `RESIDUAL_WARN`) even though the
    parent's path disagrees with the children's product badly enough
    in between (~2% mean gap) to trip the identity-gap badge. Scaling and
    the badge must agree: a mismatch big enough for the badge must also
    fall back to `parent_delta / total_sum`, not the implied-identity share.
    """
    topology = _Topology(
        parents=("revenue",),
        breakout_map={
            "revenue": (
                Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            )
        },
    )
    node_series: dict[str, tuple[float, ...]] = {
        "revenue": (100.2, 105.0, 120.758),
        "users": (10.0, 11.0, 11.0),
        "aov": (10.0, 9.0, 11.0),
    }

    contributions = _compute_contributions(topology, node_series, {})
    total = contributions[("revenue", "users")] + contributions[("revenue", "aov")]
    parent_delta = (120.758 - 100.2) / 100.2 * 100.0
    total_sum = math.log(11.0 / 10.0) + math.log(11.0 / 10.0)
    identity_delta = 100.0 * math.expm1(total_sum)

    # Fallback (sums to the observed parent_delta), not the implied-identity
    # share (~21%) an endpoint-only check would have accepted.
    assert total == pytest.approx(parent_delta)
    assert total != pytest.approx(identity_delta)

    titles = {"revenue": "Revenue", "users": "Users", "aov": "AOV"}
    breakouts = {"revenue": topology.breakout_map["revenue"]}
    html = DriverTree(node_series, titles, breakouts, _FMT, (0.0, 1.0, 2.0)).as_raw_html()
    assert re.search(r"drivers gap 2%", html)


def test_small_offsetting_endpoint_noise_does_not_trigger_an_unbadged_extreme_fallback():
    """Regression: an endpoint-only identity check could disagree by more
    than `RESIDUAL_WARN` at the two endpoints alone (opposite-signed ~0.4%
    noise at each) while the parent tracks the children's product closely
    at every point (mean gap ~0.27%, under the badge threshold) -- and,
    combined with a near-cancelling combined log ratio, the un-patched
    fallback (`parent_delta / total_sum`) produced shares in the billions
    with no badge to warn the reader. No badge must mean no extreme escape
    hatch: scaling must agree with the badge and stay bounded.
    """
    topology = _Topology(
        parents=("revenue",),
        breakout_map={
            "revenue": (
                Breakout(key="drivers", label="by drivers", op="x", children=("users", "aov")),
            )
        },
    )
    node_series: dict[str, tuple[float, ...]] = {
        "revenue": (1004.0, 1125.0, 996.0000000996),
        "users": (100.0, 150.0, 200.0),
        "aov": (10.0, 7.5, 5.0000000005),
    }

    contributions = _compute_contributions(topology, node_series, {})
    users_share = contributions[("revenue", "users")]
    aov_share = contributions[("revenue", "aov")]

    # The un-patched endpoint check would have picked the near-cancelling
    # fallback and produced shares around +/-5.5 billion.
    assert abs(users_share) < 1000.0
    assert abs(aov_share) < 1000.0

    titles = {"revenue": "Revenue", "users": "Users", "aov": "AOV"}
    breakouts = {"revenue": topology.breakout_map["revenue"]}
    html = DriverTree(node_series, titles, breakouts, _FMT, (0.0, 1.0, 2.0)).as_raw_html()
    assert not re.search(r"drivers gap", html)


def _endpoint_dilution_fixture():
    """`a` and `b` track `parent`'s product exactly for twelve periods, then
    `parent` jumps 6% above their product at the thirteenth (last)
    observation alone. Averaged over all thirteen points the mismatch is
    only ~0.44% (under `RESIDUAL_WARN`), but at the endpoint alone -- the
    only two points the edge labels are actually computed from -- it is
    ~5.66% (over `RESIDUAL_WARN`).
    """
    n = 13
    x = tuple(float(i) for i in range(n))
    a = tuple(10.0 + i for i in range(n))
    b = tuple(5.0 + 0.2 * i for i in range(n))
    product = tuple(ai * bi for ai, bi in zip(a, b, strict=True))
    parent = (*product[:-1], product[-1] * 1.06)
    titles = {"parent": "Parent", "a": "A", "b": "B"}
    series = {"parent": parent, "a": a, "b": b}
    breakouts = {
        "parent": (Breakout(key="drivers", label="by drivers", op="x", children=("a", "b")),)
    }
    return series, titles, breakouts, x


def test_an_endpoint_only_mismatch_diluted_by_a_long_series_still_flags_and_reconciles():
    """Regression: `identity_gap`'s whole-series mean can stay under the
    badge threshold even when the parent's actual endpoint change disagrees
    badly with the children's product at the endpoint alone. The edge
    labels describe the endpoint change specifically, so that mismatch must
    still surface a badge, and the labels must still sum to what the parent
    actually did at the endpoint -- not to the wrong, identity-implied
    number a mean-only check would have picked.
    """
    series, titles, breakouts, x = _endpoint_dilution_fixture()
    topology = _Topology(parents=("parent",), breakout_map={"parent": breakouts["parent"]})
    contributions = _compute_contributions(topology, dict(series), {})
    a_share = contributions[("parent", "a")]
    b_share = contributions[("parent", "b")]
    parent_delta = (series["parent"][-1] - series["parent"][0]) / series["parent"][0] * 100.0
    total_sum = math.log(series["a"][-1] / series["a"][0]) + math.log(
        series["b"][-1] / series["b"][0]
    )
    identity_delta = 100.0 * math.expm1(total_sum)

    # Labels reconcile with the parent's actual endpoint change...
    assert a_share + b_share == pytest.approx(parent_delta)
    # ...not the wrong, identity-implied number a mean-only check would pick.
    assert parent_delta != pytest.approx(identity_delta)

    html = DriverTree(series, titles, breakouts, _FMT, x).as_raw_html()
    assert "drivers gap 6%" in html


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
    assert str(excinfo.value) == (
        "breakout layout is cyclic once alternatives collapse to shared positions: a"
    )


def _cycle_with_downstream_leaf_fixture() -> GraphReport:
    """`q` switches between default `a` and alternative `a2`, which collapses
    onto `a`'s representative position. `a` decomposes into `d` and a
    sibling `e`; `d` decomposes into `a2`, which resolves back onto `a`,
    closing a two-node cycle `a <-> d`. `e` is a plain downstream leaf: it
    is reachable *from* the cycle (via `a`'s own split) but never reaches
    back *into* it. Kahn's algorithm alone cannot tell `e` apart from the
    cycle it merely sits behind."""
    x = (0.0, 1.0, 2.0)
    titles = {"q": "Q", "a": "A", "a2": "A2", "d": "D", "e": "E"}
    series = {
        "q": (1000.0, 1000.0, 1000.0),
        "a": (1000.0, 1000.0, 1000.0),
        "a2": (999.0, 999.0, 999.0),
        "d": (999.0, 999.0, 999.0),
        "e": (1.0, 1.0, 1.0),
    }
    breakouts = {
        "q": (
            Breakout(key="opt_a", label="A", op="+", children=("a",)),
            Breakout(key="opt_a2", label="A2", op="+", children=("a2",)),
        ),
        "a": (Breakout(key="split", label="Split", op="+", children=("d", "e")),),
        "d": (Breakout(key="only", label="Only", op="+", children=("a2",)),),
    }
    return DriverTree(series, titles, breakouts, _FMT, x)


def test_the_cycle_diagnostic_names_only_the_cyclic_nodes_not_their_downstream():
    """Regression: naming every node Kahn's algorithm never dequeues blames
    `e`, a plain downstream leaf, for a cycle it plays no part in."""
    with pytest.raises(SpecError, match="cyclic") as excinfo:
        _cycle_with_downstream_leaf_fixture()
    assert str(excinfo.value) == (
        "breakout layout is cyclic once alternatives collapse to shared positions: a, d"
    )


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


def test_a_wrapped_multiline_caption_still_reconstructs_correctly():
    # A caption long enough to wrap renders one HTML element per line;
    # compare against the unwrapped text to confirm a phrase spanning a
    # line break still appears contiguously once flattened with spaces.
    caption = (
        "Edge labels are measured against a parent's starting value, not "
        "its own, so siblings sum to about the parent's change."
    )
    html = _fixture(caption=caption).as_raw_html()
    flat = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    flat = flat.replace("&#x27;", "'").replace("&amp;", "&")
    assert "measured against a parent's starting value, not its own" in flat
    assert "siblings sum to about the parent's change" in flat


def test_a_trade_off_warning_hides_with_the_alternative_it_describes():
    # The warning names two specific siblings, so it must not live on the
    # parent card: that card survives every switch and would keep warning
    # about cards the reader can no longer see. `_tradeoff_fixture` has two
    # breakouts (`split` and `alt`), so `combo` is an actual switcher and the
    # host really does disappear when the reader picks the other option.
    report = _tradeoff_fixture()
    html = report.as_raw_html()
    hosts = {
        node_id
        for node_id, card in report.graph.nodes
        if any(isinstance(a, Callout) and "trade-off" in a.text for a in card.content)
    }
    assert hosts, "expected a trade-off callout somewhere"
    parents = {"combo"}  # the switcher parent in _tradeoff_fixture
    assert not (hosts & parents), f"callout must not sit on a switcher parent: {hosts & parents}"
    assert "trade-off" in html

    split_host = hosts & {"a", "b"}
    assert split_host, f"expected the trade-off host among split's children, got {hosts}"
    other_option_rules = [
        rule
        for rule in report.graph.rules
        for atom in rule.when_all
        if atom.control.card_id == "combo" and atom.option != "split"
    ]
    assert other_option_rules, "expected a state rule for combo's non-default option"
    assert all(split_host <= set(rule.hide_cards) for rule in other_option_rules), (
        f"host {split_host} must be hidden once combo switches away from split"
    )
