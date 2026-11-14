from html.parser import HTMLParser

import pytest

from coeftable import Tooltip, TooltipValues, interactive_html
from coeftable.errors import SpecError
from coeftable.plots import Trace, forest_bar, sparkline_bar, sparkline_multi
from coeftable.theme import DEFAULT


class _Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.bodies = 0
        self.in_body = False
        self.body_scripts = 0
        self.svg_payloads = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.bodies += 1
            self.in_body = True
        if tag == "script" and self.in_body:
            self.body_scripts += 1
        if tag == "svg":
            self.svg_payloads.append(dict(attrs).get("data-ct-tooltip"))

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False


def _plot():
    traces = [
        Trace([0, 2, 4], [1, None, 5], [None] * 3, [None] * 3, "#123456", False, "A"),
        Trace([0, 4, 4], [2, 6, 7], [None] * 3, [None] * 3, "#567890", False, "B"),
    ]
    return sparkline_multi(
        traces,
        x_domain=(0, 4),
        domain=(0, 3),
        ref=None,
        ref_color="#123456",
        fmt=str,
        tooltip=Tooltip(fmt=str, x_fmt=str),
        tooltip_values=[[TooltipValues("n", [10, 20, 30])], []],
        show_endpoint=False,
        width=220,
        height=60,
    )


def test_interactive_html_preserves_payload_and_places_bootstrap_in_body():
    fragment = _plot()
    source = _Document()
    source.feed(fragment)
    document = _Document()
    document.feed(interactive_html(fragment, full_document=True))
    assert document.bodies == 1
    assert document.body_scripts >= 1
    assert document.svg_payloads == source.svg_payloads
    with pytest.raises(SpecError):
        interactive_html("<!doctype html><html><head></head><body>table</body></html>")


@pytest.fixture
def page():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport={"width": 640, "height": 480}, has_touch=True)
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page
        assert errors == []
        context.close()
        browser.close()


def _move(page, x, selector="svg[data-ct-tooltip]", y=None):
    point = page.locator(selector).first.evaluate(
        """(svg, args) => {
        const p = JSON.parse(svg.dataset.ctTooltip), r = p.rect;
        let px = (r.left + r.right) / 2;
        if (p.kind === 'sparkline') {
            const points = p.traces.flatMap(t => t.points);
            const first = points.reduce((a,b) => a.x < b.x ? a : b);
            const last = points.reduce((a,b) => a.x > b.x ? a : b);
            px = first.x === last.x ? px : first.px +
                (args.x-first.x)/(last.x-first.x)*(last.px-first.px);
        }
        const point = new DOMPoint(px, args.y ?? r.top+2).matrixTransform(svg.getScreenCTM());
        return {x: point.x, y: point.y};
    }""",
        {"x": x, "y": y},
    )
    page.mouse.move(point["x"], point["y"])


def _text(page):
    panel = page.locator(".ct-tooltip-panel")
    panel.wait_for(state="visible")
    return panel.inner_text()


@pytest.mark.integration
def test_union_selection_ties_gaps_duplicates_and_keyboard(page):
    page.set_content(interactive_html(_plot()))
    _move(page, 1.8)
    text = _text(page)
    assert "Missing" in text and "20" in text and "No observation" in text
    _move(page, 3)
    assert "Missing" in _text(page)
    _move(page, 3.1)
    text = _text(page)
    assert "5" in text and "6" in text and "7" in text and "above" in text
    target = page.locator(".ct-tooltip-target")
    target.focus()
    page.keyboard.press("Home")
    assert page.locator(".ct-tooltip-x").inner_text() == "0"
    page.keyboard.press("ArrowRight")
    assert page.locator(".ct-tooltip-x").inner_text() == "2"
    page.keyboard.press("End")
    assert page.locator(".ct-tooltip-x").inner_text() == "4"
    page.keyboard.press("ArrowLeft")
    assert page.locator(".ct-tooltip-x").inner_text() == "2"
    accessibility = page.context.new_cdp_session(page)
    document = accessibility.send("DOM.getDocument")
    node_id = accessibility.send(
        "DOM.querySelector",
        {
            "nodeId": document["root"]["nodeId"],
            "selector": ".ct-tooltip-target",
        },
    )["nodeId"]
    ax = accessibility.send(
        "Accessibility.getPartialAXTree",
        {
            "nodeId": node_id,
            "fetchRelatives": False,
        },
    )
    description = ax["nodes"][0].get("description", {}).get("value", "")
    assert "Missing" in description and "20" in description
    accessibility.detach()
    page.keyboard.press("Escape")
    assert page.locator(".ct-tooltip-panel").is_hidden()


@pytest.mark.integration
def test_table_missing_only_arm_remains_selectable(page, inspection_table):
    page.set_content(interactive_html(inspection_table.as_raw_html()))
    _move(page, 2)
    text = _text(page)
    assert "Missing" in text and "20" in text
    assert text.count("No observation") == 2


@pytest.mark.integration
def test_forest_and_equal_domain_plots_are_inspectable_without_guides(page):
    from coeftable.cards import Card, Trend

    fragments = []
    for estimate, bounds in [(None, (-1, 1)), (5, (4, 6))]:
        fragments.append(
            forest_bar(
                estimate,
                *bounds,
                domain=(-2, 2),
                ref=0,
                color="#123456",
                theme=DEFAULT,
                tooltip=Tooltip(fmt=str),
                tooltip_values=[TooltipValues("n", [20])],
            )
        )
    fragments.append(
        sparkline_bar(
            [1],
            [1],
            [None],
            [None],
            x_domain=(1, 1),
            domain=(1, 1),
            ref=None,
            color="#123456",
            fmt=str,
            tooltip=Tooltip(),
            show_endpoint=False,
        )
    )
    constant = Card(
        "Constant",
        content=[
            Trend(
                x=[0, 2],
                y=[1, 1],
                x_domain=(0, 2),
                domain=(1, 1),
                show_axis=False,
                show_endpoint=False,
                tooltip=Tooltip(),
            )
        ],
    )
    fragments.append('<div id="constant">' + constant.as_raw_html() + "</div>")
    page.set_content(interactive_html("".join(fragments)))
    _move(page, 0, "svg:nth-of-type(1)")
    assert "Missing" in _text(page) and "-1" in _text(page)
    assert page.locator(".ct-tooltip-guide").count() == 0
    page.locator("svg:nth-of-type(2) .ct-tooltip-target").focus()
    assert "5" in _text(page) and "right" in _text(page) and "6" in _text(page)
    _move(page, 0, "svg:nth-of-type(3)")
    assert "1" in _text(page)
    _move(page, 1, "#constant svg[data-ct-tooltip]")
    assert "1" in _text(page)


@pytest.mark.integration
def test_scaled_plot_portal_escapes_clipping_drag_cancel_and_touch_release(page):
    page.set_content(
        interactive_html(
            '<div style="margin:100px 0 0 80px;width:330px;height:90px;overflow:hidden">'
            '<div style="transform:scale(1.5);transform-origin:top left">'
            + _plot()
            + "</div></div>"
        )
    )
    _move(page, 2)
    assert "Missing" in _text(page)
    box = page.locator(".ct-tooltip-panel").bounding_box()
    assert 0 <= box["x"] and box["x"] + box["width"] <= 640
    assert 0 <= box["y"] and box["y"] + box["height"] <= 480
    assert box["y"] + box["height"] > 190
    page.mouse.down()
    page.mouse.move(620, 130)
    assert page.locator(".ct-tooltip-x").inner_text() == "4"
    page.mouse.up()
    target = page.locator(".ct-tooltip-target")
    target.dispatch_event("pointercancel", {"pointerId": 1})
    assert page.locator(".ct-tooltip-panel").is_hidden()
    bounds = target.bounding_box()
    page.touchscreen.tap(bounds["x"] + bounds["width"] / 2, bounds["y"] + 4)
    assert page.locator(".ct-tooltip-panel").is_visible()
    target.evaluate("el => el.blur()")
    _move(page, 2)
    page.mouse.move(5, 5)
    page.locator(".ct-tooltip-panel").wait_for(state="hidden")
    page.touchscreen.tap(bounds["x"] + bounds["width"] / 2, bounds["y"] + 4)
    page.touchscreen.tap(5, 5)
    assert page.locator(".ct-tooltip-panel").is_hidden()


@pytest.mark.integration
def test_overflow_panel_is_bounded_scrollable_and_does_not_reselect(page):
    page.set_viewport_size({"width": 320, "height": 240})
    extras = [TooltipValues(f"Field {i}", ["word" * 150]) for i in range(18)]
    svg = sparkline_bar(
        [0],
        [1],
        [None],
        [None],
        x_domain=(0, 0),
        domain=(0, 2),
        ref=None,
        color="#123456",
        fmt=str,
        tooltip=Tooltip(),
        tooltip_values=extras,
    )
    page.set_content(interactive_html(svg))
    _move(page, 0)
    panel = page.locator(".ct-tooltip-panel")
    box = panel.bounding_box()
    assert box["x"] >= 8 and box["x"] + box["width"] <= 312
    assert box["y"] >= 8 and box["y"] + box["height"] <= 232
    page.locator(".ct-tooltip-target").focus()
    page.keyboard.press("PageDown")
    assert panel.evaluate("el => el.scrollTop") > 0
    panel.hover()
    page.mouse.wheel(0, 10000)
    panel.locator("text=Field 17").wait_for(state="visible")
    assert panel.is_visible()
    assert panel.evaluate("el => el.scrollTop") > 0
    page.keyboard.press("Escape")
    assert panel.is_hidden()


@pytest.mark.integration
def test_overlapping_mounts_dynamic_plots_removal_and_literal_content(page):
    hostile = '<img src=x onerror="window.tooltipAttack=1">'
    svg = sparkline_bar(
        [0, 1, 2],
        [1, 2, 3],
        [None] * 3,
        [None] * 3,
        x_domain=(0, 2),
        domain=(0, 3),
        ref=None,
        color="#123456",
        fmt=str,
        tooltip=Tooltip(x_fmt=str),
        tooltip_values=[TooltipValues("Note", [hostile] * 3)],
    )
    page.set_content(
        interactive_html(
            '<section id="one">' + svg + '</section><section id="two">' + svg + "</section>"
        )
    )
    assert page.evaluate("""() => {
        const root = document.querySelector('.ct-interactive');
        const dispose = coeftableTooltips.mount(root);
        window.innerDispose = coeftableTooltips.mount(document.querySelector('#one'));
        return dispose === coeftableTooltips.mount(root);
    }""")
    page.locator("#one .ct-tooltip-target").focus()
    page.keyboard.press("Home")
    page.keyboard.press("ArrowRight")
    assert page.locator(".ct-tooltip-x").inner_text() == "1"
    assert hostile in _text(page)
    assert page.evaluate("window.tooltipAttack") is None
    page.locator("#two .ct-tooltip-target").focus()
    assert page.locator(".ct-tooltip-x").inner_text() == "0"
    page.evaluate("document.querySelector('#two').remove()")
    page.locator(".ct-tooltip-panel").wait_for(state="hidden")
    page.evaluate(
        "window.innerDispose(); document.querySelector('#one').insertAdjacentHTML("
        "'beforeend', document.querySelector('#one svg').outerHTML)"
    )
    page.locator("#one svg").last.locator(".ct-tooltip-target").focus()
    assert "Note" in _text(page)
    page.evaluate("document.querySelector('.ct-interactive').hidden = true")
    page.locator(".ct-tooltip-panel").wait_for(state="hidden")
    page.evaluate("""() => {
        const root = document.querySelector('.ct-interactive');
        coeftableTooltips.mount(root)();
        root.hidden = false;
    }""")
    assert page.locator(".ct-tooltip-panel").count() == 0
    assert page.locator(".ct-tooltip-target").count() == 0
    page.evaluate("() => { coeftableTooltips.mount(document.querySelector('.ct-interactive')); }")
    page.locator("#one svg").last.locator(".ct-tooltip-target").focus()
    assert "Note" in _text(page)


@pytest.mark.integration
def test_payload_changes_dismiss_stale_values_and_remove_unsupported_controls(page):
    page.set_content(interactive_html(_plot()))
    page.locator(".ct-tooltip-target").focus()
    assert "1" in _text(page)
    page.evaluate("""() => {
        const svg = document.querySelector('svg');
        const data = JSON.parse(svg.dataset.ctTooltip);
        data.traces[0].points[0].value_text = 'Updated observation';
        svg.dataset.ctTooltip = JSON.stringify(data);
    }""")
    page.locator(".ct-tooltip-panel").wait_for(state="hidden")
    page.locator(".ct-tooltip-target").focus()
    assert "Updated observation" in _text(page)
    page.evaluate("""() => {
        const svg = document.querySelector('svg');
        const data = JSON.parse(svg.dataset.ctTooltip);
        data.version = 99;
        svg.dataset.ctTooltip = JSON.stringify(data);
    }""")
    page.wait_for_function("document.querySelectorAll('.ct-tooltip-target').length === 0")
    assert page.locator(".ct-tooltip-panel").is_hidden()
    page.evaluate("""() => {
        const svg = document.querySelector('svg');
        const data = JSON.parse(svg.dataset.ctTooltip);
        data.version = 1;
        svg.dataset.ctTooltip = JSON.stringify(data);
    }""")
    page.locator(".ct-tooltip-target").focus()
    assert "Updated observation" in _text(page)
    page.evaluate("document.querySelector('svg').removeAttribute('data-ct-tooltip')")
    page.wait_for_function("document.querySelectorAll('.ct-tooltip-target').length === 0")
    assert page.locator(".ct-tooltip-panel").is_hidden()


@pytest.mark.integration
def test_disposed_root_stays_passive_when_sibling_mount_observes_metadata_changes(page):
    page.set_content(interactive_html(_plot()) + interactive_html(_plot()))
    page.evaluate("""() => {
        const root = document.querySelector('.ct-interactive');
        coeftableTooltips.mount(root)();
        const svg = root.querySelector('svg');
        const data = JSON.parse(svg.dataset.ctTooltip);
        data.traces[0].label = 'Updated passive plot';
        svg.dataset.ctTooltip = JSON.stringify(data);
    }""")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
    roots = page.locator(".ct-interactive")
    assert roots.first.locator(".ct-tooltip-target").count() == 0
    roots.last.locator(".ct-tooltip-target").focus()
    page.keyboard.press("End")
    assert "5" in _text(page)


@pytest.mark.integration
@pytest.mark.parametrize("container", ["card", "table"])
def test_touch_inspector_dismisses_when_keyboard_collapses_its_container(page, container):
    import polars as pl

    from coeftable import CoefTable
    from coeftable.cards import Card, Trend

    if container == "card":
        fragment = Card(
            "A",
            content=[
                Trend(
                    x=[0, 2],
                    y=[1, 2],
                    x_domain=(0, 2),
                    domain=(0, 3),
                    tooltip=Tooltip(),
                    show_axis=False,
                )
            ],
        ).as_raw_html()
    else:
        frame = pl.DataFrame(
            {
                "metric": ["A"],
                "group": ["One"],
                "x": [[0, 2]],
                "y": [[1, 2]],
            }
        )
        fragment = (
            CoefTable(
                frame,
                rows="metric",
                groups="group",
                collapsible_groups=True,
            )
            .sparkline("Trend", value="y", x="x", tooltip=Tooltip())
            .as_raw_html()
        )
    page.clock.install()
    page.set_content(interactive_html(fragment))
    target = page.locator(".ct-tooltip-target")
    box = target.bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + 4)
    assert "1" in _text(page)
    page.keyboard.press("Shift+Tab")
    page.clock.run_for(150)
    assert page.locator(".ct-tooltip-panel").is_visible()
    page.keyboard.press("Space")
    assert target.is_hidden()
    page.locator(".ct-tooltip-panel").wait_for(state="hidden")
