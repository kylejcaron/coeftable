"""Contract tests for the public Card and CardGrid entry points."""

import re
from dataclasses import replace

import pytest

import coeftable as ct
from coeftable.cards import (
    DEFAULT_CHROME,
    Card,
    CardGrid,
    CardTemplate,
    TextBlock,
)
from coeftable.cards.regions import Metric, resolve_content
from coeftable.errors import SpecError
from coeftable.theme import BLUE, DEFAULT


def _card() -> Card:
    return Card(
        "Revenue",
        content=[Metric(3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ref=0.0)],
        subtitle="weekly lift",
    )


def test_card_matches_equivalent_hand_built_template_byte_for_byte():
    card = _card()
    usable = card.width - 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    template = CardTemplate(
        width=card.width,
        header=(
            TextBlock("Revenue", variant="title"),
            TextBlock("weekly lift", variant="subtitle"),
        ),
        body=resolve_content(
            [Metric(3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ref=0.0)],
            width=usable,
            theme=DEFAULT,
            chrome=DEFAULT_CHROME,
        ),
    )
    assert card.as_raw_html() == template.render(theme=DEFAULT)
    assert card.measure() == template.measure()


def test_repr_html_is_as_raw_html_and_deterministic():
    card = _card()
    assert card._repr_html_() == card.as_raw_html() == card.as_raw_html()


def test_with_theme_recolors_and_returns_a_new_card():
    card = _card()
    themed = card.with_theme(BLUE)
    assert themed is not card
    assert BLUE.favorable in themed.as_raw_html()
    assert BLUE.favorable not in card.as_raw_html()


def test_regions_resolve_exactly_once_per_construction():
    calls = []

    class Counting:
        def resolve(self, *, width, theme, chrome):
            calls.append(theme.favorable)
            return (TextBlock("resolved"),)

    card = Card("t", content=[Counting()])
    card.as_raw_html()
    card.as_raw_html()
    card.measure()
    assert len(calls) == 1
    card.with_theme(BLUE)
    assert len(calls) == 2  # replace() re-resolves under the new theme
    assert calls[1] == BLUE.favorable


def test_chrome_overrides_propagate_to_regions_measurement_and_html():
    widths = []

    class Recording:
        def resolve(self, *, width, theme, chrome):
            widths.append(width)
            return (TextBlock("resolved"),)

    chrome = replace(DEFAULT_CHROME, padding=24, title_size=20)
    card = Card("t", content=[Recording()], chrome=chrome)
    assert widths == [card.width - 2 * (24 + chrome.border_width)]

    default = Card("t", content=[Recording()])
    assert card.measure().collapsed_height != default.measure().collapsed_height
    assert card.measure().expanded_height != default.measure().expanded_height

    html_out = card.as_raw_html()
    assert "padding:24px 24px 0 24px" in html_out
    assert "font-size:20px" in html_out


def test_region_errors_surface_at_card_construction():
    with pytest.raises(SpecError):
        Card("t", content=[Metric(123456789.123, ct.Number())], width=90)


@pytest.mark.parametrize(
    "build",
    [
        lambda: Card(""),
        lambda: Card(7),  # ty: ignore[invalid-argument-type]
        lambda: Card("t", subtitle=7),  # ty: ignore[invalid-argument-type]
        lambda: Card("t", width=True),
        lambda: Card("t", width=-1),
        lambda: Card("t", chrome="chrome"),  # ty: ignore[invalid-argument-type]
        lambda: Card("t", theme="theme"),  # ty: ignore[invalid-argument-type]
        lambda: Card("t", content="text"),  # ty: ignore[invalid-argument-type]
        lambda: Card("t", content=[object()]),  # ty: ignore[invalid-argument-type]
    ],
    ids=[
        "empty-title",
        "nonstr-title",
        "nonstr-subtitle",
        "bool-width",
        "negative-width",
        "bad-chrome",
        "bad-theme",
        "str-content",
        "invalid-content-item",
    ],
)
def test_card_validation(build):
    with pytest.raises(SpecError):
        build()


def test_grid_wraps_each_card_in_a_measured_fixed_basis_item():
    a, b = _card(), Card("Latency", width=280)
    html_out = CardGrid([a, b], gap=20).as_raw_html()
    assert html_out.startswith('<div style="display:flex;flex-wrap:wrap;gap:20px;')
    assert "align-items:flex-start" in html_out
    ma, mb = a.measure(), b.measure()
    assert f"flex:0 0 {ma.width}px" in html_out
    assert f"height:{ma.expanded_height}px" in html_out
    assert f"flex:0 0 {mb.width}px" in html_out
    assert html_out.index("Revenue") < html_out.index("Latency")
    assert re.search(r"\bid=", html_out) is None


def test_grid_repr_html_and_mixed_themes():
    grid = CardGrid([_card(), _card().with_theme(BLUE)])
    html_out = grid._repr_html_()
    assert html_out == grid.as_raw_html()
    assert DEFAULT.favorable in html_out and BLUE.favorable in html_out


@pytest.mark.parametrize(
    "build",
    [
        lambda: CardGrid([]),
        lambda: CardGrid([_card()], gap=0),
        lambda: CardGrid([_card()], gap=True),
        lambda: CardGrid([_card(), "card"]),  # ty: ignore[invalid-argument-type]
        lambda: CardGrid("cards"),  # ty: ignore[invalid-argument-type]
    ],
    ids=["empty", "zero-gap", "bool-gap", "non-card-item", "str-cards"],
)
def test_grid_validation(build):
    with pytest.raises(SpecError):
        build()
