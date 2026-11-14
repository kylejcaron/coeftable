"""Explicit browser activation for trusted coeftable HTML fragments.

SVG payload v1 contains version, kind, rect (left/right/top/bottom), theme
colors (surface/text/axis) and ordered traces (label/color/points). Points
carry original index, x, projected px/py, x/value/lower/upper display text,
status and ordered extras. Forest points have null x/px/py plus unbounded
endpoint flags; they bypass sparkline nearest-observation selection.
Unknown versions remain static. No existing renderer activates scripts.
"""

from functools import lru_cache
from html.parser import HTMLParser
from importlib.resources import files

from coeftable.errors import SpecError


class _FragmentParser(HTMLParser):
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("html", "head", "body"):
            raise SpecError("interactive_html accepts fragments, not complete HTML documents.")


@lru_cache(maxsize=1)
def _runtime() -> str:
    """Read the packaged dependency-free runtime once per process."""
    return files("coeftable").joinpath("_tooltip_runtime.js").read_text(encoding="utf-8")


def interactive_html(fragment: str, *, full_document: bool = False) -> str:
    """Activate observation inspection around a trusted rendered HTML fragment.

    This helper does not sanitize arbitrary HTML. Include only data intended
    for the browser. Scripts must be allowed by the host: innerHTML-inserted
    scripts are inert; explicit mounting is available through
    ``window.coeftableTooltips.mount(root)``. Existing render methods and SVG
    outputs remain passive. For marimo, host a full document with
    ``mo.iframe(interactive_html(fragment, full_document=True), height='500px')``.
    No kernel, CDN, network connection, or runtime Python dependency is needed.
    """
    parser = _FragmentParser()
    parser.feed(fragment)
    parser.close()
    assembled = (
        '<div class="ct-interactive">'
        + fragment
        + "<script>"
        + _runtime()
        + "\nwindow.coeftableTooltips.mount(document.currentScript.parentElement);"
        + "</script></div>"
    )
    if not full_document:
        return assembled
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "</head><body>" + assembled + "</body></html>"
    )
