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
from coeftable.theme import Role

_ELLIPSIS = "…"
_FIXES = "fixes: wider card, smaller chrome scale, or shorter formatted text"


def _budget(px: float, size: int, ratio: float) -> int:
    """Char budget for `px` at `size`; never below one char + ellipsis."""
    return max(int(px / (ratio * size)), 2)


def _est(text: str, size: int, ratio: float) -> float:
    return len(text) * ratio * size


def _minimum_text_width(text: str, size: int, ratio: float) -> float:
    """Reserve at most two characters, or the content's full width if shorter."""
    return min(len(text), 2) * ratio * size


def _minimum_inline_width(adornment: Adornment, chrome: CardChrome) -> float | None:
    """Return the minimum width needed to keep an adornment legible."""
    if isinstance(adornment, TextBlock):
        size = {
            "title": chrome.title_size,
            "subtitle": chrome.subtitle_size,
            "body": chrome.body_size,
            "caption": chrome.caption_size,
        }[adornment.variant]
        normalized = " ".join(adornment.text.split())
        return _minimum_text_width(normalized, size, chrome.char_width_ratio)
    if isinstance(adornment, KeyValuePopover):
        return _minimum_text_width(adornment.label, chrome.control_size, chrome.char_width_ratio)
    if isinstance(adornment, Badge):
        return 2 * chrome.chip_padding_x + _minimum_text_width(
            adornment.text, chrome.chip_size, chrome.char_width_ratio
        )
    if isinstance(adornment, CaptionRow):
        fixed = 0 if adornment.color is None else chrome.swatch_width + chrome.swatch_gap
        return fixed + _minimum_text_width(
            adornment.text, chrome.caption_size, chrome.char_width_ratio
        )
    if isinstance(adornment, Legend):
        fixed = chrome.legend_swatch + chrome.swatch_gap + chrome.chip_gap
        return sum(
            fixed + _minimum_text_width(label, chrome.caption_size, chrome.char_width_ratio)
            for label, _color in adornment.entries
        )
    if isinstance(adornment, RuleStrip):
        fixed = chrome.swatch_width + chrome.swatch_gap + chrome.chip_gap
        return sum(
            fixed + _minimum_text_width(label, chrome.caption_size, chrome.char_width_ratio)
            for label, _color, _dash in adornment.entries
        )
    if isinstance(adornment, SelectControl):
        # The label gets 40% of usable width less the swatch gap.
        label_minimum = _minimum_text_width(
            adornment.label, chrome.control_size, chrome.char_width_ratio
        )
        return (label_minimum + chrome.swatch_gap) / 0.4
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
    lines: list[tuple[str, bool]] = []
    current = ""
    current_continuation = False
    for word in words:
        word_continuation = False
        while len(word) > budget:
            if current:
                lines.append((current, current_continuation))
                current = ""
            lines.append((word[:budget], word_continuation))
            word = word[budget:]
            word_continuation = True
        if not word:
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= budget:
            if current:
                current = candidate
            else:
                current = word
                current_continuation = word_continuation
        else:
            lines.append((current, current_continuation))
            current = word
            current_continuation = word_continuation
    if current:
        lines.append((current, current_continuation))
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        remainder = "".join(
            ("" if continuation else " ") + line for line, continuation in lines[max_lines:]
        )
        kept[-1] = (kept[-1][0] + remainder, kept[-1][1])
        return tuple(line for line, _continuation in kept)
    return tuple(line for line, _continuation in lines)


@dataclass(frozen=True, slots=True)
class RenderRow:
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


def _metric_row(
    adornment: MetricValue, usable: float, chrome: CardChrome, where: str
) -> RenderRow:
    ratio = chrome.data_char_width_ratio
    value_width = _est(adornment.value, chrome.value_size, ratio)
    width = value_width
    if adornment.detail is not None:
        width += chrome.value_detail_gap + _est(adornment.detail, chrome.ci_size, ratio)
    if width > usable:
        field = "value" if value_width > usable else "detail"
        raise SpecError(
            f"{where}: MetricValue.{field} does not fit: estimated {width:.0f}px in "
            f"{usable:.0f}px usable; {_FIXES}"
        )
    return RenderRow(adornment, line_height(max(chrome.value_size, chrome.ci_size), chrome))


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
) -> tuple[RenderRow, ...]:
    """Resolve a section's adornments into exact render rows."""
    rows: list[RenderRow] = []
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
                        RenderRow(
                            replace(adornment, text=lined, max_lines=1), line_height(size, chrome)
                        )
                    )
            case MetricValue():
                rows.append(_metric_row(adornment, usable, chrome, where))
            case InlineSvg(width=svg_width, height=svg_height):
                if svg_width > usable:
                    raise SpecError(
                        f"{where}: InlineSvg width {svg_width}px exceeds usable "
                        f"{usable}px; {_FIXES}"
                    )
                rows.append(RenderRow(adornment, svg_height))
            case KeyValuePopover():
                rows.append(RenderRow(adornment, line_height(chrome.control_size, chrome)))
            case SelectControl():
                rows.append(
                    RenderRow(
                        adornment,
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
                    RenderRow(
                        replace(adornment, text=_clip(text, budget)),
                        line_height(chrome.chip_size, chrome) + 2 * chrome.chip_padding_y,
                    )
                )
            case CaptionRow():
                rows.append(RenderRow(adornment, line_height(chrome.caption_size, chrome)))
            case Legend(entries=entries):
                fixed = chrome.legend_swatch + chrome.swatch_gap + chrome.chip_gap
                rows.append(
                    RenderRow(
                        replace(adornment, entries=_clip_entries2(entries, fixed, usable, chrome)),
                        line_height(chrome.caption_size, chrome),
                    )
                )
            case RuleStrip(entries=entries):
                fixed = chrome.swatch_width + chrome.swatch_gap + chrome.chip_gap
                rows.append(
                    RenderRow(
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
) -> tuple[MeasuredCard, tuple[RenderRow, ...], tuple[RenderRow, ...], tuple[str, Role] | None]:
    """Measure one card; returns footprints plus the exact rows to render."""
    usable = width - 2 * (chrome.padding + chrome.border_width)
    if usable < 1:
        shell_overhead = 2 * (chrome.padding + chrome.border_width)
        raise SpecError(
            f"card width {width}px leaves {usable}px usable after shell overhead "
            f"{shell_overhead}px; width must leave at least 1px usable; {_FIXES}"
        )
    chip: tuple[str, Role] | None = None
    header_rows: tuple[RenderRow, ...] | None = None
    for adornment in body:
        if isinstance(adornment, MetricValue):
            chip_width = _est(adornment.value, chrome.value_size, chrome.data_char_width_ratio)
            candidate = int(usable - chip_width - chrome.gap)
            if chip_width <= usable / 2 and candidate >= 1:
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
                    chip = (adornment.value, adornment.role)
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
