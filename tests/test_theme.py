import dataclasses

import pytest

from coeftable.theme import BLUE, COLORBLIND, DEFAULT, MONO, TEXTUAL, Theme, role_for


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


def test_role_for_ref_none_is_neutral_regardless_of_interval_or_direction():
    assert role_for(1.0, 2.0, None, "higher_is_better") == "neutral"
    assert role_for(None, -1.0, None, "lower_is_better") == "neutral"


def test_color_returns_the_slot_for_each_role():
    for role in ("favorable", "unfavorable", "inconclusive", "neutral"):
        assert DEFAULT.color(role).startswith("#")


def test_color_raises_on_unknown_role():
    with pytest.raises(ValueError, match="Unknown role"):
        DEFAULT.color("bogus")  # ty: ignore[invalid-argument-type]


def _luminance(hex_color: str) -> int:
    """Sum of RGB channels; lower means visually darker."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return r + g + b


def test_mono_shades_significant_results_darker():
    # Favorable and unfavorable share a shade (MONO never colour-codes
    # direction), but that shade is darker than inconclusive's, and
    # neutral sits between the two.
    assert MONO.color("favorable") == MONO.color("unfavorable")
    assert _luminance(MONO.color("favorable")) < _luminance(MONO.color("neutral"))
    assert _luminance(MONO.color("neutral")) < _luminance(MONO.color("inconclusive"))


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


def test_builtin_themes_except_textual_are_boxed():
    assert BLUE.border_style == "boxed"
    assert COLORBLIND.border_style == "boxed"
    assert MONO.border_style == "boxed"


def test_textual_is_minimal_border():
    assert TEXTUAL.border_style == "minimal"


def test_textual_disables_row_banding():
    # A publication-style table has no zebra striping: band matches surface.
    assert TEXTUAL.band == TEXTUAL.surface


def test_textual_uses_a_muted_palette():
    assert TEXTUAL.color("favorable") != BLUE.color("favorable")
    assert TEXTUAL.color("unfavorable") != BLUE.color("unfavorable")


def test_textual_axis_labels_are_legible():
    # Forest-plot xtick labels render at a small font size against a white
    # background; they must be at least as dark as BLUE's axis colour.
    assert _luminance(TEXTUAL.axis) <= _luminance(BLUE.axis)


def test_textual_border_color_is_decoupled_from_header_bg():
    # header_bg stays a light title banner; border_color independently
    # drives every structural rule (table frame, table body, column
    # labels, row groups) so they stay visible against the light banner.
    assert TEXTUAL.border_color is not None
    assert TEXTUAL.border_color != TEXTUAL.header_bg
    assert _luminance(TEXTUAL.border_color) < _luminance(TEXTUAL.header_bg)


def test_other_themes_have_no_border_color_override():
    assert BLUE.border_color is None
    assert COLORBLIND.border_color is None
    assert MONO.border_color is None
