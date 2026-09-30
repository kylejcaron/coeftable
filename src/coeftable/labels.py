"""Render user-supplied row/nest labels as safe Markdown.

`great_tables.fmt_markdown` parses with the Markdown parser's unsafe mode, so
a label like ``[x](javascript:alert(1))`` becomes a live link. Labels are user
data, so they are parsed here in safe mode instead. Two things `fmt_markdown`
also provides are reproduced without the unsafe parse:

* great_tables' ``{{m s^-1}}`` units notation. `define_units` parses it and
  `_SafeUnit` assembles the same fixed span/sup/sub markup as
  `UnitDefinition.to_html`, but renders each user-derived leaf in safe mode.
* Row emphasis, generated here outside the parse.

Labels arrive entity-escaped (see `grid._escape_label`), so raw ``<tag>`` text
is inert before it reaches the parser.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from great_tables._gt_data import FormatFns
from great_tables._helpers import (
    UnitDefinition,
    UnitDefinitionList,
    _escape_html_tags,
    _units_html_sub_super,
    _units_symbol_replacements,
    _units_to_subscript,
    _units_to_superscript,
    define_units,
)
from multimark import markdown_to_html, markdown_to_latex

# Same pattern great_tables' `UnitStr.from_str` splits on.
_UNITS_RE = re.compile(r"\{\{(.*?)\}\}")
_LITERAL_TAGS = frozenset({"code", "pre"})


class _Segments(HTMLParser):
    """Split generated HTML into (kind, raw, tag) segments.

    Kinds: ``data`` (character data), ``ref`` (entity/character reference),
    ``open``/``close`` (tags, ``raw`` includes attributes) and ``other``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.segments: list[tuple[str, str, str]] = []

    def handle_data(self, data: str) -> None:
        self.segments.append(("data", data, ""))

    def handle_entityref(self, name: str) -> None:
        self.segments.append(("ref", f"&{name};", ""))

    def handle_charref(self, name: str) -> None:
        self.segments.append(("ref", f"&#{name};", ""))

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.segments.append(("open", self.get_starttag_text() or "", tag))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.segments.append(("other", self.get_starttag_text() or "", tag))

    def handle_endtag(self, tag: str) -> None:
        self.segments.append(("close", f"</{tag}>", tag))

    def handle_comment(self, data: str) -> None:
        self.segments.append(("other", f"<!--{data}-->", ""))


def _segments(markup: str) -> list[tuple[str, str, str]]:
    parser = _Segments()
    parser.feed(markup)
    parser.close()
    return parser.segments


def _map_data(markup: str, fn) -> str:
    return "".join(fn(raw) if kind == "data" else raw for kind, raw, _ in _segments(markup))


def _leaf(text: str) -> str:
    return re.sub(r"^<p>|</p>\n$", "", markdown_to_html(text))


def _leaf_text(text: str) -> str:
    return _leaf(_escape_html_tags(_units_symbol_replacements(text.replace("-", "&minus;"))))


class _SafeUnit(UnitDefinition):
    """`UnitDefinition` whose Markdown leaves are rendered in safe mode.

    Mirrors `UnitDefinition.to_html`, including which leaves great_tables
    treats as plain text (short sub/superscripts) and its x10/chemical rules.
    """

    def to_html(self) -> str:
        if len(self.unit) > 1:
            unit = _leaf_text(self.unit)
        else:
            unit = _leaf(self.unit.replace("-", "&minus;"))
        if "x10" in unit and not self.chemical_formula:
            unit = _map_data(unit, lambda text: text.replace("x", "&times;"))

        def script(text: str | None, wrap) -> str | None:
            if text is None:
                return None
            if len(text) > 2:
                return wrap(_leaf_text(text))
            return wrap(text.replace("-", "&minus;"))

        exponent = script(self.exponent, _units_to_superscript)
        subscript = script(self.unit_subscript, _units_to_subscript)

        if (
            self.sub_super_overstrike
            and self.unit_subscript is not None
            and self.exponent is not None
        ):
            return unit + _units_html_sub_super(
                content_sub=_leaf_text(self.unit_subscript),
                content_sup=_leaf_text(self.exponent),
            )
        if self.chemical_formula:
            return _map_data(
                unit,
                lambda text: re.sub(
                    r"(\d+)",
                    '<span style="white-space:nowrap;">'
                    '<sub style="line-height:0;">\\1</sub></span>',
                    text,
                ),
            )
        return unit + (subscript or "") + (exponent or "")


def _units_to_html(notation: str) -> str:
    definitions = define_units(notation).units_list
    safe: list[UnitDefinition] = [
        _SafeUnit(
            d.token,
            d.unit,
            d.unit_subscript,
            d.exponent,
            d.sub_super_overstrike,
            d.chemical_formula,
        )
        for d in definitions
    ]
    return UnitDefinitionList(safe).to_html()


def _park_units(text: str) -> tuple[str, re.Pattern[str], list[tuple[str, str]]]:
    # Reserve a short ASCII prefix absent from the label, including overlapping
    # lookalikes. Never repeat an attacker-sized literal run in every marker.
    reserved = {match[1] for match in re.finditer(r"(?=q([0-9]+)q)", text, re.IGNORECASE)}
    salt = 0
    while str(salt) in reserved:
        salt += 1
    prefix = f"q{salt}q"
    units: list[tuple[str, str]] = []

    def park(match: re.Match[str]) -> str:
        units.append((_units_to_html(match.group(1)), match.group(0)))
        return f"{prefix}{len(units) - 1}z"

    return _UNITS_RE.sub(park, text), re.compile(f"{prefix}(\\d+)z"), units


def _restore_units(rendered: str, token: re.Pattern[str], units: list[tuple[str, str]]) -> str:
    # Generated markup goes into text nodes only. In code/pre the literal
    # source comes back as text, and inside a tag (e.g. a link target) as an
    # attribute-escaped literal. Sources were entity-escaped with the label,
    # so unescape once before escaping for the target context.
    def generated(match: re.Match[str]) -> str:
        return units[int(match.group(1))][0]

    def literal(match: re.Match[str]) -> str:
        return html.escape(html.unescape(units[int(match.group(1))][1]), quote=True)

    out: list[str] = []
    literal_depth = 0
    for kind, raw, tag in _segments(rendered):
        if kind == "open" and tag in _LITERAL_TAGS:
            literal_depth += 1
        elif kind == "close" and tag in _LITERAL_TAGS:
            literal_depth = max(0, literal_depth - 1)
        if kind == "data":
            out.append(token.sub(literal if literal_depth else generated, raw))
        elif kind in ("open", "other"):
            out.append(token.sub(literal, raw))
        else:
            out.append(raw)
    return "".join(out)


def _label_to_html(text: str, *, bold: bool = False) -> str:
    tokenised, token, units = _park_units(text)
    rendered = _restore_units(_leaf(tokenised), token, units)
    return f"<b>{rendered}</b>" if bold and rendered else rendered


def _label_to_latex(text: str) -> str:
    return markdown_to_latex(text, extensions=["strikethrough"]).rstrip("\n")


def _label_formats(*, bold: bool) -> FormatFns:
    def to_html(text: str) -> str:
        return _label_to_html(text, bold=bold)

    return FormatFns(html=to_html, latex=_label_to_latex, default=to_html)


ROW_LABEL = _label_formats(bold=True)
NEST_LABEL = _label_formats(bold=False)
