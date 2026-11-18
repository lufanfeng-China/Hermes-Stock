"""Descriptive equal-volume QFQ intraday response; no Wyckoff phase classification."""
from __future__ import annotations

from statistics import median
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import TDX_QFQ_EXPORT_DIR
from app.wyckoff_events import clean_wyckoff_bars

_SSE_INDEX_PATH = TDX_QFQ_EXPORT_DIR.parent.parent / 'vipdoc/sh/lday/sh000001.day'
_INDEX_DAY = np.dtype([('date', '<i4'), ('open', '<i4'), ('high', '<i4'),
                       ('low', '<i4'), ('close', '<i4'), ('amount', '<f4'),
                       ('volume', '<u4'), ('reserved', '<u4')])


def load_sse_intraday_index(path: Path = _SSE_INDEX_PATH) -> pd.DataFrame | None:
    """Read local SSE Composite daily open/close; no online/raw-stock fallback."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size % _INDEX_DAY.itemsize:
        return None
    bars = np.fromfile(path, dtype=_INDEX_DAY)
    if not len(bars):
        return None
    dates = pd.to_datetime(bars['date'].astype(str), format='%Y%m%d', errors='coerce')
    frame = pd.DataFrame({'open': bars['open'].astype(float) / 100,
                          'close': bars['close'].astype(float) / 100}, index=dates)
    return frame.loc[frame.index.notna() & (frame['open'] > 0) & (frame['close'] > 0)].sort_index().loc[
        lambda value: ~value.index.duplicated(keep='last')]

RECENT_DAYS = 20
REFERENCE_DAYS = 120
MIN_REFERENCE_DAYS = 60
MIN_MATCHES_PER_DAY = 5
MIN_PAIRED_DAYS = 10
VOLUME_TOLERANCE = 0.15


def measure_equal_volume_response(bars: pd.DataFrame, index_daily: pd.DataFrame | None,
                                  *, as_of_date: str | None = None) -> dict:
    """Compare each of the latest 20 traded bars with *older* similar-volume days.

    Return percentages are QFQ stock intraday minus same-date SSE Composite intraday.
    Every reference observation predates the full recent block, not merely its day.
    """
    if as_of_date is not None:
        bars = bars.loc[bars.index <= pd.Timestamp(as_of_date)]
    clean = clean_wyckoff_bars(bars)
    result = {"status": "unavailable", "as_of_date": str(clean.index[-1].date()) if len(clean) else None,
              "recent_days": RECENT_DAYS, "reference_days": REFERENCE_DAYS,
              "matched_volume_tolerance": VOLUME_TOLERANCE, "observed_days": min(len(clean), RECENT_DAYS),
              "paired_days": 0, "pair_count": 0, "median_excess_response_pct": None,
              "positive_pair_fraction": None, "daily_evidence": []}
    if len(clean) < MIN_REFERENCE_DAYS + RECENT_DAYS:
        result["reason"] = "insufficient_history"
        return result
    if index_daily is None or not {"open", "close"}.issubset(index_daily.columns):
        result["reason"] = "benchmark_unavailable"
        return result
    recent = clean.iloc[-RECENT_DAYS:]
    reference = clean.iloc[max(0, len(clean) - RECENT_DAYS - REFERENCE_DAYS):-RECENT_DAYS]
    result.update(reference_from_date=str(reference.index[0].date()),
                  reference_through_date=str(reference.index[-1].date()),
                  recent_from_date=str(recent.index[0].date()))
    required = reference.index.union(recent.index)
    if not required.isin(index_daily.index).all():
        result["reason"] = "benchmark_missing_sessions"
        return result
    benchmark = index_daily.loc[required, ["open", "close"]]
    if not (benchmark.notna().all().all() and (benchmark > 0).all().all()):
        result["reason"] = "benchmark_invalid_prices"
        return result
    stock_return = clean["close"] / clean["open"] - 1
    benchmark_return = benchmark["close"] / benchmark["open"] - 1
    response = stock_return.loc[required] - benchmark_return
    residuals = []
    for day, bar in recent.iterrows():
        matches = reference.loc[(reference["volume"] - bar["volume"]).abs() <= VOLUME_TOLERANCE * bar["volume"]]
        matched = len(matches) >= MIN_MATCHES_PER_DAY
        reference_median = float(median(response.loc[matches.index])) if matched else None
        residual = float(response.loc[day] - reference_median) if matched else None
        result["daily_evidence"].append({
            "date": str(day.date()), "volume": float(bar["volume"]),
            "stock_intraday_pct": float(stock_return.loc[day] * 100),
            "benchmark_intraday_pct": float(benchmark_return.loc[day] * 100),
            "reference_count": len(matches),
            "matched_reference_dates": [str(value.date()) for value in matches.index],
            "reference_excess_median_pct": reference_median * 100 if reference_median is not None else None,
            "excess_response_pct": residual * 100 if residual is not None else None,
        })
        if not matched:
            continue
        residuals.append(residual)
        result["pair_count"] += len(matches)
    result["paired_days"] = len(residuals)
    if len(residuals) < MIN_PAIRED_DAYS:
        result["reason"] = "insufficient_matched_volume_days"
        return result
    result.update(status="available", median_excess_response_pct=median(residuals) * 100,
                  positive_pair_fraction=sum(value > 0 for value in residuals) / len(residuals))
    return result
