import math
import random
import sys

import pytest

from coeftable.errors import SpecError
from coeftable.graph.honesty import (
    RESIDUAL_FAIL,
    RESIDUAL_WARN,
    TRADEOFF_R,
    endpoint_identity_gap,
    endpoint_interval,
    identity_gap,
    implied_series,
    infer_op,
    level_noise,
    log_ratio,
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


def test_endpoint_identity_gap_rejects_a_zero_parent_endpoint():
    with pytest.raises(SpecError, match="finite and non-zero"):
        endpoint_identity_gap((0.0, 10.0), ((0.0, 10.0),), "+")


def test_infer_op_reports_a_zero_parent_value_directly():
    with pytest.raises(SpecError, match="decomposition parent values must be finite and non-zero"):
        infer_op((0.0, 10.0), ((0.0, 10.0),))


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


def test_endpoint_interval_refuses_a_percentage_that_only_overflows_on_scaling():
    # exp(707) ~= 1.11e307 is finite - the exponential guard alone would let
    # it through - but multiplying by 100 to form a percentage pushes past
    # float range. Two equal weekly changes give a zero band so all three
    # returned percentages hit this scaling-only overflow.
    v2 = math.exp(353.5)
    v3 = math.exp(707.0)
    assert math.isfinite(v3)
    with pytest.raises(SpecError, match="orders of magnitude"):
        endpoint_interval((1.0, v2, v3))


def test_tradeoff_pairs_treats_near_one_geometric_siblings_as_steady():
    # With log changes around 1e-12, a purely relative tolerance
    # (1e-9 * 1e-12 = 1e-21) is far below the ~1e-16 noise that independent
    # divisions and logs actually introduce, so a genuinely steady pair can
    # look like it has real variance and correlate into a spurious
    # trade-off. These ratios reproduce that spurious -1.0 correlation
    # without the combined absolute+relative tolerance.
    first = tuple(100.0 * (1.0000000000003**index) for index in range(12))
    second = tuple(100.0 * (0.9999999999997**index) for index in range(12))
    assert tradeoff_pairs((("first", first), ("second", second))) == ()


def test_weekly_log_changes_uses_log_subtraction_for_a_subnormal_quotient():
    # The smallest subnormal divided by 1.5 rounds right back to itself,
    # silently losing log(1.5) - the direct-quotient path must be skipped
    # for a subnormal quotient, not only a zero or infinite one.
    smallest_subnormal = 5e-324
    changes = weekly_log_changes((1.5, smallest_subnormal, smallest_subnormal * 2))
    assert changes[0] == pytest.approx(math.log(smallest_subnormal) - math.log(1.5))


def test_ribbon_bounds_refuses_a_factor_that_would_be_infinite():
    # This series' weekly log changes swing by ~+/-1382, large enough that
    # the ribbon's own +/-2 sigma exponential overflows even though the
    # endpoint percentage guard is never exercised.
    series = (1e-300, 1e300, 1e-300, 1e300)
    with pytest.raises(SpecError, match="orders of magnitude"):
        ribbon_bounds(series)


def test_ribbon_bounds_refuses_a_multiplied_bound_that_would_be_infinite():
    # Each level here is close enough to float max, and the +/-2 sigma noise
    # small enough, that the ribbon FACTOR itself is finite (~1.01) - the
    # exponential guard alone would let this through unnoticed - but
    # multiplying an already-near-max, finite, positive level by that
    # finite factor still overflows to infinity.
    near_max = sys.float_info.max
    series = (near_max * 0.99, near_max * 0.999, near_max * 0.995, near_max * 0.998)
    sigma = level_noise(series)
    factor = math.exp(2.0 * sigma)
    assert math.isfinite(factor)
    with pytest.raises(SpecError, match="orders of magnitude"):
        ribbon_bounds(series)


def test_implied_series_normalizes_large_integer_children_before_combining():
    # 10**200 * 10**200 stays an exact, arbitrary-precision Python int if
    # left unconverted, so a later math.isfinite() raises OverflowError
    # instead of the module reporting the overflow as SpecError like every
    # other overflow in this module does.
    huge = 10**200
    result = implied_series(((huge, huge),), "x")
    assert result == (float(huge), float(huge))
    assert all(math.isfinite(value) for value in result)

    with pytest.raises(SpecError, match="orders of magnitude"):
        implied_series(((huge,), (huge,)), "x")


def test_ribbon_domain_stays_nondegenerate_for_a_flat_subnormal_series():
    # 0.1 * span underflows to exactly 0.0 for a subnormal-magnitude flat
    # series, so the naive padded bounds come out equal even though the
    # docstring promises a non-degenerate domain.
    smallest_subnormal = 5e-324
    flat = (smallest_subnormal, smallest_subnormal, smallest_subnormal)
    lower, upper = ribbon_bounds(flat)
    lo, hi = ribbon_domain(flat, lower, upper)
    assert hi > lo
    assert math.isfinite(lo)
    assert math.isfinite(hi)


def test_log_ratio_stays_finite_for_large_but_safe_integer_inputs():
    assert log_ratio(10**400, 10**399) == pytest.approx(math.log(10.0))


def test_log_ratio_refuses_inputs_that_cannot_produce_a_finite_ratio():
    # Every input shape that previously let a raw OverflowError,
    # ZeroDivisionError, or ValueError escape log_ratio instead of SpecError.
    huge = 10**400
    cases = (
        (huge, 10**50),  # the direct quotient itself overflows the divide
        (float(10**300), huge),  # converting the huge side overflows
        (5.0, 0.0),  # division by zero
        (0.0, 5.0),  # log(0.0) is undefined on the fallback path
        (-5.0, 2.0),  # log() of a negative number is undefined
        (float("nan"), 5.0),  # NaN never resolves to a finite log
    )
    for numerator, denominator in cases:
        with pytest.raises(SpecError):
            log_ratio(numerator, denominator)


def _random_positive_finite(rng: random.Random) -> float:
    """A positive float spanning subnormal to near-max magnitude."""
    exponent = rng.uniform(-323, 308)
    mantissa = rng.uniform(1.0, 9.999999)
    return mantissa * (10.0**exponent)


def _random_finite(rng: random.Random) -> float:
    """A signed float spanning subnormal to near-max magnitude."""
    return rng.choice((1.0, -1.0)) * _random_positive_finite(rng)


def _flatten(value):
    if isinstance(value, tuple):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


_PROBE_TRIALS = 400


def test_every_public_function_stays_finite_or_raises_spec_error_across_magnitudes():
    # Several hundred random series spanning subnormal to near-max
    # magnitude, run through every public function in this module. An
    # uncaught exception of any other type, or a non-finite float slipping
    # past a return, fails the test - closing the overflow defect class
    # instead of only the one multiplication site that prompted this.
    rng = random.Random(20260827)  # noqa: S311  -- deterministic fuzz seed, not security-sensitive
    for _ in range(_PROBE_TRIALS):
        length = rng.randint(3, 8)
        series = tuple(_random_positive_finite(rng) for _ in range(length))

        for fn in (weekly_log_changes, level_noise, endpoint_interval, ribbon_bounds):
            try:
                result = fn(series)
            except SpecError:
                continue
            assert all(math.isfinite(value) for value in _flatten(result))

        try:
            lower, upper = ribbon_bounds(series)
            domain = ribbon_domain(series, lower, upper)
            assert all(math.isfinite(value) for value in domain)
        except SpecError:
            pass

        children = tuple(
            tuple(_random_finite(rng) for _ in range(length)) for _ in range(rng.randint(1, 4))
        )
        op = rng.choice(("+", "x"))
        try:
            implied = implied_series(children, op)
            assert all(math.isfinite(value) for value in implied)
        except SpecError:
            pass

        parent = tuple(_random_finite(rng) for _ in range(length))
        try:
            gap = identity_gap(parent, children, op)
            assert math.isfinite(gap)
        except SpecError:
            pass

        named = tuple(
            (f"sibling-{index}", tuple(_random_positive_finite(rng) for _ in range(length)))
            for index in range(rng.randint(2, 4))
        )
        try:
            pairs = tradeoff_pairs(named)
            assert all(math.isfinite(correlation) for _, _, correlation in pairs)
        except SpecError:
            pass


def _random_huge_int(rng: random.Random) -> int:
    """A signed Python int large enough to stay arbitrary-precision through
    arithmetic instead of ever implicitly becoming a machine float."""
    exponent = rng.randint(150, 500)
    return rng.choice((1, -1)) * (10**exponent + rng.randint(0, 999))


_INT_PROBE_TRIALS = 200
_SUBNORMAL_FLAT_MAGNITUDES = (5e-324, 4.9e-324, 1e-323, 2e-323, 1e-320, 1e-310, 1e-300)


def test_public_functions_survive_large_integers_and_flat_subnormal_series():
    # Extends the random-float magnitude sweep above along the two axes it
    # never exercises: raw Python ints large enough to stay
    # arbitrary-precision through arithmetic (implied_series, log_ratio),
    # and perfectly flat series pinned at subnormal magnitude
    # (ribbon_domain). Both previously let a raw OverflowError or a
    # degenerate (lo == hi) domain escape instead of SpecError / a
    # non-degenerate, finite result.
    rng = random.Random(20260827)  # noqa: S311  -- deterministic fuzz seed, not security-sensitive
    probed = 0

    for _ in range(_INT_PROBE_TRIALS):
        length = rng.randint(1, 4)
        children = tuple(
            tuple(_random_huge_int(rng) for _ in range(length)) for _ in range(rng.randint(1, 3))
        )
        op = rng.choice(("+", "x"))
        probed += 1
        try:
            implied = implied_series(children, op)
            assert all(math.isfinite(value) for value in implied)
        except SpecError:
            pass

        numerator = rng.choice((_random_huge_int(rng), _random_positive_finite(rng)))
        denominator = rng.choice((_random_huge_int(rng), _random_positive_finite(rng)))
        probed += 1
        try:
            ratio = log_ratio(numerator, denominator)
            assert math.isfinite(ratio)
        except SpecError:
            pass

    for magnitude in _SUBNORMAL_FLAT_MAGNITUDES:
        flat = (magnitude, magnitude, magnitude)
        probed += 1
        lower, upper = ribbon_bounds(flat)
        lo, hi = ribbon_domain(flat, lower, upper)
        assert hi > lo
        assert math.isfinite(lo)
        assert math.isfinite(hi)

    assert probed == 2 * _INT_PROBE_TRIALS + len(_SUBNORMAL_FLAT_MAGNITUDES)


def test_log_ratio_refuses_two_negative_operands():
    # Their quotient is positive, so a check on the ratio alone lets them
    # through -- but a negative level has no logarithm, and the multiplicative
    # noise model this feeds is undefined there.
    with pytest.raises(SpecError, match="finite, positive"):
        log_ratio(-2.0, -1.0)
    with pytest.raises(SpecError, match="finite, positive"):
        log_ratio(-2.0, -2.0)


def test_log_ratio_refuses_a_single_non_positive_operand():
    for numerator, denominator in ((-2.0, 1.0), (2.0, -1.0), (0.0, 1.0), (1.0, 0.0)):
        with pytest.raises(SpecError, match="finite, positive"):
            log_ratio(numerator, denominator)


def test_log_ratio_still_accepts_two_positives():
    assert log_ratio(2.0, 1.0) == pytest.approx(math.log(2.0))
