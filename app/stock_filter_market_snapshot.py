"""Compact, per-symbol QFQ metrics used by the all-market stock filter."""
from __future__ import annotations

from typing import Any, Callable
import pandas as pd


def _num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def classify_timeframe_trend(closes: list[float]) -> str | None:
    values = [float(value) for value in closes if _num(value) is not None]
    if len(values) < 20:
        return None
    series = pd.Series(values, dtype=float)
    fast, middle, slow = (series.rolling(window).mean().iloc[-1] for window in (5, 10, 20))
    latest = values[-1]
    if latest > fast > middle > slow:
        return "strong_bullish"
    if latest > fast > middle:
        return "bullish"
    if latest < fast < middle:
        return "bearish"
    return "neutral"


def _trend_label(value: str | None) -> str | None:
    return {"strong_bullish": "强多头", "bullish": "多头", "recovering": "修复中", "neutral": "震荡", "bearish": "空头", "strong_bearish": "强空头"}.get(value or "")


def _daily_trend(closes: list[float]) -> str | None:
    """Match the technical-evaluation daily MA20/50/120/250 trend gate."""
    values = pd.Series([float(value) for value in closes if _num(value) is not None], dtype=float)
    if len(values) < 60:
        return None
    ma20, ma50 = values.rolling(20).mean(), values.rolling(50).mean()
    ma120 = values.rolling(120).mean() if len(values) >= 120 else None
    ma250 = values.rolling(250).mean() if len(values) >= 250 else None
    last20, last50, close = float(ma20.iloc[-1]), float(ma50.iloc[-1]), float(values.iloc[-1])
    slope20 = (last20 / float(ma20.iloc[-6]) - 1.0) if float(ma20.iloc[-6]) else 0.0
    slope50 = (last50 / float(ma50.iloc[-11]) - 1.0) if float(ma50.iloc[-11]) else 0.0
    last120 = float(ma120.iloc[-1]) if ma120 is not None else None
    last250 = float(ma250.iloc[-1]) if ma250 is not None else None
    if last250 is not None and last120 is not None and last20 > last50 > last120 > last250 and close > last20 and slope20 > 0 and slope50 > 0:
        return "strong_bullish"
    if last120 is not None and last20 > last50 > last120 and close > last20 and slope20 > 0:
        return "bullish"
    if last20 > last50 and close > last20:
        threshold = 0.01 if last20 < 5 else (0.005 if last20 <= 20 else 0.003)
        if slope20 >= threshold:
            return "recovering"
    if last250 is not None and last120 is not None and last20 < last50 < last120 < last250 and close < last20 and slope20 < 0:
        return "strong_bearish"
    if last120 is not None and last20 < last50 < last120 and close < last50:
        return "bearish"
    return "neutral"


def _short_trend(closes: list[float]) -> str | None:
    """Match the technical-evaluation short MA10/20/30/60 trend gate."""
    values = pd.Series([float(value) for value in closes if _num(value) is not None], dtype=float)
    if len(values) < 30:
        return None
    ma10, ma20, ma30 = values.rolling(10).mean(), values.rolling(20).mean(), values.rolling(30).mean()
    ma60 = values.rolling(60).mean() if len(values) >= 60 else None
    last10, last20, last30, close = float(ma10.iloc[-1]), float(ma20.iloc[-1]), float(ma30.iloc[-1]), float(values.iloc[-1])
    slope10 = (last10 / float(ma10.iloc[-4]) - 1.0) if float(ma10.iloc[-4]) else 0.0
    slope20 = (last20 / float(ma20.iloc[-6]) - 1.0) if float(ma20.iloc[-6]) else 0.0
    last60 = float(ma60.iloc[-1]) if ma60 is not None else None
    if last60 is not None and last10 > last20 > last30 > last60 and close > last10 and slope10 > 0 and slope20 > 0:
        return "strong_bullish"
    if last10 > last20 > last30 and close > last10 and slope10 > 0:
        return "bullish"
    if last10 > last20 and close > last10:
        threshold = 0.01 if last10 < 5 else (0.005 if last10 <= 20 else 0.003)
        if slope10 >= threshold:
            return "recovering"
    if last60 is not None and last10 < last20 < last30 < last60 and close < last10 and slope10 < 0:
        return "strong_bearish"
    if last10 < last20 < last30 and close < last20:
        return "bearish"
    return "neutral"


def _blowup_break_metrics(group: pd.DataFrame) -> dict[str, Any]:
    """Compute the historical ``爆量突破`` volume/price legs from QFQ OHLCV.

    V1 is the latest bar. VA is V6--V10 average volume; every V1--V5
    bar must exceed 3x VA when bullish and 2x VA otherwise. Trend legs are
    deliberately evaluated by the filter from the technical-evaluation data.
    """
    bars = group[["open", "close", "volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(bars) < 11:
        return {"blowup_break_volume_price_ok": False, "blowup_break_va": None,
                "blowup_break_vol_ratios": [], "blowup_break_return_5d": None}
    opens = bars["open"].tolist()
    closes = bars["close"].tolist()
    volumes = bars["volume"].tolist()
    va = sum(volumes[-10:-5]) / 5.0
    ret_5d = (closes[-1] / closes[-6] - 1.0) * 100.0 if closes[-6] else None
    ratios = [round(float(volumes[idx] / va), 2) for idx in range(len(volumes) - 1, len(volumes) - 6, -1)] if va > 0 else []
    volume_ok = va > 0 and all(
        volumes[idx] > va * (3.0 if closes[idx] > opens[idx] else 2.0)
        for idx in range(len(volumes) - 5, len(volumes))
    )
    return {
        "blowup_break_volume_price_ok": bool(volume_ok and ret_5d is not None and 5.0 < ret_5d < 20.0),
        "blowup_break_va": round(float(va), 4) if va > 0 else None,
        "blowup_break_vol_ratios": ratios,
        "blowup_break_return_5d": round(float(ret_5d), 4) if ret_5d is not None else None,
    }


def build_market_metrics(frame: pd.DataFrame, *, on_progress: Callable[[int, int], Any] | None = None) -> dict[str, Any]:
    """Convert QFQ daily bars to a small current-per-symbol snapshot."""
    required = {"date", "market", "symbol", "open", "close", "volume", "free_float_shares"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows = frame.copy()
    rows["date"] = pd.to_datetime(rows["date"])
    rows["market"] = rows["market"].astype(str).str.lower()
    rows["symbol"] = rows["symbol"].astype(str).str.zfill(6)
    rows = rows.sort_values(["market", "symbol", "date"], kind="stable")
    labels = {"strong_bullish": "强多头", "bullish": "多头", "bearish": "空头", "neutral": "震荡"}
    metrics: dict[str, dict[str, Any]] = {}
    grouped = rows.groupby(["market", "symbol"], sort=False)
    total_groups = int(rows[["market", "symbol"]].drop_duplicates().shape[0])
    for completed, ((market, symbol), group) in enumerate(grouped, 1):
        group = group.set_index("date")
        closes = pd.to_numeric(group["close"], errors="coerce").dropna()
        close = closes.tolist()
        daily_trend, short_trend = _daily_trend(close), _short_trend(close)
        item: dict[str, Any] = {"qfq_as_of": str(closes.index[-1].date()) if len(closes) else None,
                                "trend_daily": daily_trend, "trend_daily_label": _trend_label(daily_trend),
                                "short_trend": short_trend, "short_trend_label": _trend_label(short_trend)}
        item.update(_blowup_break_metrics(group))
        for days in (1, 5, 20):
            item[f"return_{days}d"] = round((close[-1] / close[-1-days] - 1) * 100, 4) if len(close) > days and close[-1-days] else None
        shares = _num(group["free_float_shares"].iloc[-1]) if len(group) else None
        volumes = pd.to_numeric(group["volume"], errors="coerce")
        if shares and shares > 0 and len(volumes) >= 5 and volumes.tail(5).notna().all():
            total = float(volumes.tail(5).sum()) / shares * 100
            item["turnover_5_sum"] = round(total, 4)
            item["turnover_5_avg"] = round(total / 5, 4)
        else:
            item["turnover_5_sum"] = item["turnover_5_avg"] = None
        for name, rule in (("weekly", "W-FRI"), ("monthly", "ME")):
            sampled = closes.resample(rule).last().dropna().tolist()
            trend = classify_timeframe_trend(sampled)
            item[f"trend_{name}"] = trend
            item[f"trend_{name}_label"] = labels.get(trend or "")
        metrics[f"{market}:{symbol}"] = item
        if on_progress is not None and (completed == total_groups or completed % 50 == 0):
            on_progress(completed, total_groups)
    return {"schema_version": "stock-filter-market-metrics-v1", "stocks": len(metrics), "metrics": metrics}
