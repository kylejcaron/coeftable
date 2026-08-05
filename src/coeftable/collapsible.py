"""Post-process `great_tables` HTML to make row-group sections collapsible.

`make_collapsible` is a pure string transform: it knows nothing about
`CoefTable`. It walks the rendered `<tbody>`, tags each group heading row and
its member rows with `data-ct-group*` attributes, and appends a `<style>`
block whose `:has()` rules do the collapsing -- no JavaScript.
"""

from __future__ import annotations

import re

_TBODY_OPEN_RE = re.compile(r'<tbody\s+class="gt_table_body"[^>]*>')
_WRAPPER_DIV_ID_RE = re.compile(r'<div\s+id="([^"]+)"')
_ROW_TOKEN_RE = re.compile(r"<tr(?=[\s>])|</tr>")
_GROUP_HEADING_TH_RE = re.compile(r'(<th\s+class="gt_group_heading"[^>]*>)(.*?)(</th>)', re.DOTALL)

_BASE_CSS = """\
#{uid} .ct-group-state{{
  position:absolute;width:1px;height:1px;overflow:hidden;
  clip-path:inset(50%);white-space:nowrap
}}
#{uid} label.ct-group-toggle{{display:block;cursor:pointer}}
#{uid} .ct-caret{{display:inline-block;width:1em}}
#{uid} .ct-group-state:focus-visible + label.ct-group-toggle{{
  outline:2px solid currentColor;outline-offset:2px
}}
/* per group n: */
"""

_GROUP_CSS = (
    '#{uid} tbody:has(#{cid}:checked) tr[data-ct-group-member="{n}"]{{display:none}}\n'
    '#{uid} tbody:has(#{cid}:checked) label[for="{cid}"] .ct-caret{{transform:rotate(-90deg)}}\n'
)


def _top_level_row_spans(body: str) -> list[tuple[int, int]]:
    """Depth-tracking scan for `<tr>...</tr>` spans at nesting depth 0.

    A markdown/passthrough cell can legitimately contain a nested
    `<table>`, so a naive `"<tr" in body` split would also tag its rows.
    Only rows that open and close at depth 0 are real body rows.
    """
    depth = 0
    start: int | None = None
    spans: list[tuple[int, int]] = []
    for m in _ROW_TOKEN_RE.finditer(body):
        if m.group(0) == "</tr>":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, m.end()))
                start = None
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def _insert_tr_attr(row: str, attr: str) -> str:
    """Insert `attr` into the row's opening `<tr...>` tag, right after `<tr`."""
    close = row.index(">")
    return "<tr " + attr + row[len("<tr") : close] + row[close:]


def _tag_heading_row(row: str, *, uid: str, n: int) -> str:
    cid = f"ct-{uid}-g{n}"

    def _wrap_heading(match: re.Match[str]) -> str:
        open_th, inner, close_th = match.group(1), match.group(2), match.group(3)
        checkbox = f'<input class="ct-group-state" type="checkbox" id="{cid}">'
        label = (
            f'<label class="ct-group-toggle" for="{cid}">'
            f'<span class="ct-caret" aria-hidden="true">\u25be</span>{inner}</label>'
        )
        return f"{open_th}{checkbox}{label}{close_th}"

    row = _GROUP_HEADING_TH_RE.sub(_wrap_heading, row, count=1)
    return _insert_tr_attr(row, f'data-ct-group="{n}"')


def _tag_member_row(row: str, *, n: int) -> str:
    return _insert_tr_attr(row, f'data-ct-group-member="{n}"')


def make_collapsible(html: str) -> str:
    """Tag `great_tables` row-group headings so CSS alone can collapse them.

    Locates the `<tbody class="gt_table_body">...</tbody>` slice and walks
    its rows with a depth-tracking scan (not a naive split, which would
    also match `<tr>` tags nested inside a markdown/passthrough cell).
    Each `gt_group_heading_row` gets a `data-ct-group="n"` attribute, its
    heading text is wrapped in a `<label>`/`<input type="checkbox">` pair,
    and every following row up to the next heading gets
    `data-ct-group-member="n"` -- except a shared forest/sparkline axis
    row (marked by `render.py` with a `--ct-axis-row:1` CSS custom
    property), which stays untagged so it never disappears into whichever
    group happens to precede it. A `<style>` block using `:has()` is
    appended after the wrapper `</div>` to do the actual hiding.

    Returns `html` unchanged if the tbody is not found, or if no group
    heading row (empty- or non-empty-label) is present.
    """
    tbody_open = _TBODY_OPEN_RE.search(html)
    if tbody_open is None:
        return html
    tbody_close = html.find("</tbody>", tbody_open.end())
    if tbody_close == -1:
        return html

    body = html[tbody_open.end() : tbody_close]
    spans = _top_level_row_spans(body)
    if not any('class="gt_group_heading"' in body[s:e] for s, e in spans):
        return html

    uid_match = _WRAPPER_DIV_ID_RE.search(html)
    if uid_match is None:
        return html
    uid = uid_match.group(1)

    pieces: list[str] = []
    cursor = 0
    n = -1
    group_ids: list[str] = []
    for start, end in spans:
        pieces.append(body[cursor:start])
        row = body[start:end]
        if 'class="gt_group_heading"' in row:
            n += 1
            pieces.append(_tag_heading_row(row, uid=uid, n=n))
            group_ids.append(f"ct-{uid}-g{n}")
        elif "--ct-axis-row:1" in row:
            # A shared forest/sparkline axis row (great_tables schedules it
            # once per shared domain, which for the default `scale="table"`
            # is once for the whole column). It is not this group's data
            # and must stay visible no matter which group collapses --
            # leave it untagged rather than folding it into whichever
            # group happens to precede it in row order.
            pieces.append(row)
        elif n >= 0:
            pieces.append(_tag_member_row(row, n=n))
        else:
            pieces.append(row)
        cursor = end
    pieces.append(body[cursor:])
    new_body = "".join(pieces)

    new_html = html[: tbody_open.end()] + new_body + html[tbody_close:]

    style = "<style>\n" + _BASE_CSS.format(uid=uid)
    for n, cid in enumerate(group_ids):
        style += _GROUP_CSS.format(uid=uid, cid=cid, n=n)
    style += "</style>"

    div_close = new_html.rfind("</div>")
    return new_html[: div_close + len("</div>")] + style + new_html[div_close + len("</div>") :]
