import pytest

from coeftable.errors import SpecError
from coeftable.graph.timeline import TimelineEvent, events_for, timeline_strip
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
