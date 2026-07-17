"""Deterministic analytics: deltas, OLS slope, freshness, trend classification,
dual-trend alignment, and series data quality. Pure functions, no I/O."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DAYS_PER_MONTH = 30.44

# Per-metric monthly-slope thresholds above which a trend is "rising"
# (or below negative threshold, "falling"). Defaults are conservative.
SLOPE_THRESHOLDS: dict[str, float] = {
    "hba1c": 0.15,       # % points / month
    "sbp": 2.0,          # mmHg / month
    "dbp": 1.5,
    "weight": 0.8,       # kg / month
    "ldl": 4.0,          # mg/dL / month
    "egfr": 1.5,         # mL/min / month (falling is the concern)
    "creatinine": 0.05,
    "hemoglobin": 0.1,   # g/dL / month (falling is the concern)
    "glucose": 5.0,      # mg/dL / month
    "potassium": 0.08,
}

# Only points within this window vote on the trend direction; older history
# still informs latest/previous values but must not dilute a recent change.
TREND_WINDOW_MONTHS = 24
DEFAULT_SLOPE_THRESHOLD = 0.5

FRESHNESS_MAX_AGE_DAYS: dict[str, int] = {
    "hba1c": 200,
    "sbp": 400,
    "ldl": 400,
    "egfr": 400,
}
DEFAULT_MAX_AGE_DAYS = 730

# Related-metric map for dual-trend checks.
RELATED_METRICS: dict[str, list[str]] = {
    "hba1c": ["weight", "glucose"],
    "sbp": ["dbp", "weight"],
    "egfr": ["creatinine"],
    "ldl": ["weight"],
}


@dataclass
class SeriesPoint:
    time: datetime
    value: float


@dataclass
class TrendResult:
    metric_code: str
    n_points: int
    latest_value: float | None
    latest_time: datetime | None
    previous_value: float | None
    delta: float | None
    slope_per_month: float | None
    direction: str  # rising | falling | stable | insufficient_data
    quality: str  # ok | sparse | insufficient_data


def delta(points: list[SeriesPoint]) -> float | None:
    if len(points) < 2:
        return None
    return points[-1].value - points[-2].value


def ols_slope_per_month(points: list[SeriesPoint]) -> float | None:
    """Ordinary least squares slope in value-units per month."""
    if len(points) < 3:
        return None
    t0 = points[0].time
    xs = [(p.time - t0).total_seconds() / (86400 * DAYS_PER_MONTH) for p in points]
    ys = [p.value for p in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx


def classify_trend(
    metric_code: str,
    points: list[SeriesPoint],
    now: datetime | None = None,
    window_months: int = TREND_WINDOW_MONTHS,
) -> TrendResult:
    pts = sorted(points, key=lambda p: p.time)
    n = len(pts)
    latest = pts[-1] if pts else None
    prev = pts[-2] if n >= 2 else None

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=window_months * DAYS_PER_MONTH)
    recent = [p for p in pts if p.time >= cutoff]
    slope = ols_slope_per_month(recent)
    d = delta(recent)
    rn = len(recent)

    threshold = SLOPE_THRESHOLDS.get(metric_code, DEFAULT_SLOPE_THRESHOLD)
    if n == 0:
        direction, quality = "insufficient_data", "insufficient_data"
    elif slope is None:
        direction, quality = "insufficient_data", "sparse"
    elif slope > threshold:
        direction, quality = "rising", "ok" if rn >= 3 else "sparse"
    elif slope < -threshold:
        direction, quality = "falling", "ok" if rn >= 3 else "sparse"
    else:
        direction, quality = "stable", "ok" if rn >= 3 else "sparse"

    return TrendResult(
        metric_code=metric_code,
        n_points=rn,
        latest_value=latest.value if latest else None,
        latest_time=latest.time if latest else None,
        previous_value=prev.value if prev else None,
        delta=d,
        slope_per_month=slope,
        direction=direction,
        quality=quality,
    )


def is_stale(metric_code: str, latest_time: datetime | None, now: datetime | None = None) -> bool:
    if latest_time is None:
        return True
    now = now or datetime.now(UTC)
    max_age = FRESHNESS_MAX_AGE_DAYS.get(metric_code, DEFAULT_MAX_AGE_DAYS)
    return (now - latest_time).days > max_age


def dual_trend_aligned(a: TrendResult, b: TrendResult) -> bool:
    """Two related metrics moving in the same concerning direction."""
    if a.direction not in ("rising", "falling") or b.direction not in ("rising", "falling"):
        return False
    return a.direction == b.direction
