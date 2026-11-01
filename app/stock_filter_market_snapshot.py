"""Compact, per-symbol QFQ metrics used by the all-market stock filter."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


# 趋势模版（Trend Template）口径。第 8 条「相对强度评级 ≥70」本次不纳入。
TREND_TEMPLATE_MA_FAST = 50          # 50 日线
TREND_TEMPLATE_MA_MID = 150          # 150 日线
TREND_TEMPLATE_MA_SLOW = 200         # 200 日线
TREND_TEMPLATE_RISE_LOOKBACK = 20    # 「至少上升 1 个月」按 20 个交易日计
TREND_TEMPLATE_RANGE_BARS = 250      # 52 周按 250 个交易日计
TREND_TEMPLATE_MIN_BARS = 250        # 同时需要 MA200 与 52 周区间
TREND_TEMPLATE_OFF_LOW_PCT = 30.0    # 比 52 周低点高至少 30%
TREND_TEMPLATE_NEAR_HIGH_PCT = 25.0  # 距 52 周高点 25% 以内


TREND_TEMPLATE_FIELDS = (
    "trend_template_ok",
    "trend_template_status",
    "trend_template_bars",
    "trend_template_price_basis",
    "trend_template_ma50",
    "trend_template_ma150",
    "trend_template_ma200",
    "trend_template_ma200_20d_ago",
    "trend_template_high_52w",
    "trend_template_low_52w",
    "trend_template_off_low_pct",
    "trend_template_from_high_pct",
    "trend_template_legs",
)


def _trend_template_metrics(group: pd.DataFrame) -> dict[str, Any]:
    """Trend Template 的 7 条腿（不含第 8 条相对强度）。

    本地筛选库里只有收盘价，没有最高/最低价，因此「52 周高低点」按收盘价的
    最高/最低计，与用最高/最低价的严格口径可能有细微差异。
    """
    closes = pd.to_numeric(group["close"], errors="coerce").dropna().tolist()
    bars = len(closes)
    base = {
        "trend_template_ok": False,
        "trend_template_status": "insufficient_history" if bars < TREND_TEMPLATE_MIN_BARS else "evaluated",
        "trend_template_bars": bars,
        "trend_template_price_basis": "close_only",
        "trend_template_ma50": None,
        "trend_template_ma150": None,
        "trend_template_ma200": None,
        "trend_template_ma200_20d_ago": None,
        "trend_template_high_52w": None,
        "trend_template_low_52w": None,
        "trend_template_off_low_pct": None,
        "trend_template_from_high_pct": None,
        "trend_template_legs": {},
    }
    if bars < TREND_TEMPLATE_MIN_BARS:
        return base

    close = closes[-1]
    ma_fast = sum(closes[-TREND_TEMPLATE_MA_FAST:]) / TREND_TEMPLATE_MA_FAST
    ma_mid = sum(closes[-TREND_TEMPLATE_MA_MID:]) / TREND_TEMPLATE_MA_MID
    ma_slow = sum(closes[-TREND_TEMPLATE_MA_SLOW:]) / TREND_TEMPLATE_MA_SLOW
    slow_series = [sum(closes[index - TREND_TEMPLATE_MA_SLOW + 1:index + 1]) / TREND_TEMPLATE_MA_SLOW
                   for index in range(TREND_TEMPLATE_MA_SLOW - 1, bars)]
    slow_prev = slow_series[-1 - TREND_TEMPLATE_RISE_LOOKBACK] if len(slow_series) > TREND_TEMPLATE_RISE_LOOKBACK else None
    window = closes[-TREND_TEMPLATE_RANGE_BARS:]
    high_52w, low_52w = max(window), min(window)

    legs = {
        "above_ma150": close > ma_mid,                     # 1 股价在 150 日线之上
        "ma150_above_ma200": ma_mid > ma_slow,              # 2 150 日线在 200 日线之上
        "ma200_rising_1m": slow_prev is not None and ma_slow > slow_prev,  # 3 200 日线至少上升 1 个月
        "ma50_above_150_200": ma_fast > ma_mid and ma_fast > ma_slow,      # 4 50 日线在 150、200 日线之上
        "above_ma50": close > ma_fast,                     # 5 股价在 50 日线之上
        "off_52w_low_30pct": low_52w > 0 and (close / low_52w - 1) * 100 >= TREND_TEMPLATE_OFF_LOW_PCT,  # 6
        "within_25pct_of_52w_high": high_52w > 0 and (high_52w - close) / high_52w * 100 <= TREND_TEMPLATE_NEAR_HIGH_PCT,  # 7
    }
    base.update({
        "trend_template_ok": all(legs.values()),
        "trend_template_ma50": round(ma_fast, 4),
        "trend_template_ma150": round(ma_mid, 4),
        "trend_template_ma200": round(ma_slow, 4),
        "trend_template_ma200_20d_ago": round(slow_prev, 4) if slow_prev is not None else None,
        "trend_template_high_52w": round(high_52w, 4),
        "trend_template_low_52w": round(low_52w, 4),
        "trend_template_off_low_pct": round((close / low_52w - 1) * 100, 2) if low_52w > 0 else None,
        "trend_template_from_high_pct": round((close / high_52w - 1) * 100, 2) if high_52w > 0 else None,
        "trend_template_legs": legs,
    })
    return base


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


PRICE_PERCENTILE_FIELDS = (
    "price_percentile_5y", "price_basis", "price_percentile_5y_as_of",
    "price_percentile_5y_window_start", "price_percentile_5y_window_end",
    "price_percentile_5y_sample_count", "price_percentile_5y_first_valid_date",
)

# 股价收益比 = 最近 5 个完整年度「基本每股收益」加总 ÷ 当前股价（%）。
# 上市不足五年的公司按已有完整年度年化到五年口径，系数见 EPS_ANNUALISATION：
#   4 年 ×1.25、3 年 ×5/3、2 年 ×2.5、1 年 ×5
EPS_YEARS = ("2021A", "2022A", "2023A", "2024A", "2025A")
EPS_ANNUALISATION = {5: 1.0, 4: 1.25, 3: 5 / 3, 2: 2.5, 1: 5.0}
FINANCIAL_TS_DIR = PROJECT_ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
EPS_RATIO_FIELDS = ("eps_ratio_5y", "eps_ratio_5y_years", "eps_ratio_5y_factor",
                    "eps_ratio_5y_eps_sum", "eps_ratio_5y_price")


@lru_cache(maxsize=2)
def load_annual_eps(years: tuple[str, ...] = EPS_YEARS,
                    directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Sum basic EPS over the last five complete fiscal years, per symbol.

    Returns {symbol: {"sum": float, "years": int}}; symbols missing every year are
    omitted. Missing year files are skipped rather than failing the whole build.
    """
    base = Path(directory) if directory is not None else FINANCIAL_TS_DIR
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for year in years:
        path = base / f"{year}.parquet"
        if not path.is_file():
            continue
        frame = pd.read_parquet(path, columns=["基本每股收益"])
        series = pd.to_numeric(frame["基本每股收益"], errors="coerce").dropna()
        for code, value in series.items():
            key = str(code).zfill(6)
            totals[key] = totals.get(key, 0.0) + float(value)
            counts[key] = counts.get(key, 0) + 1
    return {code: {"sum": round(totals[code], 6), "years": counts[code]} for code in totals}


def _eps_ratio_fields(eps_info: dict[str, Any] | None, price: float | None) -> dict[str, Any]:
    """Annualise the EPS sum to five years and divide by the current price (in %)."""
    result = dict.fromkeys(EPS_RATIO_FIELDS)
    if not eps_info or price is None or price <= 0:
        return result
    years = int(eps_info.get("years") or 0)
    factor = EPS_ANNUALISATION.get(min(years, 5))
    if not factor:
        return result
    eps_sum = float(eps_info.get("sum") or 0.0)
    result.update({
        "eps_ratio_5y": round(eps_sum * factor / price * 100, 2),
        "eps_ratio_5y_years": years,
        "eps_ratio_5y_factor": round(factor, 4),
        "eps_ratio_5y_eps_sum": round(eps_sum, 4),
        "eps_ratio_5y_price": round(price, 2),
    })
    return result


def _price_percentile_5y(group: pd.DataFrame) -> dict[str, Any]:
    """Inclusive five-calendar-year empirical rank; never use raw-price fallback."""
    import numpy as np

    closes = pd.to_numeric(group["close"], errors="coerce")
    valid = closes[(closes > 0) & np.isfinite(closes) & closes.index.notna()]
    result = dict.fromkeys(PRICE_PERCENTILE_FIELDS)
    result.update(price_basis="tdx_export_qfq", price_percentile_5y_sample_count=0)
    if valid.empty:
        return result
    as_of = valid.index[-1]
    cutoff = as_of - pd.DateOffset(years=5)
    window = valid.loc[(valid.index >= cutoff) & (valid.index <= as_of)]
    result.update({
        "price_percentile_5y_as_of": str(as_of.date()),
        "price_percentile_5y_window_start": str(cutoff.date()),
        "price_percentile_5y_window_end": str(as_of.date()),
        "price_percentile_5y_first_valid_date": str(valid.index[0].date()),
        "price_percentile_5y_sample_count": len(window),
    })
    if valid.index[0] <= cutoff and len(window) >= 60:
        result["price_percentile_5y"] = round(float((window <= valid.iloc[-1]).sum()) / len(window) * 100, 1)
    return result


def build_market_metrics(frame: pd.DataFrame, *, on_progress: Callable[[int, int], Any] | None = None,
                         annual_eps: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Convert QFQ daily bars to a small current-per-symbol snapshot."""
    required = {"date", "market", "symbol", "open", "close", "volume", "free_float_shares"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    eps_map = annual_eps if annual_eps is not None else load_annual_eps()
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
        item.update(_trend_template_metrics(group))
        item.update(_price_percentile_5y(group))
        item.update(_eps_ratio_fields(eps_map.get(symbol), close[-1] if close else None))
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
    return {"schema_version": "stock-filter-market-metrics-v3", "stocks": len(metrics), "metrics": metrics}
