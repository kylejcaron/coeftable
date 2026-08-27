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


def test_tradeoff_pairs_skips_a_steady_sibling_instead_of_erroring():
    steady = (100.0, 100.0, 100.0, 100.0)
    rising = (100.0, 110.0, 121.0, 133.0)
    # Exact reciprocal of `rising`, so its correlation with `rising` is -1.0.
    falling = tuple(10000.0 / value for value in rising)
    pairs = tradeoff_pairs((("steady", steady), ("a", rising), ("b", falling)))
    names = {(x, y) for x, y, _ in pairs}
    assert ("a", "b") in names
    assert all("steady" not in pair for pair in names)


def test_weekly_log_changes_stay_finite_across_wildly_different_magnitudes():
    series = (1e-300, 1e300, 1e-300)
    changes = weekly_log_changes(series)
    assert all(math.isfinite(change) for change in changes)
    assert changes == pytest.approx(
        (math.log(1e300) - math.log(1e-300), math.log(1e-300) - math.log(1e300))
    )


def _geometric(magnitude: float, ratio: float, n: int) -> tuple[float, ...]:
    values = [magnitude]
    for _ in range(n - 1):
        values.append(values[-1] * ratio)
    return tuple(values)


def test_weekly_log_changes_are_exactly_constant_for_a_clean_geometric_series():
    series = _geometric(100.0, 1.08, 8)
    changes = weekly_log_changes(series)
    assert len(set(changes)) == 1


def test_tradeoff_pairs_treats_a_pair_of_geometric_siblings_as_steady():
    # Subtracting independently rounded logs can leave ~1e-16 noise across an
    # exactly constant-ratio series' changes; an exact zero-variance check
    # would mistake that noise for real movement and correlate it into a
    # spurious trade-off. Probe several ratios and starting magnitudes since
    # the defect is data-dependent - it doesn't show up for every input.
    ratios = (1.02, 1.08, 1.2, 0.9, 0.75, 3.3, 1.1, 0.5)
    magnitudes = (1e-4, 1.0, 50.0, 100.0, 1e6)
    for ratio in ratios:
        for magnitude in magnitudes:
            first = _geometric(magnitude, ratio, 10)
            second = _geometric(magnitude * 3.0, ratio, 10)
            assert tradeoff_pairs((("first", first), ("second", second))) == ()


def test_endpoint_interval_refuses_a_percentage_that_would_be_infinite():
    # The total log change (~1382) is finite, but exp() of it overflows
    # before it can become a percentage; before log ratios were made
    # overflow-safe this silently returned an infinite bound instead.
    with pytest.raises(SpecError, match="orders of magnitude"):
        endpoint_interval((1e-300, 1.0, 1e300))


def test_tradeoff_pairs_excludes_a_pair_exactly_at_the_threshold():
    # Correlation is scale-invariant: these two series' weekly log changes are
    # proportional to (1, 0, -1) and (-1, 1, 0), whose correlation is exactly
    # -0.5 - right at TRADEOFF_R, which must NOT count as "strongly negative".
    e = math.e
    first = (100.0, 100.0 * e, 100.0 * e, 100.0)
    second = (100.0, 100.0 / e, 100.0, 100.0)
    import statistics

    correlation = statistics.correlation(weekly_log_changes(first), weekly_log_changes(second))
    assert correlation == pytest.approx(TRADEOFF_R)
    assert tradeoff_pairs((("first", first), ("second", second))) == ()


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
