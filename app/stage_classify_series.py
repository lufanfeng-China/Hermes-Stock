"""Vectorised lifecycle-stage series for one stock.

Batch counterpart of :func:`app.stage_classify.classify_stage`: it answers the
stage question for **every** bar, using only data up to that bar, so the result
can be written to a history parquet without lookahead.

Parity is exact, not approximate
--------------------------------
The scalar classifier sums each MA window with an incremental running total
(``running += v; running -= v[i-window]``).  pandas' rolling mean accumulates
differently, so the last mantissa bits differ and comparisons such as
``ma5 > ma10`` or ``slope60 <= FLAT_SLOPE`` flip on exact ties — real QFQ data
(BSE names, suspended days) contains plenty of those.  The first parity run on
200 stocks x 3 years found 123 stage disagreements out of 132,724 bars for
exactly this reason.

This module therefore reuses the *same* running-sum arithmetic as the scalar
path (one O(n) pass per window), plus the same left-to-right five-day volume sum.
Only then is the vectorised history guaranteed to match what the page shows.

Thresholds are imported from :mod:`app.stage_classify` so the two paths cannot
drift apart.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.stage_classify import (
    B3_MAX_PULLBACK,
    U1_MAX_DAYS,
    BASE_MAX_RANGE_POS,
    BIAS_CLIMAX,
    FLAT_SLOPE,
    MIN_DAYS,
    TOP_MAX_DIST_FROM_HIGH,
    VOL_BREAKOUT,
    prepare_bars,
)

_SERIES_COLUMNS = [
    "trading_day", "valid", "region", "stage",
    "ma5", "ma10", "ma20", "ma60",
    "slope20", "slope60", "slope20_prev",
    "bias20", "pos_high_60", "pos_low_60", "range_pos_60", "vol_ratio",
    "high_20", "low_20", "high_60", "low_60",
]

_EVIDENCE_COLUMNS = [
    "ma5", "ma10", "ma20", "ma60", "slope20", "slope60", "slope20_prev",
    "bias20", "pos_high_60", "pos_low_60", "range_pos_60", "vol_ratio",
    "high_20", "low_20", "high_60", "low_60",
]


def _rolling_mean_like_scalar(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing mean with the scalar classifier's exact accumulation order.

    ``app.stage_classify._rolling_mean`` keeps one running total and subtracts
    the element leaving the window.  Reproducing that order keeps the two paths
    bit-identical, which matters because the stage rules compare MAs with ``>``
    and ``<`` (ties are common on illiquid names).
    """
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    running = 0.0
    for i in range(n):
        running += values[i]
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def _shift(values: np.ndarray, periods: int) -> np.ndarray:
    """Shift forward by `periods`, padding the head with NaN."""
    out = np.full(len(values), np.nan, dtype=float)
    if periods <= 0:
        return values.astype(float, copy=True)
    if periods < len(values):
        out[periods:] = values[:-periods]
    return out


def _slope_like_scalar(ma: np.ndarray, ago: int) -> np.ndarray:
    """Percent change versus `ago` bars earlier; missing/zero base -> 0.0."""
    then = _shift(ma, ago)
    usable = np.isfinite(ma) & np.isfinite(then) & (then != 0)
    out = np.zeros(len(ma), dtype=float)
    out[usable] = (ma[usable] - then[usable]) / then[usable]
    return out


def _safe_ratio_like_scalar(numerator: np.ndarray, denominator: np.ndarray, default: float) -> np.ndarray:
    usable = np.isfinite(denominator) & (denominator != 0)
    out = np.full(len(numerator), default, dtype=float)
    out[usable] = numerator[usable] / denominator[usable]
    return out


def _prior5_mean_like_scalar(volumes: np.ndarray) -> np.ndarray:
    """Mean of the five bars before each bar, summed left-to-right like sum(list)."""
    v1 = _shift(volumes, 5)
    v2 = _shift(volumes, 4)
    v3 = _shift(volumes, 3)
    v4 = _shift(volumes, 2)
    v5 = _shift(volumes, 1)
    return ((((v1 + v2) + v3) + v4) + v5) / 5.0


def _round_like_scalar(values: np.ndarray, digits: int) -> np.ndarray:
    """Element-wise ``round()`` (the scalar path rounds Python floats)."""
    return np.array([round(float(v), digits) if np.isfinite(v) else np.nan for v in values], dtype=float)


def _trading_day_labels(index: pd.Index) -> list[str]:
    if isinstance(index, pd.DatetimeIndex):
        return [stamp.strftime("%Y-%m-%d") for stamp in index]
    return [str(value) for value in index]


def classify_stage_series(df: pd.DataFrame) -> pd.DataFrame:
    """Classify every bar of one stock using only data available up to that bar.

    Suspended placeholder rows (0.00 prices) are excluded from the arithmetic and
    reported back as ``valid=False`` rows, so the returned frame stays aligned to
    the input index.  This matches the scalar classifier, which drops them too.
    """
    if df.empty:
        return pd.DataFrame(columns=_SERIES_COLUMNS)

    work = prepare_bars(df)
    if work.empty:
        empty = pd.DataFrame({
            "trading_day": _trading_day_labels(df.index),
            "valid": False,
            "region": None,
            "stage": None,
        }, index=df.index)
        for column in _EVIDENCE_COLUMNS:
            empty[column] = np.nan
        return empty[_SERIES_COLUMNS]

    closes = work["close"].astype(float).to_numpy()
    highs = work["high"].astype(float).to_numpy()
    lows = work["low"].astype(float).to_numpy()
    volumes = work["volume"].astype(float).to_numpy()
    n = len(closes)

    ma5 = _rolling_mean_like_scalar(closes, 5)
    ma10 = _rolling_mean_like_scalar(closes, 10)
    ma20 = _rolling_mean_like_scalar(closes, 20)
    ma60 = _rolling_mean_like_scalar(closes, 60)

    slope20 = _slope_like_scalar(ma20, 5)
    slope60 = _slope_like_scalar(ma60, 10)
    slope20_prev = _slope_like_scalar(_shift(ma20, 5), 5)

    # max/min are exact comparisons, so pandas rolling is safe here
    high_60 = pd.Series(highs).rolling(60).max().to_numpy()
    low_60 = pd.Series(lows).rolling(60).min().to_numpy()
    high_20 = pd.Series(highs).rolling(20).max().to_numpy()
    low_20 = pd.Series(lows).rolling(20).min().to_numpy()
    mid_60 = (high_60 + low_60) / 2.0

    pos_high_60 = _safe_ratio_like_scalar(closes - high_60, high_60, 0.0)
    pos_low_60 = _safe_ratio_like_scalar(closes - low_60, low_60, 0.0)
    bias20 = _safe_ratio_like_scalar(closes - ma20, ma20, 0.0)
    range_span = high_60 - low_60
    with np.errstate(invalid="ignore", divide="ignore"):
        range_pos_60 = np.where(range_span > 0, (closes - low_60) / range_span, 0.5)
    range_pos_60 = np.where(np.isfinite(range_pos_60), range_pos_60, 0.5)
    vol_ratio = _safe_ratio_like_scalar(volumes, _prior5_mean_like_scalar(volumes), 1.0)

    valid = (np.arange(n) >= (MIN_DAYS - 1)) & np.isfinite(ma60) & np.isfinite(ma20) \
        & np.isfinite(high_60) & np.isfinite(low_60)
    at_valid = valid  # alias for readability in the rules below

    with np.errstate(invalid="ignore"):
        up_mid = slope60 > FLAT_SLOPE
        down_mid = slope60 < -FLAT_SLOPE
        flat_mid = ~up_mid & ~down_mid

        region = np.full(n, None, dtype=object)
        up_region = np.where((closes > ma60) | (range_pos_60 > BASE_MAX_RANGE_POS), "up", "base")
        down_region = np.where((closes < ma60) | (pos_high_60 < -TOP_MAX_DIST_FROM_HIGH), "down", "top")
        region[up_mid] = up_region[up_mid]
        region[down_mid] = down_region[down_mid]

        flat_up = flat_mid & (slope20 > FLAT_SLOPE) & (closes > ma60)
        flat_down = flat_mid & (slope20 < -FLAT_SLOPE) & (closes < ma60)
        flat_rest = flat_mid & ~flat_up & ~flat_down
        region[flat_up] = "up"
        region[flat_down] = "down"
        region[flat_rest] = np.where(closes[flat_rest] < mid_60[flat_rest], "base", "top")

        stage = np.full(n, None, dtype=object)

        def assign(mask: np.ndarray, code: str) -> None:
            targets = mask & (stage == None)  # noqa: E711 - elementwise None test
            stage[targets] = code

        # --- events that live inside a trend region (they never rewrite it) ---
        near_bottom = (range_pos_60 <= BASE_MAX_RANGE_POS) | (pos_high_60 <= -TOP_MAX_DIST_FROM_HIGH)
        b2 = ((region == "down") | (region == "base")) & near_bottom \
            & (closes > ma20) & (vol_ratio >= VOL_BREAKOUT) & (slope20 > 0)
        assign(b2, "B2")

        b3 = ((region == "down") | (region == "base")) \
            & (low_20 > low_60) & (high_20 > ma20) & (closes < ma20) \
            & (slope60 >= -FLAT_SLOPE) & (range_pos_60 <= BASE_MAX_RANGE_POS) \
            & (bias20 >= B3_MAX_PULLBACK)
        assign(b3, "B3")

        # --- per-region stages, in the scalar classifier's priority order ---
        in_down = (region == "down") & at_valid
        assign(in_down & (slope20 < 0) & (slope20_prev >= 0), "D1")
        assign(in_down & (ma5 > ma10), "D3")
        bearish = (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)
        assign(in_down & bearish, "D2")
        assign(in_down, "D3")

        in_base = (region == "base") & at_valid
        # MA60 仍上行时跌破 MA60 且落在区间下半 = 上升回撤，不是底部盘整
        assign(in_base & (slope60 > FLAT_SLOPE), "R1")
        assign(in_base, "B1")

        in_up = (region == "up") & at_valid
        assign(in_up & (bias20 >= BIAS_CLIMAX), "U4")
        ma60_prev = _shift(ma60, 1)
        close_prev = _shift(closes, 1)
        # 最近一次「收复 MA60」的位置，以及之后是否一直站稳
        reclaim = np.isfinite(ma60_prev) & (close_prev <= ma60_prev) & (closes > ma60)
        positions = np.arange(n)
        last_reclaim = np.maximum.accumulate(np.where(reclaim, positions, -1))
        has_reclaim = last_reclaim >= 0
        safe_last = np.where(has_reclaim, last_reclaim, 0)
        below = closes <= ma60
        cum_below = np.cumsum(below)
        below_since = cum_below - np.where(has_reclaim, cum_below[safe_last] - below[safe_last], 0)
        days_since = np.where(has_reclaim, positions - safe_last, np.inf)
        reclaimed = (has_reclaim & (below_since == 0) & (days_since <= U1_MAX_DAYS)
                     & (np.abs(bias20) < 0.05) & (slope60 > -FLAT_SLOPE))
        assign(in_up & reclaimed, "U1")
        assign(in_up & (ma5 < ma10), "U3")
        # 主升要求站上 MA20；跌破 MA20 的短期回踩归上升中继
        assign(in_up & (closes > ma20), "U2")
        assign(in_up, "U3")

        in_top = (region == "top") & at_valid
        # MA60 下行、价格仍在 MA60 上方且贴近高点 = 下跌反弹，不是高位震荡
        assign(in_top & (slope60 < -FLAT_SLOPE), "R2")
        assign(in_top, "T1")

    out = pd.DataFrame({
        "trading_day": _trading_day_labels(work.index),
        "valid": valid,
        "region": np.where(valid, region, None),
        "stage": np.where(valid, stage, None),
        "ma5": _round_like_scalar(ma5, 3),
        "ma10": _round_like_scalar(ma10, 3),
        "ma20": _round_like_scalar(ma20, 3),
        "ma60": _round_like_scalar(ma60, 3),
        "slope20": _round_like_scalar(slope20, 5),
        "slope60": _round_like_scalar(slope60, 5),
        "slope20_prev": _round_like_scalar(slope20_prev, 5),
        "bias20": _round_like_scalar(bias20, 4),
        "pos_high_60": _round_like_scalar(pos_high_60, 4),
        "pos_low_60": _round_like_scalar(pos_low_60, 4),
        "range_pos_60": _round_like_scalar(range_pos_60, 4),
        "vol_ratio": _round_like_scalar(vol_ratio, 3),
        "high_20": _round_like_scalar(high_20, 3),
        "low_20": _round_like_scalar(low_20, 3),
        "high_60": _round_like_scalar(high_60, 3),
        "low_60": _round_like_scalar(low_60, 3),
    }, index=work.index)

    out = out[_SERIES_COLUMNS]
    if not valid.all():
        out.loc[~valid, _EVIDENCE_COLUMNS] = np.nan
        out.loc[~valid, ["region", "stage"]] = None

    if len(work) != len(df):
        # re-align to the caller's index: suspended placeholder rows come back as
        # valid=False rather than shifting every subsequent bar
        out = out.reindex(df.index)
        out["trading_day"] = _trading_day_labels(df.index)
        out["valid"] = out["valid"].fillna(False).astype(bool)
    return out


def summarise_series_parity(df: pd.DataFrame) -> dict[str, Any]:
    """Compare the vectorised path against the scalar classifier bar by bar.

    Returns counts plus the first few divergences, so a build can refuse to
    write history when the two implementations disagree.
    """
    from app.stage_classify import classify_stage

    series = classify_stage_series(df)
    checked = 0
    skipped = 0
    region_mismatch, stage_mismatch, evidence_mismatch = 0, 0, 0
    first: list[dict[str, Any]] = []

    for t in range(MIN_DAYS - 1, len(df)):
        row = series.iloc[t]
        if not bool(row["valid"]):
            # suspended placeholder bar: no stage is published for that day, and the
            # scalar classifier answers for the last *traded* bar, so there is nothing
            # to compare here
            skipped += 1
            continue
        expected = classify_stage(df.iloc[: t + 1])
        checked += 1
        if row["region"] != expected["region"]:
            region_mismatch += 1
        if row["stage"] != expected["stage"]:
            stage_mismatch += 1
        for field in ("ma5", "ma10", "ma20", "ma60", "slope20", "slope60",
                      "bias20", "pos_high_60", "pos_low_60", "range_pos_60", "vol_ratio"):
            got, want = row[field], expected["evidence"][field]
            if not (pd.isna(got) and pd.isna(want)) and abs(float(got) - float(want)) > 1e-9:
                evidence_mismatch += 1
                break
        if len(first) < 5 and (row["region"], row["stage"]) != (expected["region"], expected["stage"]):
            first.append({
                "trading_day": row["trading_day"],
                "vectorised": [row["region"], row["stage"]],
                "scalar": [expected["region"], expected["stage"]],
            })

    return {
        "checked": checked,
        "skipped_placeholder_bars": skipped,
        "region_mismatch": region_mismatch,
        "stage_mismatch": stage_mismatch,
        "evidence_mismatch": evidence_mismatch,
        "first_divergences": first,
    }
