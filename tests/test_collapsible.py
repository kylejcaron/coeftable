import random
import re
from typing import Any

import polars as pl

from coeftable.collapsible import make_collapsible
from coeftable.spec import CoefTable

RAW = {
    "area": ["Core", "Core", "Ops", "Ops", "Sales", "Sales"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency", "Deals", "Deals"],
    "variant": ["B", "C", "B", "C", "B", "C"],
    "rel": [3.4, -1.2, 0.5, 2.0, 1.1, -0.4],
    "rel_lb": [1.2, -4.0, -1.0, 0.8, 0.2, -1.5],
    "rel_ub": [5.7, 1.6, 2.0, 3.2, 2.0, 0.7],
}


def table(**kwargs):
    return CoefTable(pl.DataFrame(RAW), rows="metric", nest="variant", **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


def _wrapper_id(html: str) -> str:
    match = re.search(r'<div\s+id="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_three_groups_get_three_distinct_group_ids_with_correct_membership():
    html = make_collapsible(table(groups="area").gt().as_raw_html())
    tbody = html[html.index('<tbody class="gt_table_body">') : html.index("</tbody>")]

    headings = re.findall(r'<tr data-ct-group="(\d+)"[^>]*class="gt_group_heading_row">', tbody)
    assert headings == ["0", "1", "2"]

    # Each group has exactly two data rows (variant B and C), and they
    # must carry the group id of the heading immediately above them --
    # not just "some" group id.
    for n in range(3):
        members = re.findall(rf'<tr data-ct-group-member="{n}">', tbody)
        assert len(members) == 2

    # Every data row between heading 0 and heading 1 is tagged "0"; between
    # heading 1 and heading 2 is tagged "1"; after heading 2 is tagged "2".
    heading_0 = tbody.index('data-ct-group="0"')
    heading_1 = tbody.index('data-ct-group="1"')
    heading_2 = tbody.index('data-ct-group="2"')
    assert heading_0 < heading_1 < heading_2

    core_slice = tbody[heading_0:heading_1]
    ops_slice = tbody[heading_1:heading_2]
    sales_slice = tbody[heading_2:]
    assert core_slice.count('data-ct-group-member="0"') == 2
    assert core_slice.count('data-ct-group-member="1"') == 0
    assert ops_slice.count('data-ct-group-member="1"') == 2
    assert ops_slice.count('data-ct-group-member="0"') == 0
    assert sales_slice.count('data-ct-group-member="2"') == 2


def test_forest_axis_row_is_not_folded_into_the_last_group():
    # The shared forest axis (default scale="table") is scheduled once,
    # after the last data row across the whole column -- not per group.
    # Tagging it data-ct-group-member would hide the axis whenever that
    # last group collapses, even though earlier groups' rows (still
    # visible) reference the same shared scale.
    html = table(groups="area").forest("Plot", of="Lift %").gt().as_raw_html()
    result = make_collapsible(html)
    tbody = result[result.index('<tbody class="gt_table_body">') : result.index("</tbody>")]

    assert tbody.count("<svg") == 7  # 6 data rows + 1 shared axis row
    axis_row = tbody[tbody.index("--ct-axis-row:1") :]
    axis_row = axis_row[: axis_row.index("</tr>") + len("</tr>")]
    assert "data-ct-group-member" not in axis_row

    # Every other row is still correctly tagged.
    assert tbody.count('data-ct-group-member="2"') == 2


def test_sparkline_axis_row_is_not_folded_into_the_last_group():
    raw: dict[str, Any] = {
        **RAW,
        "trend": [
            [1.0, 1.2],
            [0.9, 0.8],
            [2.0, 2.4],
            [1.8, 1.5],
            [0.5, 0.6],
            [0.4, 0.3],
        ],
    }
    html = (
        CoefTable(pl.DataFrame(raw), rows="metric", nest="variant", groups="area")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .sparkline("Trend", value="trend")
        .gt()
        .as_raw_html()
    )
    result = make_collapsible(html)
    tbody = result[result.index('<tbody class="gt_table_body">') : result.index("</tbody>")]

    axis_row = tbody[tbody.index("--ct-axis-row:1") :]
    axis_row = axis_row[: axis_row.index("</tr>") + len("</tr>")]
    assert "data-ct-group-member" not in axis_row
    assert tbody.count('data-ct-group-member="2"') == 2


def test_empty_group_label_gets_its_own_toggle_not_folded_into_the_previous_group():
    # great_tables emits a different <tr> class for an empty group label
    # (`gt_empty_group_heading` instead of `gt_group_heading_row`), but the
    # same `<th class="gt_group_heading">` marker either way. Detecting on
    # the `<tr>` class alone misses this and silently folds the empty-label
    # group's heading and rows into the previous group's toggle.
    raw = dict(RAW)
    raw["area"] = ["Core", "Core", "", "", "Sales", "Sales"]
    html = make_collapsible(
        CoefTable(pl.DataFrame(raw), rows="metric", nest="variant", groups="area")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
        .as_raw_html()
    )
    tbody = html[html.index('<tbody class="gt_table_body">') : html.index("</tbody>")]

    assert 'class="gt_empty_group_heading"' in tbody
    headings = re.findall(r'data-ct-group="(\d+)"', tbody)
    assert headings == ["0", "1", "2"]

    heading_0 = tbody.index('data-ct-group="0"')
    heading_1 = tbody.index('data-ct-group="1"')
    heading_2 = tbody.index('data-ct-group="2"')
    core_slice = tbody[heading_0:heading_1]
    empty_slice = tbody[heading_1:heading_2]
    sales_slice = tbody[heading_2:]
    assert core_slice.count('data-ct-group-member="0"') == 2
    assert empty_slice.count('data-ct-group-member="1"') == 2
    assert sales_slice.count('data-ct-group-member="2"') == 2


def test_injects_exactly_one_style_block_with_one_toggle_per_group():
    html = table(groups="area").gt().as_raw_html()
    result = make_collapsible(html)

    assert result.count("<style>") == html.count("<style>") + 1
    # The accessibility-hiding rule for the checkbox is written once, in
    # the shared base CSS -- not duplicated per group.
    assert result.count(".ct-group-state{") == 1
    # One toggle label per group heading (3 groups -> 3 labels).
    assert result.count('class="ct-group-toggle"') == 3


def test_every_emitted_id_and_selector_is_scoped_to_the_wrapper_div_id():
    html = table(groups="area").gt().as_raw_html()
    uid = _wrapper_id(html)
    result = make_collapsible(html)

    checkbox_re = r'<input class="ct-group-state" type="checkbox" id="([^"]+)">'
    checkbox_ids = re.findall(checkbox_re, result)
    assert len(checkbox_ids) == 3
    for cid in checkbox_ids:
        assert cid.startswith(f"ct-{uid}-g")

    label_fors = re.findall(r'<label class="ct-group-toggle" for="([^"]+)">', result)
    assert label_fors == checkbox_ids

    # No selector or id in the injected markup/CSS is a bare "#ct-..." --
    # every one has the wrapper div id embedded right after "ct-".
    bare_refs = re.findall(r"#ct-[\w-]*", result)
    assert len(bare_refs) > 0
    for bare in bare_refs:
        assert bare.startswith(f"#ct-{uid}-g")


def test_table_without_groups_is_returned_byte_identical():
    html = table().gt().as_raw_html()
    assert make_collapsible(html) == html


def test_nested_table_inside_a_passthrough_cell_is_not_tagged_as_a_body_row():
    raw = dict(RAW)
    raw["note"] = ["<table><tr><td>x</td></tr></table>", "n2", "n3", "n4", "n5", "n6"]
    html = (
        CoefTable(pl.DataFrame(raw), rows="metric", nest="variant", groups="area")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .passthrough("Note", "note")
        .gt()
        .as_raw_html()
    )
    result = make_collapsible(html)

    # The naive-split failure mode: splitting on "<tr" would count the
    # nested table's row and misalign every group-member tag after it.
    tbody = result[result.index('<tbody class="gt_table_body">') : result.index("</tbody>")]
    assert '<tr data-ct-group-member="0">\n    <td' in tbody
    for n in range(3):
        assert tbody.count(f'data-ct-group-member="{n}"') == 2

    # The nested row itself must not have been touched.
    assert "<tr><td>x</td></tr>" in result
    assert re.search(r'data-ct-group[^"]*="[^"]*"\s*>\s*<td>x</td>', result) is None

    headings = re.findall(r'data-ct-group="(\d+)"', result)
    assert headings == ["0", "1", "2"]


def test_html_with_no_tbody_is_returned_unchanged():
    html = "<div id='x'><p>no table here</p></div>"
    assert make_collapsible(html) == html


def test_coeftable_as_raw_html_wiring_matches_direct_transform():
    # Guards the funnel in spec.py: as_raw_html() must be exactly
    # make_collapsible(self.gt().as_raw_html()), not a reimplementation.
    # great_tables assigns a fresh random wrapper-div id per .gt() call, so
    # seed around each render to compare in isolation.
    grouped = table(groups="area", collapsible_groups=True)
    random.seed(0)
    via_wiring = grouped.as_raw_html()
    random.seed(0)
    direct = make_collapsible(grouped.gt().as_raw_html())
    assert via_wiring == direct
