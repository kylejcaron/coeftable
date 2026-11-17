import pytest

from coeftable.dotplots import layout_dots, prepare_dots
from coeftable.errors import SpecError


def test_empirical_midpoints_preserve_discrete_mass():
    for samples in ([10, 0], [0, 10]):
        assert prepare_dots(samples=samples, dot_count=4).quantiles == (0, 0, 10, 10)
    assert prepare_dots(samples=[7], dot_count=4).quantiles == (7,) * 4
    assert prepare_dots(samples=[0, 1, 2, 3], dot_count=2).quantiles == (0, 2)


def test_precomputed_midpoints_preserve_ties_and_validate_count():
    result = prepare_dots(quantiles=[-1, 0, 0, 2])
    assert result.quantiles == (-1, 0, 0, 2)
    assert result.dot_count == 4
    with pytest.raises(SpecError):
        prepare_dots(quantiles=[-1, 0, 0, 2], dot_count=5)
    with pytest.raises(SpecError):
        prepare_dots(quantiles=[1, 0])
    assert prepare_dots(quantiles=[]).dot_count is None
    assert prepare_dots(samples=[]).dot_count == 20
    assert prepare_dots(quantiles=[], dot_count=4).dot_count == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"samples": [], "quantiles": []},
        {"samples": 2},
        {"samples": "12"},
        {"samples": [float("nan")]},
        {"samples": [None]},
        {"samples": [True]},
        {"samples": [1], "dot_count": True},
        {"samples": [1], "dot_count": 1},
        {"quantiles": [1]},
        {"samples": [[1]]},
        {"samples": [float("inf")]},
    ],
)
def test_malformed_distribution_cannot_silently_change_weights(kwargs):
    with pytest.raises(SpecError):
        prepare_dots(**kwargs)


def test_layout_preserves_endpoints_and_accounts_for_all_dots():
    values = prepare_dots(quantiles=[-3, -1, 0, 1, 3])
    layout = layout_dots(values, domain=(-1, 1), project=lambda x: 10 * (x + 1), dot_size=4)
    assert [(p.value, p.x) for p in layout.dots] == [(-1, 0), (0, 10), (1, 20)]
    assert (layout.below, layout.above, layout.dot_count) == (1, 1, 5)
    outside = layout_dots(values, domain=(4, 5), project=lambda x: x, dot_size=4)
    assert not outside.dots
    assert (outside.below, outside.above, outside.dot_count) == (5, 0, 5)


def test_exact_x_stacking_separates_ties_without_jitter():
    values = prepare_dots(quantiles=[0, 0, 0.01, 1])
    layout = layout_dots(values, domain=(0, 1), project=lambda x: 100 * x, dot_size=4)
    assert [p.x for p in layout.dots] == [0, 0, 1, 100]
    assert [p.level for p in layout.dots] == [0, 1, 2, 0]
    assert layout.levels == 3
