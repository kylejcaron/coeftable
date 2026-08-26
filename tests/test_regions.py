"""Contract tests for the built-in card regions."""

from typing import Any, TypedDict

import pytest

import coeftable as ct
from coeftable.cards import (
    DEFAULT_CHROME,
    CaptionRow,
    CardChrome,
    MetricValue,
    RuleStrip,
    TextBlock,
)
from coeftable.cards.regions import Diagnostics, Event, Events, Metric, resolve_content
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT, Theme


def _unchecked(value: object) -> Any:
    return value


class ResolveKw(TypedDict):
    """Parameters supplied to region resolution."""

    width: int
    theme: Theme
    chrome: CardChrome


RESOLVE_KW: ResolveKw = {"width": 220, "theme": DEFAULT, "chrome": DEFAULT_CHROME}


def test_metric_with_ci_resolves_value_detail_and_role():
    (adorn,) = Metric(3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ref=0.0).resolve(**RESOLVE_KW)
    assert isinstance(adorn, MetricValue)
    assert adorn.value == ct.Percent(signed=True)(3.4)
    assert adorn.detail == f"[{ct.Percent(signed=True)(1.2)}, {ct.Percent(signed=True)(5.7)}]"
    assert adorn.role == "favorable"


def test_metric_ci_fmt_overrides_detail_formatting():
    (adorn,) = Metric(
        3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ci_fmt=ct.Number(), ref=0.0
    ).resolve(**RESOLVE_KW)
    assert adorn.detail == f"[{ct.Number()(1.2)}, {ct.Number()(5.7)}]"


def test_metric_without_ci_is_neutral_with_no_detail():
    (adorn,) = Metric(3.4, ct.Number(), ref=0.0).resolve(**RESOLVE_KW)
    assert adorn.role == "neutral"
    assert adorn.detail is None


@pytest.mark.parametrize(
    "ci,direction,expected",
    [
        ((1.2, 5.7), "higher_is_better", "favorable"),
        ((-5.7, -1.2), "higher_is_better", "unfavorable"),
        ((-1.0, 1.0), "higher_is_better", "inconclusive"),
        ((1.2, 5.7), "lower_is_better", "unfavorable"),
    ],
)
def test_metric_role_paths(ci, direction, expected):
    (adorn,) = Metric(3.4, ct.Number(), ci=ci, ref=0.0, direction=direction).resolve(**RESOLVE_KW)
    assert adorn.role == expected


def test_metric_explicit_role_overrides():
    (adorn,) = Metric(3.4, ct.Number(), ci=(1.2, 5.7), ref=0.0, role="inconclusive").resolve(
        **RESOLVE_KW
    )
    assert adorn.role == "inconclusive"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Metric(float("nan"), ct.Number()),
        lambda: Metric(True, ct.Number()),
        lambda: Metric(3.4, _unchecked("not callable")),
        lambda: Metric(3.4, ci=_unchecked(1), fmt=ct.Number()),
        lambda: Metric(3.4, ct.Number(), ci=(5.7, 1.2)),
        lambda: Metric(3.4, ct.Number(), ci=(1.2,)),
        lambda: Metric(3.4, ct.Number(), ci=(1.2, float("inf"))),
        lambda: Metric(3.4, ct.Number(), ref=float("nan")),
        lambda: Metric(3.4, ct.Number(), direction=_unchecked("sideways")),
        lambda: Metric(3.4, ct.Number(), role=_unchecked("loud")),
    ],
    ids=[
        "nan-value",
        "bool-value",
        "fmt-not-callable",
        "malformed-ci",
        "unordered-ci",
        "short-ci",
        "inf-ci",
        "nan-ref",
        "bad-direction",
        "bad-role",
    ],
)
def test_metric_validation(build):
    with pytest.raises(SpecError):
        build()


def test_diagnostics_formats_numbers_and_passes_strings():
    (adorn,) = Diagnostics(
        "diagnostics", [("n", 412), ("estimator", "ATT")], fmt=ct.Number(), key="diag"
    ).resolve(**RESOLVE_KW)
    assert adorn.label == "diagnostics"
    assert adorn.items == (("n", ct.Number()(412)), ("estimator", "ATT"))
    assert adorn.key == "diag"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Diagnostics("", [("k", 1)]),
        lambda: Diagnostics("d", []),
        lambda: Diagnostics("d", _unchecked(1)),
        lambda: Diagnostics("d", [("k", True)]),
        lambda: Diagnostics("d", [("k", float("nan"))]),
        lambda: Diagnostics("d", _unchecked([(1, "v")])),
        lambda: Diagnostics("d", _unchecked([1])),
    ],
    ids=[
        "empty-label",
        "empty-items",
        "malformed-items",
        "bool-value",
        "nan-value",
        "nonstr-key",
        "malformed-item",
    ],
)
def test_diagnostics_validation(build):
    with pytest.raises(SpecError):
        build()


def test_events_resolve_strip_and_optional_captions():
    events = Events(
        [Event("launch", "#4C72B0", at=3.0), Event("incident", "#C44E52", dash="dashed")],
        captions=True,
    )
    strip, cap1, cap2 = events.resolve(**RESOLVE_KW)
    assert isinstance(strip, RuleStrip)
    assert strip.entries == (("launch", "#4C72B0", "dotted"), ("incident", "#C44E52", "dashed"))
    assert isinstance(cap1, CaptionRow) and cap1.text == "launch"
    assert isinstance(cap2, CaptionRow)
    assert cap2.dash == "dashed"


def test_events_rules_derive_from_positioned_events_only():
    events = Events([Event("launch", "#4C72B0", at=3.0), Event("nopos", "#111111")])
    rules = events.rules()
    assert len(rules) == 1
    rule = rules[0]
    assert (rule.at, rule.axis, rule.color, rule.dash) == (3.0, "x", "#4C72B0", "dotted")
    assert rule.affect_domain is False


@pytest.mark.parametrize(
    "build",
    [
        lambda: Events([]),
        lambda: Events(_unchecked(1)),
        lambda: Events([Event("", "#111111")]),
        lambda: Events([Event("x", "#111111", dash=_unchecked("wavy"))]),
        lambda: Events([Event("x", "#111111", at=float("nan"))]),
    ],
    ids=["no-events", "malformed-events", "empty-label", "bad-dash", "nan-at"],
)
def test_events_validation(build):
    with pytest.raises(SpecError):
        build()


def test_resolve_content_passthrough_is_identity_and_flattens_in_order():
    block = TextBlock("title", variant="title")
    metric = Metric(3.4, ct.Number())
    out = resolve_content([block, metric], **RESOLVE_KW)
    assert out[0] is block
    assert isinstance(out[1], MetricValue)
    assert len(out) == 2


def test_resolve_content_accepts_structural_third_party_regions():
    class Custom:
        def resolve(self, *, width, theme, chrome):
            return (TextBlock("custom"),)

    out = resolve_content([Custom()], **RESOLVE_KW)
    assert out == (TextBlock("custom"),)


def test_resolve_content_rejects_unknown_objects_with_index_and_type():
    with pytest.raises(SpecError) as excinfo:
        resolve_content(_unchecked([TextBlock("ok"), object()]), **RESOLVE_KW)
    assert "1" in str(excinfo.value)
    assert "object" in str(excinfo.value)


def test_canonicalization_snapshots_caller_lists():
    items = [("n", 412)]
    diag = Diagnostics("d", items)
    items.append(("mutated", 1))
    (adorn,) = diag.resolve(**RESOLVE_KW)
    assert adorn.items == (("n", ct.Number()(412)),)


def test_events_canonicalization_snapshots_caller_lists():
    source = [Event("launch", "#4C72B0")]
    events = Events(source)
    source.append(Event("mutated", "#C44E52"))
    (strip,) = events.resolve(**RESOLVE_KW)
    assert isinstance(strip, RuleStrip)
    assert strip.entries == (("launch", "#4C72B0", "dotted"),)
