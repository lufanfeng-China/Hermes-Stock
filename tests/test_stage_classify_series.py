"""Parity contract: vectorised stage series must equal the day-by-day classifier.

`classify_stage_series` is the batch path used to build the full-market stage
history.  If it ever disagrees with `classify_stage`, the history silently
diverges from what the stock-analysis page shows.  These tests pin the two
implementations together on every synthetic fixture, for every bar index.

The rule is strict: for every t >= MIN_DAYS-1 the vectorised row must return the
same (region, stage) as calling the scalar classifier on df.iloc[:t+1].
"""
import numpy as np
import pandas as pd
import pytest

from app.stage_classify import MIN_DAYS, classify_stage
from app.stage_classify_series import classify_stage_series


def bars(closes, volumes=None):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    if volumes is None:
        volumes = [1e6] * n
    return pd.DataFrame(
        dict(open=closes, high=highs, low=lows, close=closes, volume=volumes),
        index=dates,
    )


def flat(v, n):
    return [float(v)] * n


def lin(a, b, n):
    return list(np.linspace(a, b, n))


FIXTURES = {
    "D2主跌": ([200.0 - i for i in range(90)], None),
    "U2主升": ([100.0 + i for i in range(90)], None),
    "D1破位": (flat(110, 85) + [109, 108, 107, 106, 105], None),
    "D3中继": (lin(110, 41, 70) + lin(41.5, 51, 20), None),
    "U3中继": (lin(100, 170, 70) + lin(168.5, 159, 20), None),
    "U4赶顶": (lin(100, 110, 60) + lin(110, 210, 30), None),
    "U1初期": (flat(100, 80) + lin(100, 110, 10), None),
    "B1盘整": ([52 - 0.02 * i for i in range(90)], None),
    "T1高位": ([48 + 0.02 * i for i in range(90)], None),
    "B2回升": (lin(70, 50, 60) + flat(50, 15) + lin(50, 52, 15), [1e6] * 89 + [2.5e6]),
    "B3回踩": (lin(60, 50, 40) + lin(50, 60, 15) + lin(60, 53, 20) + flat(53, 15), None),
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_series_matches_scalar_classifier_every_bar(name):
    closes, volumes = FIXTURES[name]
    frame = bars(closes, volumes)
    series = classify_stage_series(frame)
    assert len(series) == len(frame)

    mismatches = []
    for t in range(MIN_DAYS - 1, len(frame)):
        expected = classify_stage(frame.iloc[: t + 1])
        row = series.iloc[t]
        if (row["region"], row["stage"]) != (expected["region"], expected["stage"]):
            mismatches.append((frame.index[t].date(), row["region"], row["stage"],
                               expected["region"], expected["stage"]))
    assert not mismatches, f"{name} diverged at {mismatches[:5]}"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_series_evidence_matches_scalar_classifier_every_bar(name):
    closes, volumes = FIXTURES[name]
    frame = bars(closes, volumes)
    series = classify_stage_series(frame)
    fields = ("ma5", "ma10", "ma20", "ma60", "slope20", "slope60", "bias20",
              "pos_high_60", "pos_low_60", "vol_ratio")

    for t in range(MIN_DAYS - 1, len(frame)):
        expected = classify_stage(frame.iloc[: t + 1])["evidence"]
        row = series.iloc[t]
        for field in fields:
            got = row[field]
            want = expected[field]
            assert abs(float(got) - float(want)) <= 1e-9, (
                f"{name} {field} diverged at {frame.index[t].date()}: {got} vs {want}")


def test_rows_before_minimum_history_are_marked_invalid():
    frame = bars(lin(100, 200, 90))
    series = classify_stage_series(frame)
    assert series.iloc[: MIN_DAYS - 1]["stage"].isna().all()
    assert not series.iloc[: MIN_DAYS - 1]["valid"].any()
    assert series.iloc[MIN_DAYS - 1 :]["stage"].notna().all()
    assert series.iloc[MIN_DAYS - 1 :]["valid"].all()


def test_series_is_ascending_and_carries_the_trading_day():
    frame = bars(lin(100, 200, 90))
    series = classify_stage_series(frame)
    assert series["trading_day"].is_monotonic_increasing
    assert str(series.iloc[-1]["trading_day"]) == frame.index[-1].strftime("%Y-%m-%d")


def test_series_marks_suspended_placeholder_rows_invalid_without_shifting():
    """0.00 rows must come back as valid=False, aligned, with later bars unchanged."""
    closes = lin(100, 170, 70) + lin(168.5, 159, 20)
    clean = bars(closes)
    dirty_closes = closes[:61] + [0.0] + closes[61:72] + [0.0] + closes[72:83] + [0.0] + closes[83:]
    dirty = bars(dirty_closes)
    positions = [index for index, close in enumerate(dirty_closes) if close == 0.0]
    assert positions == [61, 73, 85]

    series = classify_stage_series(dirty)
    assert len(series) == len(dirty)
    for position in positions:
        assert not bool(series.iloc[position]["valid"])
        assert pd.isna(series.iloc[position]["stage"])

    clean_series = classify_stage_series(clean)
    for position in range(len(dirty)):
        if position in positions:
            continue
        shifted = position - sum(1 for p in positions if p < position)
        got = series.iloc[position]["stage"]
        want = clean_series.iloc[shifted]["stage"]
        if pd.isna(got) and pd.isna(want):
            continue
        assert got == want, position
