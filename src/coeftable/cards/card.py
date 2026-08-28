"""The public card entry points: `Card` and `CardGrid`.

Thin sugar over templates and regions: a `Card` resolves its content
exactly once at construction into a cached template, so every validation
error surfaces immediately and rendering is pure reads. A `CardGrid` is a
flex-wrap row of fixed-basis items sized to each card's measured
footprint — narrow containers cannot shrink cards and folding one card
never moves its siblings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from coeftable.cards.adornments import Adornment, SelectControl, TextBlock
from coeftable.cards.appearance import DEFAULT_APPEARANCE, CardAppearance, appearance_theme
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.cards.measure import MeasuredCard
from coeftable.cards.regions import Region, _canonical, resolve_content
from coeftable.cards.template import CardTemplate
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT, Theme


@dataclass(frozen=True, slots=True)
class Card:
    """A measured, foldable metric card built from regions and adornments."""

    title: str
    content: Sequence[Region | Adornment] = ()
    subtitle: str | None = None
    width: int = 256
    chrome: CardChrome = DEFAULT_CHROME
    theme: Theme = DEFAULT
    appearance: CardAppearance = DEFAULT_APPEARANCE
    _template: CardTemplate = field(init=False, repr=False, compare=False)
    _control_options: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate inputs and build the cached template once."""
        if not isinstance(self.title, str) or not self.title:
            raise SpecError("Card.title must be a non-empty str")
        if self.subtitle is not None and not isinstance(self.subtitle, str):
            raise SpecError("Card.subtitle must be a str")
        if isinstance(self.width, bool) or not isinstance(self.width, int):
            raise SpecError("Card.width must be an int")
        if self.width <= 0:
            raise SpecError("Card.width must be positive")
        if not isinstance(self.chrome, CardChrome):
            raise SpecError("Card.chrome must be a CardChrome")
        if not isinstance(self.theme, Theme):
            raise SpecError("Card.theme must be a Theme")
        if not isinstance(self.appearance, CardAppearance):
            raise SpecError("Card.appearance must be a CardAppearance")
        object.__setattr__(self, "content", _canonical(self.content, name="Card.content"))
        usable = self.width - 2 * (self.chrome.padding + self.chrome.border_width)
        header: tuple[Adornment, ...] = (TextBlock(self.title, variant="title"),)
        if self.subtitle is not None:
            header = (*header, TextBlock(self.subtitle, variant="subtitle"))
        resolved_theme = appearance_theme(self.theme, self.appearance)
        body = resolve_content(
            self.content,
            width=usable,
            theme=resolved_theme,
            chrome=self.chrome,
        )
        template = CardTemplate(width=self.width, header=header, body=body, chrome=self.chrome)
        if self.appearance.emphasis == "muted":
            base_body = resolve_content(
                self.content,
                width=usable,
                theme=self.theme,
                chrome=self.chrome,
            )
            base_template = CardTemplate(
                width=self.width,
                header=header,
                body=base_body,
                chrome=self.chrome,
            )
            if base_template.measure() != template.measure():
                raise SpecError("Card.appearance emphasis must not change Region geometry")
        control_options: dict[str, tuple[str, ...]] = {}
        for adornment in body:
            if isinstance(adornment, SelectControl) and adornment.key is not None:
                if adornment.key in control_options:
                    raise SpecError(f"duplicate SelectControl.key {adornment.key!r} in card")
                control_options[adornment.key] = tuple(value for value, _ in adornment.options)
        object.__setattr__(self, "_control_options", MappingProxyType(control_options))
        object.__setattr__(self, "_template", template)

    def measure(self) -> MeasuredCard:
        """Return this card's exact reserved footprints."""
        return self._template.measure()

    def as_raw_html(self, *, control_dom_ids: Mapping[str, str] | None = None) -> str:
        """Render the card as a self-contained HTML string."""
        return self._template.render(
            theme=self.theme, appearance=self.appearance, control_dom_ids=control_dom_ids
        )

    def control_options(self) -> Mapping[str, tuple[str, ...]]:
        """Return keyed select option values resolved for this card."""
        return self._control_options

    def _repr_html_(self) -> str:
        return self.as_raw_html()

    def with_theme(self, theme: Theme) -> Card:
        """Return a copy bound to `theme` (content re-resolves under it)."""
        return replace(self, theme=theme)


@dataclass(frozen=True, slots=True)
class CardGrid:
    """An edge-less flex-wrap arrangement of independently measured cards."""

    cards: Sequence[Card]
    gap: int = 16

    def __post_init__(self) -> None:
        """Canonicalize and validate the grid inputs."""
        object.__setattr__(self, "cards", _canonical(self.cards, name="CardGrid.cards"))
        if not self.cards:
            raise SpecError("CardGrid.cards must not be empty")
        for index, card in enumerate(self.cards):
            if not isinstance(card, Card):
                raise SpecError(f"CardGrid.cards[{index}] must be a Card")
        if isinstance(self.gap, bool) or not isinstance(self.gap, int) or self.gap <= 0:
            raise SpecError("CardGrid.gap must be a positive int")

    def as_raw_html(self) -> str:
        """Render every card inside a fixed-basis flex-wrap container."""
        items = []
        for card in self.cards:
            measured = card.measure()
            items.append(
                f'<div style="flex:0 0 {measured.width}px;'
                f"min-width:{measured.width}px;"
                f"height:{measured.expanded_height}px;"
                f'overflow:visible">{card.as_raw_html()}</div>'
            )
        return (
            f'<div style="display:flex;flex-wrap:wrap;gap:{self.gap}px;'
            f'align-items:flex-start">{"".join(items)}</div>'
        )

    def _repr_html_(self) -> str:
        return self.as_raw_html()
