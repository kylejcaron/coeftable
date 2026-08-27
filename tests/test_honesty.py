import math

import pytest

from coeftable.errors import SpecError
from coeftable.graph.honesty import (
    RESIDUAL_FAIL,
    RESIDUAL_WARN,
    TRADEOFF_R,
    endpoint_interval,
    identity_gap,
    level_noise,
    ribbon_bounds,
    ribbon_domain,
    tradeoff_pairs,
    weekly_log_changes,
)


def test_weekly_log_changes_are_successive_log_ratios():
    changes = weekly_log_changes((100.0, 110.0, 121.0))
    assert changes == pytest.approx((math.log(1.1), math.log(1.1)))


def test_endpoint_band_is_twice_the_change_deviation_not_twice_level_noise():
    # The endpoint log change carries noise from BOTH endpoints, so its band is
    # 2*stdev(d), while a single level's noise is stdev(d)/sqrt(2). Conflating
    # them understates the band by sqrt(2) - this test is the guard.
    series = (100.0, 104.0, 103.0, 110.0, 108.0, 116.0)
    changes = weekly_log_changes(series)
    import statistics

    expected_band = 2 * statistics.stdev(changes)
    assert level_noise(series) == pytest.approx(statistics.stdev(changes) / math.sqrt(2))
    delta, lower, upper = endpoint_interval(series)
    total = math.log(series[-1] / series[0])
    assert delta == pytest.approx(100 * (math.exp(total) - 1))
    assert lower == pytest.approx(100 * (math.exp(total - expected_band) - 1))
    assert upper == pytest.approx(100 * (math.exp(total + expected_band) - 1))


def test_a_noisy_flat_series_produces_an_interval_spanning_zero():
    noisy = (100.0, 108.0, 94.0, 106.0, 97.0, 101.0)
    _, lower, upper = endpoint_interval(noisy)
    assert lower < 0.0 < upper


def test_ribbon_bounds_scale_each_level_multiplicatively():
    series = (100.0, 110.0, 105.0, 115.0)
    sigma = level_noise(series)
    lower, upper = ribbon_bounds(series)
    assert lower[0] == pytest.approx(100.0 * math.exp(-2 * sigma))
    assert upper[0] == pytest.approx(100.0 * math.exp(+2 * sigma))


def test_ribbon_domain_pads_by_a_tenth_of_the_series_span():
    series = (100.0, 110.0, 105.0, 115.0)
    lower, upper = ribbon_bounds(series)
    lo, hi = ribbon_domain(series, lower, upper)
    span = max(series) - min(series)
    assert lo == pytest.approx(min(lower) - 0.1 * span)
    assert hi == pytest.approx(max(upper) + 0.1 * span)


def test_ribbon_domain_survives_a_flat_series():
    # span would be 0; the fallback keeps the domain non-degenerate.
    flat = (50.0, 50.0, 50.0)
    lower, upper = ribbon_bounds(flat)
    lo, hi = ribbon_domain(flat, lower, upper)
    assert hi > lo


def test_identity_gap_is_zero_for_an_exact_additive_split():
    parent = (10.0, 20.0, 30.0)
    children = ((4.0, 8.0, 12.0), (6.0, 12.0, 18.0))
    assert identity_gap(parent, children, "+") == pytest.approx(0.0)


def test_identity_gap_is_zero_for_an_exact_multiplicative_split():
    parent = (12.0, 24.0)
    children = ((3.0, 4.0), (4.0, 6.0))
    assert identity_gap(parent, children, "x") == pytest.approx(0.0)


def test_identity_gap_measures_mean_relative_shortfall():
    parent = (100.0, 100.0)
    children = ((40.0, 30.0),)  # short by 60% then 70%
    assert identity_gap(parent, children, "+") == pytest.approx(0.65)


def test_tradeoff_pairs_flag_only_strongly_negative_change_correlation():
    rising = (100.0, 110.0, 121.0, 133.0)
    # Exact reciprocal of `rising`: its weekly log changes are the negation
    # of rising's, so the correlation is exactly -1.0.
    falling = tuple(10000.0 / value for value in rising)
    together = (100.0, 110.0, 121.0, 133.0)
    pairs = tradeoff_pairs((("a", rising), ("b", falling), ("c", together)))
    names = {(x, y) for x, y, _ in pairs}
    assert ("a", "b") in names
    assert ("a", "c") not in names


def test_tradeoff_threshold_is_strict():
    assert TRADEOFF_R == -0.5


def test_thresholds_match_the_spec():
    assert RESIDUAL_WARN == 0.005
    assert RESIDUAL_FAIL == 0.20


def test_short_series_is_rejected():
    with pytest.raises(SpecError, match="at least 3"):
        endpoint_interval((100.0, 110.0))


def test_nonpositive_levels_are_rejected():
    # Log ratios are undefined at or below zero; refuse rather than emit nan.
    with pytest.raises(SpecError, match="positive"):
        weekly_log_changes((100.0, 0.0, 50.0))
