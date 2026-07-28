import dataclasses

import pytest

from coeftable.theme import COLORBLIND, DEFAULT, MONO, Theme, role_for


@pytest.mark.parametrize(
    ("lower", "upper", "direction", "expected"),
    [
        (1.0, 2.0, "higher_is_better", "favorable"),
        (1.0, 2.0, "lower_is_better", "unfavorable"),
        (-2.0, -1.0, "higher_is_better", "unfavorable"),
        (-2.0, -1.0, "lower_is_better", "favorable"),
        (-1.0, 1.0, "higher_is_better", "inconclusive"),
        (-1.0, 1.0, "lower_is_better", "inconclusive"),
        (1.0, 2.0, "neutral", "neutral"),
        (-1.0, 1.0, "neutral", "neutral"),
    ],
)
def test_role_for_respects_direction(lower, upper, direction, expected):
    assert role_for(lower, upper, 0.0, direction) == expected


def test_interval_touching_reference_is_inconclusive():
    assert role_for(0.0, 2.0, 0.0, "higher_is_better") == "inconclusive"
    assert role_for(-2.0, 0.0, 0.0, "higher_is_better") == "inconclusive"


def test_one_sided_intervals_resolve():
    assert role_for(1.0, None, 0.0, "higher_is_better") == "favorable"
    assert role_for(None, -1.0, 0.0, "higher_is_better") == "unfavorable"
    assert role_for(None, None, 0.0, "higher_is_better") == "inconclusive"


def test_reference_other_than_zero():
    assert role_for(1.1, 1.5, 1.0, "higher_is_better") == "favorable"
    assert role_for(0.5, 0.9, 1.0, "higher_is_better") == "unfavorable"


def test_color_returns_the_slot_for_each_role():
    for role in ("favorable", "unfavorable", "inconclusive", "neutral"):
        assert DEFAULT.color(role).startswith("#")


def test_color_raises_on_unknown_role():
    with pytest.raises(ValueError, match="Unknown role"):
        DEFAULT.color("bogus")  # ty: ignore[invalid-argument-type]


def test_mono_encodes_no_significance():
    colors = {MONO.color(r) for r in ("favorable", "unfavorable", "inconclusive", "neutral")}
    assert len(colors) == 1


def test_colorblind_separates_favorable_from_unfavorable():
    assert COLORBLIND.color("favorable") != COLORBLIND.color("unfavorable")


def test_theme_is_frozen_and_replaceable():
    custom = dataclasses.replace(DEFAULT, favorable="#123456")
    assert custom.color("favorable") == "#123456"
    assert DEFAULT.color("favorable") != "#123456"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(DEFAULT, "favorable", "#000000")  # noqa: B010  -- opaque to ty so it doesn't flag the frozen-dataclass assignment


def test_theme_is_hashable():
    assert isinstance(hash(Theme()), int)
