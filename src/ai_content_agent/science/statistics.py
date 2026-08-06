from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TypeVar

Number = TypeVar("Number", int, float)


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def sample_variance(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    avg = mean(values)
    return sum((value - avg) ** 2 for value in values) / (n - 1)


def sample_stddev(values: Sequence[float]) -> float:
    return math.sqrt(sample_variance(values))


def cohens_d(control: Sequence[float], variant: Sequence[float]) -> float:
    """Pooled effect size between two samples (positive means variant > control)."""
    n_control = len(control)
    n_variant = len(variant)
    if n_control < 2 or n_variant < 2:
        return 0.0
    var_control = sample_variance(control)
    var_variant = sample_variance(variant)
    pooled = math.sqrt(
        ((n_control - 1) * var_control + (n_variant - 1) * var_variant)
        / (n_control + n_variant - 2)
    )
    if pooled == 0:
        return 0.0
    return (mean(variant) - mean(control)) / pooled


def welch_t_statistic(control: Sequence[float], variant: Sequence[float]) -> float:
    n_control = len(control)
    n_variant = len(variant)
    if n_control < 2 or n_variant < 2:
        return 0.0
    var_control = sample_variance(control)
    var_variant = sample_variance(variant)
    denominator = math.sqrt(var_control / n_control + var_variant / n_variant)
    if denominator == 0:
        return 0.0
    return (mean(variant) - mean(control)) / denominator


def welch_satterthwaite_df(control: Sequence[float], variant: Sequence[float]) -> float:
    n_control = len(control)
    n_variant = len(variant)
    var_control = sample_variance(control)
    var_variant = sample_variance(variant)
    numerator = (var_control / n_control + var_variant / n_variant) ** 2
    denominator = (var_control / n_control) ** 2 / (n_control - 1) + (
        var_variant / n_variant
    ) ** 2 / (n_variant - 1)
    if denominator == 0:
        return 1.0
    return numerator / denominator


def normal_cdf(z: float) -> float:
    """Cumulative distribution function of the standard normal distribution."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _betacf(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta continued fraction (Numerical Recipes)."""
    MAX_ITERATIONS = 200
    EPS = 3.0e-7
    FPMIN = 1.0e-30

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAX_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def students_t_cdf(t: float, degrees_of_freedom: float) -> float:
    """Cumulative distribution function of Student's t distribution."""
    if degrees_of_freedom <= 0:
        return 0.5
    x = degrees_of_freedom / (degrees_of_freedom + t * t)
    if t >= 0:
        return 1.0 - 0.5 * betai(degrees_of_freedom / 2.0, 0.5, x)
    return 0.5 * betai(degrees_of_freedom / 2.0, 0.5, x)


def two_sample_p_value(control: Sequence[float], variant: Sequence[float]) -> float:
    """Two-tailed p-value from Welch's t-test (0.0..1.0)."""
    n_control = len(control)
    n_variant = len(variant)
    if n_control < 2 or n_variant < 2:
        return 1.0
    if sample_variance(control) == 0 and sample_variance(variant) == 0:
        if mean(control) == mean(variant):
            return 1.0
        return 0.0
    t = abs(welch_t_statistic(control, variant))
    df = welch_satterthwaite_df(control, variant)
    return 2.0 * (1.0 - students_t_cdf(t, df))
