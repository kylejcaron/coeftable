"""The card shell: one measured border box rendered from resolved rows.

`render()` and `measure()` walk the same rows from `measure_card`, so the
pinned heights in the HTML are the measured heights by construction. The
shell is a native `<details>`: expanded height is reserved by layout even
when a card starts folded (zero-JS cannot reflow).
"""

from __future__ import annotations

from dataclasses import dataclass

from coeftable.cards.adornments import (
    Adornment,
    InlineSvg,
    KeyValuePopover,
    SelectControl,
)
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome, line_height
from coeftable.cards.fragments import _esc, render_adornment
from coeftable.cards.measure import MeasuredCard, Row, measure_card
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT, Theme


@dataclass(frozen=True, slots=True)
class CardTemplate:
    """An arrangement of adornments at a declared width and chrome."""

    width: int
    header: tuple[Adornment, ...]
    body: tuple[Adornment, ...] = ()
    chrome: CardChrome = DEFAULT_CHROME

    def __post_init__(self) -> None:
        """Validate shell inputs through the shared measurement path."""
        if isinstance(self.width, bool) or not isinstance(self.width, int):
            raise SpecError("CardTemplate.width must be an int")
        if not isinstance(self.header, tuple) or not isinstance(self.body, tuple):
            raise SpecError("CardTemplate.header and .body must be tuples")
        if not self.header:
            raise SpecError("CardTemplate.header must not be empty")
        for index, adornment in enumerate(self.header):
            if isinstance(adornment, (SelectControl, KeyValuePopover)):
                raise SpecError(
                    f"header[{index}]: interactive adornments are invalid inside "
                    "<summary>; move it to body"
                )
        self.measure()

    def measure(self) -> MeasuredCard:
        """Return the reserved border-box footprint for this card."""
        measured, _, _, _ = measure_card(
            width=self.width, header=self.header, body=self.body, chrome=self.chrome
        )
        return measured

    def render(self, *, theme: Theme = DEFAULT) -> str:
        """Render the pinned-box shell for this card."""
        chrome = self.chrome
        measured, header_rows, body_rows, chip = measure_card(
            width=self.width, header=self.header, body=self.body, chrome=chrome
        )
        summary_content = measured.header_height - chrome.border_width - chrome.padding
        header_html = "".join(_wrap(row, theme, chrome) for row in header_rows)
        chip_html = ""
        if chip is not None:
            chip_lh = line_height(chrome.value_size, chrome)
            chip_html = (
                f'<span style="font-size:{chrome.value_size}px;'
                f"line-height:{chip_lh}px;font-weight:600;white-space:nowrap;"
                f'color:{_esc(theme.text)}">{_esc(chip)}</span>'
            )
        body_html = "".join(_wrap(row, theme, chrome) for row in body_rows)
        body_block = (
            ""
            if not body_rows
            else (
                f'<div style="box-sizing:border-box;margin:0;'
                f"padding:{chrome.header_gap}px {chrome.padding}px "
                f'0 {chrome.padding}px">{body_html}</div>'
            )
        )
        return (
            f'<details open style="box-sizing:border-box;width:{self.width}px;'
            f"margin:0;padding:0 0 {chrome.padding}px 0;"
            f"border:{chrome.border_width}px solid {_esc(theme.rule)};"
            f"border-radius:{chrome.radius}px;background:{_esc(theme.surface)};"
            f'overflow:hidden">'
            f'<summary style="display:flex;list-style:none;margin:0;'
            f"justify-content:space-between;align-items:baseline;"
            f"padding:{chrome.padding}px {chrome.padding}px 0 {chrome.padding}px;"
            f'height:{summary_content}px;cursor:pointer">'
            f"<div>{header_html}</div>{chip_html}</summary>"
            f"{body_block}</details>"
        )


def _wrap(row: Row, theme: Theme, chrome: CardChrome) -> str:
    """Render one exact-height row, preserving measurement-owned spacing."""
    gap = f";margin-top:{row.gap_above}px" if row.gap_above else ""
    svg_containment = ";line-height:0" if isinstance(row.adornment, InlineSvg) else ""
    return (
        f'<div style="height:{row.height}px;overflow:hidden;margin:0'
        f'{gap}{svg_containment}">'
        f"{render_adornment(row.adornment, theme=theme, chrome=chrome)}</div>"
    )
