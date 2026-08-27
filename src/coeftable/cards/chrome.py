"""Card geometry and type scale: the single source measure and render share.

Colors live in `Theme`; every px that affects a measured card box lives
here. A geometry value read by only one of measure/render is a defect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

from coeftable.errors import SpecError


@dataclass(frozen=True, slots=True)
class CardChrome:
    """Numeric card geometry (px) and typographic scale."""

    padding: int = 16
    gap: int = 8
    radius: int = 12
    border_width: int = 1
    header_gap: int = 10
    char_width_ratio: float = 0.6
    data_char_width_ratio: float = 0.75
    leading: float = 1.3
    title_size: int = 14
    subtitle_size: int = 12
    body_size: int = 12
    caption_size: int = 11
    value_size: int = 15
    ci_size: int = 11
    control_size: int = 11
    chip_size: int = 10
    select_padding: int = 6
    chip_padding_x: int = 8
    chip_padding_y: int = 1
    swatch_width: int = 14
    swatch_thickness: int = 2
    legend_swatch: int = 8
    swatch_gap: int = 4
    chip_gap: int = 10
    value_detail_gap: int = 4
    callout_accent: int = 3
    callout_inset: int = 6

    def __post_init__(self) -> None:
        """Validate all geometry fields."""
        float_fields = {"char_width_ratio", "data_char_width_ratio", "leading"}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in float_fields:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise SpecError(f"CardChrome.{field.name} must be a finite float")
                if field.name == "leading":
                    valid_range = 1.0 <= value <= 3.0
                else:
                    valid_range = 0.0 < value <= 3.0
                if not valid_range:
                    bound = "[1, 3]" if field.name == "leading" else "(0, 3]"
                    raise SpecError(f"CardChrome.{field.name} must be in {bound}")
            else:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise SpecError(f"CardChrome.{field.name} must be an int")
                if value <= 0 and field.name not in ("border_width", "chip_padding_y"):
                    raise SpecError(f"CardChrome.{field.name} must be positive")
                if value < 0:
                    raise SpecError(f"CardChrome.{field.name} must be non-negative")

        if self.swatch_thickness > self.caption_size:
            raise SpecError("CardChrome.swatch_thickness must be <= caption_size")
        if self.legend_swatch > self.caption_size:
            raise SpecError("CardChrome.legend_swatch must be <= caption_size")


def line_height(size: int, chrome: CardChrome) -> int:
    """Exact per-line pixel height: ceil(size * leading)."""
    return math.ceil(size * chrome.leading)


DEFAULT_CHROME = CardChrome()
