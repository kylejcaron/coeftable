"""Contract tests for the public plot-primitives facade."""

import ast
from pathlib import Path

import pytest


EXPECTED_EXPORTS = {
    "ResolvedBand",
    "ResolvedRule",
    "Trace",
    "forest_axis",
    "forest_bar",
    "sparkline_axis",
    "sparkline_bar",
    "sparkline_multi",
}

# The layering law from the architecture: plots (and later cards/graph)
# import only the foundation layer, never table modules.
FORBIDDEN_IMPORTS = {
    "coeftable.spec",
    "coeftable.frame",
    "coeftable.render",
    "coeftable.grid",
    "coeftable.collapsible",
    "coeftable.series",
}


def test_public_surface_is_exactly_the_promised_set():
    import coeftable.plots as plots

    assert set(plots.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(plots, name)


def test_plots_imports_only_foundation_modules():
    import coeftable.plots as plots

    tree = ast.parse(Path(plots.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not imported & FORBIDDEN_IMPORTS


def test_facade_names_are_the_svg_objects():
    # Re-export, not wrapper: identity guarantees no drift in behavior
    # or signature between the public path and the internal one.
    import coeftable.plots as plots
    import coeftable.svg as svg

    assert plots.forest_bar is svg.forest_bar
    assert plots.sparkline_bar is svg.sparkline_bar
    assert plots.sparkline_multi is svg.sparkline_multi
    assert plots.Trace is svg.Trace


def test_forest_bar_renders_via_public_path():
    from coeftable.plots import forest_bar
    from coeftable.theme import DEFAULT

    svg_str = forest_bar(
        1.2, 0.4, 2.0, domain=(-1.0, 3.0), ref=0.0, color=DEFAULT.favorable, theme=DEFAULT
    )
    assert svg_str.startswith("<svg")
    assert svg_str.endswith("</svg>")


def test_sparkline_bar_renders_via_public_path():
    import coeftable as ct
    from coeftable.plots import sparkline_bar
    from coeftable.theme import DEFAULT

    svg_str = sparkline_bar(
        [0.0, 1.0, 2.0],
        [1.0, 1.5, 2.0],
        [0.5, 1.0, 1.6],
        [1.5, 2.0, 2.4],
        x_domain=(0.0, 2.0),
        domain=(0.0, 3.0),
        ref=0.0,
        color=DEFAULT.favorable,
        fmt=ct.Number(),
        theme=DEFAULT,
    )
    assert svg_str.startswith("<svg")


def test_sparkline_multi_renders_via_public_path():
    import coeftable as ct
    from coeftable.plots import Trace, sparkline_multi
    from coeftable.theme import DEFAULT

    trace = Trace(
        x=[0.0, 1.0, 2.0],
        y=[1.0, 1.5, 2.0],
        lower=[0.5, 1.0, 1.6],
        upper=[1.5, 2.0, 2.4],
        color=DEFAULT.favorable,
        show_ribbon=True,
        label="A",
    )
    svg_str = sparkline_multi(
        [trace],
        x_domain=(0.0, 2.0),
        domain=(0.0, 3.0),
        ref=0.0,
        ref_color=DEFAULT.axis,
        fmt=ct.Number(),
        theme=DEFAULT,
    )
    assert svg_str.startswith("<svg")


def test_annotated_forest_bar_accepts_resolved_rule():
    from coeftable.plots import ResolvedRule, forest_bar
    from coeftable.theme import DEFAULT

    rule = ResolvedRule(
        at=0.5,
        axis="x",
        layer="overlay",
        affect_domain=False,
        color=DEFAULT.axis,
        opacity=1.0,
        width=1.0,
        dash="dashed",
    )
    svg_str = forest_bar(
        1.2,
        0.4,
        2.0,
        domain=(-1.0, 3.0),
        ref=0.0,
        color=DEFAULT.favorable,
        theme=DEFAULT,
        annotations=(rule,),
    )
    assert svg_str.startswith("<svg")
