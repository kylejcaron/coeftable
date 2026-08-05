"""Turn a resolved specification into a great_tables object."""

from __future__ import annotations

from great_tables import GT, loc, style

from coeftable.frame import resolve
from coeftable.spec import CoefTable


def to_gt(table: CoefTable) -> GT:
    """Render `table` to a `great_tables` object.

    Parameters
    ----------
    table
        The specification to render.

    Returns
    -------
    GT
        A styled table; further native `great_tables` calls may be chained.
    """
    resolved = resolve(table)
    theme = table.theme
    border_color = theme.border_color or theme.header_bg

    gt = GT(
        resolved.frame,
        groupname_col=resolved.group_column,
    )

    if table.title:
        gt = gt.tab_header(title=table.title, subtitle=table.subtitle or None)
        gt = gt.tab_style(
            style=[
                style.text(color=theme.header_fg, weight="bold", size="26px", align="left"),
                style.fill(color=theme.header_bg),
            ],
            locations=loc.title(),
        )
        if table.subtitle:
            gt = gt.tab_style(
                style=[
                    style.text(color=theme.header_fg, size="16px", align="left"),
                    style.fill(color=theme.header_bg),
                ],
                locations=loc.subtitle(),
            )

    gt = gt.tab_style(
        style=[
            style.text(weight="bold", color=theme.header_fg, align="center", size="16px"),
            style.fill(color=theme.column_label_bg),
        ],
        locations=loc.column_labels(),
    )

    for split_value, columns in resolved.spanners.items():
        gt = gt.tab_spanner(label=split_value, columns=columns)

    if resolved.labels:
        gt = gt.cols_label(cases=dict(resolved.labels))

    gt = gt.fmt_markdown(columns=resolved.markdown_columns).cols_align(align="center")

    if resolved.band_rows:
        gt = gt.tab_style(
            style=style.fill(color=theme.band),
            locations=loc.body(rows=resolved.band_rows),
        )
    if resolved.divider_rows:
        # Deliberately lighter than border_color: this is a subtle divider
        # between row-key blocks within the light body-row region, not a
        # structural/chrome border. theme.rule is the intended field for
        # "divider on a light background"; border_color is for the darker
        # borders around table/column-label/row-group chrome.
        gt = gt.tab_style(
            style=style.borders(sides="top", color=theme.rule, weight="1px"),
            locations=loc.body(rows=resolved.divider_rows),
        )
    if resolved.axis_rows:
        gt = gt.tab_style(
            style=[
                style.fill(color=theme.surface),
                style.borders(sides="top", color=theme.rule, weight="1px"),
                style.borders(sides="bottom", color=theme.surface, weight="0px"),
                # Marks this as a shared axis/footer row rather than a
                # per-group data row: `collapsible.py` reads this to keep
                # the row visible regardless of which group precedes it,
                # since a `scale="table"` axis belongs to the whole column,
                # not to whichever group happens to render last.
                style.css("--ct-axis-row:1"),
            ],
            locations=loc.body(rows=resolved.axis_rows),
        )
    if resolved.group_column:
        gt = gt.tab_style(
            style=[
                style.text(
                    weight="bold", color=theme.header_fg, size="16px", transform="uppercase"
                ),
                style.fill(color=theme.column_label_bg),
                style.css("letter-spacing: 0.8px;"),
                style.css(
                    f"border-top: 1px solid {border_color} !important;"
                    f"border-bottom: 1px solid {border_color};"
                ),
            ],
            locations=loc.row_groups(),
        )
    if resolved.plot_columns:
        # The SVG's own height fills the row's content box; the
        # remaining gap around it is this cell's vertical padding, which
        # is otherwise sized for the taller estimate/CI text next to it.
        # Shrinking it here lets the plot (and its reference line) reach
        # closer to the row's true top/bottom edge.
        gt = gt.tab_style(
            style=style.css("padding-top: 2px; padding-bottom: 2px;"),
            locations=loc.body(columns=resolved.plot_columns),
        )

    side_border_style = "none" if theme.border_style == "minimal" else "solid"
    return gt.tab_options(
        table_font_size=theme.table_font_size,
        column_labels_font_size="16px",
        data_row_padding="10px",
        column_labels_padding="12px",
        data_row_padding_horizontal="16px",
        column_labels_padding_horizontal="16px",
        heading_border_bottom_color=border_color,
        heading_border_bottom_style="solid",
        heading_border_bottom_width="1px",
        column_labels_border_top_color=border_color,
        column_labels_border_top_style="solid",
        column_labels_border_top_width="1px",
        column_labels_border_bottom_color=border_color,
        column_labels_border_bottom_style="solid",
        column_labels_border_bottom_width="1px",
        row_group_border_top_color=border_color,
        row_group_border_top_style="solid",
        row_group_border_top_width="1px",
        row_group_border_bottom_color=border_color,
        row_group_border_bottom_style="solid",
        row_group_border_bottom_width="1px",
        table_border_top_color=border_color,
        table_border_top_style="solid",
        table_border_bottom_color=border_color,
        table_border_bottom_style="solid",
        table_border_left_color=border_color,
        table_border_left_style=side_border_style,
        table_border_right_color=border_color,
        table_border_right_style=side_border_style,
        table_body_border_top_color=border_color,
        table_body_border_top_style="solid",
        table_body_border_top_width="1px",
        table_body_border_bottom_color=border_color,
        table_body_border_bottom_style="solid",
    )
