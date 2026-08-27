import html
import re

import pytest

from coeftable.errors import SpecError
from coeftable.graph.timeline import (
    _CHAR_WIDTH_RATIO,
    _DASH_ARRAY,
    _INSET,
    _LABEL_FONT_SIZE,
    _LABEL_HALO,
    _MIN_HEIGHT,
    _MIN_WIDTH,
    _TICK_FONT_SIZE,
    TimelineEvent,
    _clip_label,
    _projector,
    events_for,
    timeline_strip,
)
from coeftable.theme import DEFAULT


def _events() -> tuple[TimelineEvent, ...]:
    return (
        TimelineEvent(at=3.0, label="price +8% rollout", color="#c33", affects=("aov", "revenue")),
        TimelineEvent(at=8.0, label="spring promo", color="#3c3", affects=("users", "revenue")),
    )


def test_events_reach_only_the_cards_they_affect():
    assert len(events_for(_events(), "revenue")) == 2
    assert len(events_for(_events(), "aov")) == 1
    assert events_for(_events(), "unrelated") == ()


def test_fanned_out_event_keeps_its_coordinate_colour_and_label():
    (event,) = events_for(_events(), "aov")
    assert event.at == 3.0
    assert event.color == "#c33"
    assert event.label == "price +8% rollout"


def test_strip_declares_the_dimensions_it_paints():
    strip = timeline_strip(_events(), x_domain=(0.0, 11.0), width=400, theme=DEFAULT)
    # InlineSvg validates declared-vs-actual on construction, so a mismatch
    # would already have raised. Assert the declared box is what we asked for.
    assert strip.width == 400
    assert strip.height == 96
    assert 'width="400"' in strip.svg


def test_strip_marks_every_event():
    strip = timeline_strip(_events(), x_domain=(0.0, 11.0), width=400, theme=DEFAULT)
    assert strip.svg.count("<circle") == 2
    for event in _events():
        assert event.label in strip.svg
        assert event.color in strip.svg


def test_strip_staggers_consecutive_event_labels_to_different_heights():
    # Scope this to the EVENT labels only. Asserting over every <text> in the
    # strip would also collect tick labels and the title, so the assertion
    # would pass even with no staggering at all.
    strip = timeline_strip(_events(), x_domain=(0.0, 11.0), width=400, theme=DEFAULT)
    ys = [
        fragment.split('y="')[1].split('"')[0]
        for fragment in strip.svg.split("<text")[1:]
        if any(event.label in fragment for event in _events())
    ]
    assert len(ys) == 2
    assert ys[0] != ys[1]


def test_event_rejects_an_empty_affects_list():
    # An event affecting nothing is silently invisible; refuse it.
    with pytest.raises(SpecError, match=r"TimelineEvent.affects must not be empty"):
        TimelineEvent(at=1.0, label="x", color="#000", affects=())


def test_event_rejects_a_non_finite_coordinate():
    with pytest.raises(SpecError, match=r"TimelineEvent.at must be finite"):
        TimelineEvent(at=float("nan"), label="x", color="#000", affects=("a",))


def test_strip_rejects_an_event_outside_the_domain():
    # Placing a pin outside the plotted range would paint outside the declared
    # box and break exact measurement.
    with pytest.raises(SpecError, match="outside"):
        timeline_strip(
            (TimelineEvent(at=99.0, label="x", color="#000", affects=("a",)),),
            x_domain=(0.0, 11.0),
            width=400,
            theme=DEFAULT,
        )


def _event_label_fragments(svg: str) -> list[str]:
    """Isolate the `<text>` fragments belonging to event labels.

    Event labels are the only `<text>` elements with `font-weight="700"` --
    the title uses 600 and tick labels carry no font-weight at all -- so
    this scopes out both without touching the SVG structure.
    """
    return [fragment for fragment in svg.split("<text")[1:] if 'font-weight="700"' in fragment]


def _parse_label_fragment(fragment: str) -> tuple[float, str, str]:
    """Pull `(x, text-anchor, rendered text)` out of one label fragment."""
    x = float(fragment.split(' x="', 1)[1].split('"', 1)[0])
    anchor = fragment.split('text-anchor="', 1)[1].split('"', 1)[0]
    text = html.unescape(fragment.split(">", 1)[1].split("</text>", 1)[0])
    return x, anchor, text


def _label_extent(x: float, anchor: str, text: str) -> tuple[float, float]:
    """Estimated pixel `(left, right)` extent of a label, mirroring the module's approximation."""
    label_width = len(text) * _LABEL_FONT_SIZE * _CHAR_WIDTH_RATIO
    if anchor == "start":
        return x, x + label_width
    if anchor == "end":
        return x - label_width, x
    return x - label_width / 2, x + label_width / 2


def test_strip_keeps_boundary_event_labels_inside_the_declared_width():
    # A centred label at either domain edge would run off the canvas: the
    # projected coordinate sits only `_INSET` px from that edge, well
    # inside half the width of most labels. Boundary events must instead
    # anchor inward, at "start" on the left and "end" on the right.
    width = 400
    events = (
        TimelineEvent(at=0.0, label="quarterly release", color="#c33", affects=("a",)),
        TimelineEvent(at=11.0, label="year-end incident", color="#3c3", affects=("a",)),
    )
    strip = timeline_strip(events, x_domain=(0.0, 11.0), width=width, theme=DEFAULT)
    fragments = _event_label_fragments(strip.svg)
    assert len(fragments) == 2

    parsed = [_parse_label_fragment(fragment) for fragment in fragments]
    for (x, anchor, text), event in zip(parsed, events, strict=True):
        expected_text = f"{event.label} \u00b7 W{int(event.at) + 1}"
        assert text == expected_text  # short enough that no truncation is needed
        left, right = _label_extent(x, anchor, text)
        assert left >= 0
        assert right <= width

    assert parsed[0][1] == "start"  # leftmost event: centring would clip the left edge
    assert parsed[1][1] == "end"  # rightmost event: centring would clip the right edge


def test_strip_truncates_a_label_that_cannot_fit_even_edge_anchored():
    width = _MIN_WIDTH + 16
    event = TimelineEvent(
        at=0.0,
        label="an extremely long release name that will never fit in this strip",
        color="#c33",
        affects=("a",),
    )
    strip = timeline_strip((event,), x_domain=(0.0, 5.0), width=width, theme=DEFAULT)
    (fragment,) = _event_label_fragments(strip.svg)
    x, anchor, text = _parse_label_fragment(fragment)
    full_text = f"{event.label} \u00b7 W1"

    assert anchor == "start"
    assert text != full_text
    assert text.endswith("\u2026")
    left, right = _label_extent(x, anchor, text)
    assert left >= 0
    assert right <= width


def test_strip_anchors_a_both_edge_overflowing_label_to_its_larger_budget():
    # A label long enough to overflow past both edges once centred must
    # anchor toward whichever side has more room, not whichever side the
    # overflow check happens to test first. Placed near the right edge, the
    # leftward ("end") budget dwarfs the rightward ("start") budget, so
    # anchoring "end" preserves far more of the label.
    width = 200
    x_domain = (0.0, 10.0)
    event = TimelineEvent(
        at=9.9,
        label="a release name so long it cannot fit anchored to either edge alone",
        color="#c33",
        affects=("a",),
    )
    project = _projector(x_domain, width, _INSET)
    x = project(event.at)
    full_label = f"{event.label} \u00b7 W{int(event.at) + 1}"
    half = len(full_label) * _LABEL_FONT_SIZE * _CHAR_WIDTH_RATIO / 2
    low, high = _LABEL_HALO, width - _LABEL_HALO
    start_budget, end_budget = high - x, x - low

    # Confirm the fixture actually exercises the both-edges-overflow branch,
    # with a materially larger budget on the "end" side.
    assert x - half < low
    assert x + half > high
    assert end_budget > start_budget

    strip = timeline_strip((event,), x_domain=x_domain, width=width, theme=DEFAULT)
    (fragment,) = _event_label_fragments(strip.svg)
    _, anchor, text = _parse_label_fragment(fragment)

    assert anchor == "end"
    assert text == _clip_label(full_label, max(end_budget, 0.0), _LABEL_FONT_SIZE)

    start_anchored_alternative = _clip_label(full_label, max(start_budget, 0.0), _LABEL_FONT_SIZE)
    assert len(text) > len(start_anchored_alternative)


def test_strip_rejects_a_width_at_or_below_the_minimum():
    pattern = rf"width must be greater than {_MIN_WIDTH}, got {_MIN_WIDTH}"
    with pytest.raises(SpecError, match=pattern):
        timeline_strip(_events(), x_domain=(0.0, 11.0), width=_MIN_WIDTH, theme=DEFAULT)


def test_strip_rejects_a_height_at_or_below_the_minimum():
    with pytest.raises(
        SpecError, match=rf"height must be greater than {_MIN_HEIGHT}, got {_MIN_HEIGHT}"
    ):
        timeline_strip(
            _events(), x_domain=(0.0, 11.0), width=400, height=_MIN_HEIGHT, theme=DEFAULT
        )


def test_strip_projects_pins_to_the_shared_projector_convention():
    x_domain = (0.0, 11.0)
    width = 400
    events = (
        TimelineEvent(at=3.0, label="a", color="#c33", affects=("x",)),
        TimelineEvent(at=8.0, label="b", color="#3c3", affects=("x",)),
    )
    strip = timeline_strip(events, x_domain=x_domain, width=width, theme=DEFAULT)
    project = _projector(x_domain, width, _INSET)
    for event in events:
        x = project(event.at)
        assert f'cx="{x:.2f}" cy=' in strip.svg
        assert f'x1="{x:.2f}" y1=' in strip.svg
        assert f'x2="{x:.2f}" y2=' in strip.svg


def test_dashed_event_keeps_its_dash_through_fan_out_and_render():
    event = TimelineEvent(at=3.0, label="x", color="#c33", affects=("aov",), dash="dashed")

    (fanned,) = events_for((event,), "aov")
    assert fanned.dash == "dashed"

    strip = timeline_strip((event,), x_domain=(0.0, 11.0), width=400, theme=DEFAULT)
    assert f'stroke-dasharray="{_DASH_ARRAY["dashed"]}"' in strip.svg


def test_strip_keeps_multi_digit_boundary_tick_labels_inside_the_declared_width():
    # "W12" centred on the last tick paints past the right edge, so boundary
    # tick labels anchor inward the way event labels do. Interior ticks stay
    # centred, and no centred label may extend beyond the declared box.
    strip = timeline_strip(
        (TimelineEvent(at=5.0, label="mid", color="#c33", affects=("a",)),),
        x_domain=(0.0, 11.0),
        width=400,
        theme=DEFAULT,
    )
    ticks = re.findall(r'<text x="([\d.]+)"[^>]*text-anchor="(\w+)">(W\d+)</text>', strip.svg)
    assert len(ticks) == 12
    assert ticks[-1][1] == "end"
    assert any(anchor == "middle" for _, anchor, _ in ticks)
    for x_text, anchor, label in ticks:
        if anchor != "middle":
            continue
        half = len(label) * _TICK_FONT_SIZE * _CHAR_WIDTH_RATIO / 2
        assert float(x_text) - half >= 0.0
        assert float(x_text) + half <= 400
