"""Geometry-neutral Card appearance values."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from coeftable.errors import SpecError
from coeftable.theme import Theme

type CardBorder = Literal["default", "dashed", "strong"]
type CardFill = Literal["surface", "transparent"]
type CardEmphasis = Literal["default", "muted"]

_BORDERS: tuple[CardBorder, ...] = ("default", "dashed", "strong")
_FILLS: tuple[CardFill, ...] = ("surface", "transparent")
_EMPHASES: tuple[CardEmphasis, ...] = ("default", "muted")


@dataclass(frozen=True, slots=True)
class CardAppearance:
    """Paint-only styling for a `Card`: never affects measured geometry."""

    border: CardBorder = "default"
    fill: CardFill = "surface"
    emphasis: CardEmphasis = "default"

    def __post_init__(self) -> None:
        """Validate every field is a recognised appearance member."""
        if self.border not in _BORDERS:
            raise SpecError("CardAppearance.border must be default, dashed, or strong")
        if self.fill not in _FILLS:
            raise SpecError("CardAppearance.fill must be surface or transparent")
        if self.emphasis not in _EMPHASES:
            raise SpecError("CardAppearance.emphasis must be default or muted")


def appearance_theme(theme: Theme, appearance: CardAppearance) -> Theme:
    """Return `theme` rebound for `appearance` (muted emphasis dims every colour role)."""
    if appearance.emphasis == "default":
        return theme
    muted = theme.muted
    return replace(
        theme,
        favorable=muted,
        unfavorable=muted,
        inconclusive=muted,
        neutral=muted,
        axis=muted,
        text=muted,
    )


DEFAULT_APPEARANCE = CardAppearance()

__all__ = ["DEFAULT_APPEARANCE", "CardAppearance"]
