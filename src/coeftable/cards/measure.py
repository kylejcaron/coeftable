"""Exact card measurement: resolved render rows and reserved footprints.

Pure arithmetic over `CardChrome`. Returns the exact rows the template
renders, so measured and rendered content agree by construction. Label
text ellipsizes to its budget; data fields (`MetricValue`) reject with
`SpecError` instead — truncating a number lies about data. That rejection
uses a conservative width estimate (`data_char_width_ratio`), so it fires
early for typical numerals; rendered rows are fixed-height and clip rather than
grow; rendered-fixture parity is verified outside the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from coeftable.cards.adornments import (
    Adornment,
    Badge,
    CaptionRow,
    InlineSvg,
    KeyValuePopover,
    Legend,
    MetricValue,
    RuleStrip,
    SelectControl,
    TextBlock,
)
from coeftable.cards.chrome import CardChrome, line_height
from coeftable.errors import SpecError

_ELLIPSIS = "…"
_FIXES = "fixes: wider card, smaller chrome scale, or shorter formatted text"


def _budget(px: float, size: int, ratio: float) -> int:
    """Char budget for `px` at `size`; never below one char + ellipsis."""
    return max(int(px / (ratio * size)), 2)


def _est(text: str, size: int, ratio: float) -> float:
    return len(text) * ratio * size


def _minimum_inline_width(adornment: Adornment, chrome: CardChrome) -> float | None:
    """Return the minimum width needed to keep an adornment legible."""
    text_budget = 2 * chrome.char_width_ratio
    if isinstance(adornment, Badge):
        return 2 * chrome.chip_padding_x + text_budget * chrome.chip_size
    if isinstance(adornment, CaptionRow):
        fixed = 0 if adornment.color is None else chrome.swatch_width + chrome.swatch_gap
        return fixed + text_budget * chrome.caption_size
    if isinstance(adornment, Legend):
        fixed = chrome.legend_swatch + chrome.swatch_gap + chrome.chip_gap
        return len(adornment.entries) * (fixed + text_budget * chrome.caption_size)
    if isinstance(adornment, RuleStrip):
        fixed = chrome.swatch_width + chrome.swatch_gap + chrome.chip_gap
        return len(adornment.entries) * (fixed + text_budget * chrome.caption_size)
    if isinstance(adornment, SelectControl):
        # The label keeps its existing half-width allocation.
        return 2 * text_budget * chrome.control_size
    return None


def _check_minimum_inline_width(
    adornment: Adornment, *, usable: int, chrome: CardChrome, where: str
) -> None:
    required = _minimum_inline_width(adornment, chrome)
    if required is not None and required > usable:
        raise SpecError(
            f"{where}: {type(adornment).__name__} requires at least {required:.1f}px, "
            f"but only {usable}px available; {_FIXES}"
        )


def _clip(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    return text[: budget - 1] + _ELLIPSIS


def text_line_plan(text: str, *, budget: int, max_lines: int) -> tuple[str, ...]:
    """Resolve text into the exact lines the template will render."""
    words = text.split()
    if not words:
        return ("",)
    lines: list[str] = []
    current = ""
    for word in words:
        while len(word) > budget:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:budget])
            word = word[budget:]
        if not word:
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= budget:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = _clip(kept[-1] + " " + lines[max_lines], budget)
        return tuple(kept)
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class Row:
    """One resolved render row: the adornment to render and its exact height."""

    adornment: Adornment
    height: int
    gap_above: int = 0


@dataclass(frozen=True, slots=True)
class Anchor:
    """A named wire attachment point relative to the measured border box."""

    name: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class MeasuredCard:
    """Border-box footprints layout can reserve without re-measuring."""

    width: int
    expanded_height: int
    collapsed_height: int
    header_height: int
    anchors: tuple[Anchor, ...]


def _metric_row(adornment: MetricValue, usable: float, chrome: CardChrome) -> Row:
    ratio = chrome.data_char_width_ratio
    width = _est(adornment.value, chrome.value_size, ratio)
    if adornment.detail is not None:
        width += chrome.value_detail_gap + _est(adornment.detail, chrome.ci_size, ratio)
    if width > usable:
        raise SpecError(
            f"MetricValue.value does not fit: estimated {width:.0f}px in "
            f"{usable:.0f}px usable; {_FIXES}"
        )
    return Row(adornment, line_height(max(chrome.value_size, chrome.ci_size), chrome))


def _clip_entries2(
    entries: tuple[tuple[str, str], ...], fixed: float, usable: float, chrome: CardChrome
) -> tuple[tuple[str, str], ...]:
    share = max((usable / len(entries)) - fixed, 1.0)
    budget = _budget(share, chrome.caption_size, chrome.char_width_ratio)
    return tuple((_clip(label, budget), color) for label, color in entries)


def _clip_entries3(
    entries: tuple[tuple[str, str, str], ...],
    fixed: float,
    usable: float,
    chrome: CardChrome,
) -> tuple[tuple[str, str, str], ...]:
    share = max((usable / len(entries)) - fixed, 1.0)
    budget = _budget(share, chrome.caption_size, chrome.char_width_ratio)
    return tuple((_clip(label, budget), color, dash) for label, color, dash in entries)


def resolve_rows(
    adornments: tuple[Adornment, ...],
    *,
    usable: int,
    chrome: CardChrome,
    section: str,
) -> tuple[Row, ...]:
    """Resolve a section's adornments into exact render rows."""
    rows: list[Row] = []
    for index, adornment in enumerate(adornments):
        row_start = len(rows)
        where = f"{section}[{index}]"
        _check_minimum_inline_width(adornment, usable=usable, chrome=chrome, where=where)
        match adornment:
            case TextBlock(text=text, variant=variant, max_lines=max_lines):
                size = {
                    "title": chrome.title_size,
                    "subtitle": chrome.subtitle_size,
                    "body": chrome.body_size,
                    "caption": chrome.caption_size,
                }[variant]
                budget = _budget(usable, size, chrome.char_width_ratio)
                for lined in text_line_plan(text, budget=budget, max_lines=max_lines):
                    rows.append(
                        Row(replace(adornment, text=lined, max_lines=1), line_height(size, chrome))
                    )
            case MetricValue():
                rows.append(_metric_row(adornment, usable, chrome))
            case InlineSvg(width=svg_width, height=svg_height):
                if svg_width > usable:
                    raise SpecError(
                        f"{where}: InlineSvg width {svg_width}px exceeds usable "
                        f"{usable}px; {_FIXES}"
                    )
                rows.append(Row(adornment, svg_height))
            case KeyValuePopover(label=label):
                budget = _budget(usable, chrome.control_size, chrome.char_width_ratio)
                rows.append(
                    Row(
                        replace(adornment, label=_clip(label, budget)),
                        line_height(chrome.control_size, chrome),
                    )
                )
            case SelectControl(label=label):
                budget = _budget(usable / 2, chrome.control_size, chrome.char_width_ratio)
                rows.append(
                    Row(
                        replace(adornment, label=_clip(label, budget)),
                        line_height(chrome.control_size, chrome) + chrome.select_padding,
                    )
                )
            case Badge(text=text):
                budget = _budget(
                    usable - 2 * chrome.chip_padding_x,
                    chrome.chip_size,
                    chrome.char_width_ratio,
                )
                rows.append(
                    Row(
                        replace(adornment, text=_clip(text, budget)),
                        line_height(chrome.chip_size, chrome) + 2 * chrome.chip_padding_y,
                    )
                )
            case CaptionRow(text=text, color=color):
                fixed = 0 if color is None else chrome.swatch_width + chrome.swatch_gap
                budget = _budget(usable - fixed, chrome.caption_size, chrome.char_width_ratio)
                rows.append(
                    Row(
                        replace(adornment, text=_clip(text, budget)),
                        line_height(chrome.caption_size, chrome),
                    )
                )
            case Legend(entries=entries):
                fixed = chrome.legend_swatch + chrome.swatch_gap + chrome.chip_gap
                rows.append(
                    Row(
                        replace(adornment, entries=_clip_entries2(entries, fixed, usable, chrome)),
                        line_height(chrome.caption_size, chrome),
                    )
                )
            case RuleStrip(entries=entries):
                fixed = chrome.swatch_width + chrome.swatch_gap + chrome.chip_gap
                rows.append(
                    Row(
                        replace(adornment, entries=_clip_entries3(entries, fixed, usable, chrome)),
                        line_height(chrome.caption_size, chrome),
                    )
                )
            case _:
                raise SpecError(f"{where}: unmeasurable adornment {adornment!r}")
        if index and len(rows) > row_start:
            rows[row_start] = replace(rows[row_start], gap_above=chrome.gap)
    return tuple(rows)


def measure_card(
    *,
    width: int,
    header: tuple[Adornment, ...],
    body: tuple[Adornment, ...],
    chrome: CardChrome,
) -> tuple[MeasuredCard, tuple[Row, ...], tuple[Row, ...], str | None]:
    """Measure one card; returns footprints plus the exact rows to render."""
    usable = width - 2 * (chrome.padding + chrome.border_width)
    if usable < 2 * chrome.body_size:
        raise SpecError(f"card width {width}px leaves {usable}px usable; too narrow; {_FIXES}")
    chip: str | None = None
    header_rows: tuple[Row, ...] | None = None
    for adornment in body:
        if isinstance(adornment, MetricValue):
            chip_width = _est(adornment.value, chrome.value_size, chrome.data_char_width_ratio)
            candidate = int(usable - chip_width - chrome.gap)
            title_budget = 2 * chrome.char_width_ratio * chrome.title_size
            if chip_width <= usable / 2 and candidate >= title_budget:
                try:
                    header_rows = resolve_rows(
                        header,
                        usable=candidate,
                        chrome=chrome,
                        section="header",
                    )
                except SpecError:
                    pass
                else:
                    chip = adornment.value
            break
    if header_rows is None:
        header_rows = resolve_rows(header, usable=usable, chrome=chrome, section="header")
    body_rows = resolve_rows(body, usable=usable, chrome=chrome, section="body")

    header_stack = sum(r.height + r.gap_above for r in header_rows)
    chip_height = 0 if chip is None else line_height(chrome.value_size, chrome)
    summary_content = max(header_stack, chip_height)
    header_height = chrome.border_width + chrome.padding + summary_content
    collapsed = header_height + chrome.padding + chrome.border_width
    body_stack = sum(r.height + r.gap_above for r in body_rows)
    expanded = (
        collapsed
        if not body_rows
        else (
            header_height + chrome.header_gap + body_stack + chrome.padding + chrome.border_width
        )
    )
    measured = MeasuredCard(
        width=width,
        expanded_height=expanded,
        collapsed_height=collapsed,
        header_height=header_height,
        anchors=(
            Anchor("in", width / 2, 0.0),
            Anchor("out", width / 2, header_height / 2),
        ),
    )
    return measured, header_rows, body_rows, chip
