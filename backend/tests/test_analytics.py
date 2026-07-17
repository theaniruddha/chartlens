from datetime import UTC, datetime

from app.analytics.trends import (
    SeriesPoint,
    classify_trend,
    delta,
    dual_trend_aligned,
    is_stale,
    ols_slope_per_month,
)


def _pts(values: list[float], months: list[int]) -> list[SeriesPoint]:
    return [
        SeriesPoint(time=datetime(2026, m, 1, tzinfo=UTC), value=v)
        for v, m in zip(values, months, strict=True)
    ]


def test_delta():
    assert delta(_pts([6.0, 7.0], [1, 5])) == 1.0
    assert delta(_pts([6.0], [1])) is None


def test_ols_slope_known_series():
    # 1.0 unit rise per month exactly
    pts = _pts([1.0, 2.0, 3.0], [1, 2, 3])
    slope = ols_slope_per_month(pts)
    assert slope is not None
    assert abs(slope - 1.0) < 0.05


def test_ols_requires_three_points():
    assert ols_slope_per_month(_pts([1.0, 2.0], [1, 2])) is None


def test_classify_rising_and_stable():
    rising = classify_trend("hba1c", _pts([6.2, 7.0, 7.8], [1, 4, 7]))
    assert rising.direction == "rising"
    assert rising.quality == "ok"
    stable = classify_trend("sbp", _pts([128, 126, 130], [1, 4, 7]))
    assert stable.direction == "stable"


def test_classify_insufficient_data():
    assert classify_trend("hba1c", []).direction == "insufficient_data"
    assert classify_trend("hba1c", _pts([6.0, 6.5], [1, 3])).direction == "insufficient_data"


def test_freshness():
    now = datetime(2026, 7, 16, tzinfo=UTC)
    assert is_stale("hba1c", datetime(2025, 6, 1, tzinfo=UTC), now) is True
    assert is_stale("hba1c", datetime(2026, 5, 1, tzinfo=UTC), now) is False
    assert is_stale("hba1c", None, now) is True


def test_dual_trend_alignment():
    a = classify_trend("hba1c", _pts([6.2, 7.0, 7.8], [1, 4, 7]))
    b = classify_trend("weight", _pts([82, 86, 90], [1, 4, 7]))
    c = classify_trend("sbp", _pts([128, 126, 130], [1, 4, 7]))
    assert dual_trend_aligned(a, b) is True
    assert dual_trend_aligned(a, c) is False


def test_trend_window_ignores_ancient_history():
    # Mohammad regression: a 2017 value must not dilute a recent decline.
    from datetime import UTC, datetime

    now = datetime(2026, 7, 17, tzinfo=UTC)
    pts = [
        SeriesPoint(time=datetime(2017, 10, 25, tzinfo=UTC), value=16.0),
        SeriesPoint(time=datetime(2024, 8, 1, tzinfo=UTC), value=12.0),
        SeriesPoint(time=datetime(2025, 9, 1, tzinfo=UTC), value=10.0),
        SeriesPoint(time=datetime(2026, 7, 1, tzinfo=UTC), value=8.0),
    ]
    result = classify_trend("hemoglobin", pts, now=now)
    assert result.direction == "falling"
    assert result.n_points == 3  # only windowed points vote
    assert result.latest_value == 8.0


def test_hemoglobin_threshold_catches_meaningful_decline():
    pts = _pts([13.0, 12.0, 11.0], [1, 4, 7])
    assert classify_trend("hemoglobin", pts).direction == "falling"
