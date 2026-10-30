"""Lifecycle stage classification for a single stock from QFQ daily bars.

Classifies the *current* stage of a stock into 11 mutually-exclusive lifecycle
states organised under 4 regions.  Signals are computed from front-adjusted
daily OHLCV only; no cross-sectional data is required, so the function is a
pure, testable transform of one instrument's bars.

Regions and stages
------------------
down (下跌区)
    D1 破位下跌  — MA20 just turned down (breakdown)
    D2 主跌      — accelerated downtrend, bearish alignment
    D3 下跌中继  — weak (low-volume) rebound inside a downtrend
base (底部区)
    B1 底部盘整  — basing sideways at lows
    B2 探底回升  — first volume breakout above MA20 (global-priority signal)
    B3 回踩确认  — pullback after a bounce that holds above the prior low
up (上升区)
    U1 上升初期  — just reclaims MA60
    U2 主升      — bullish alignment, steady new highs
    U3 上升中继  — short-term pullback inside an uptrend
    U4 加速赶顶  — excessive extension above MA20 (climax)
top (顶部区)
    T1 高位震荡  — distribution sideways at highs

The classifier is a *snapshot* read of the current state, not a forecast.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# --- tunable thresholds (empirical defaults; calibrate against distribution) ---
FLAT_SLOPE = 0.005        # |slope| below this is treated as "flat"
BIAS_CLIMAX = 0.18        # close vs MA20 extension that flags U4 climax
VOL_BREAKOUT = 1.5        # volume / 5-day-average volume for a breakout day
MIN_DAYS = 60             # minimum bars required to classify

# --- region position gates -------------------------------------------------
# "base" and "top" used to be decided only by MA60 slope + which side of MA60
# the close sits on, so a stock 20% below its 60-day high could still be called
# 底部盘整, and one 13% below the high 高位震荡.  These gates make each region
# earn its name using where price actually sits inside the 60-bar range.
BASE_MAX_RANGE_POS = 0.50      # base only accepts the lower half of the 60d range
TOP_MAX_DIST_FROM_HIGH = 0.10  # top only accepts within 10% of the 60d high

_REGION_LABELS = {"down": "下跌区", "base": "底部区", "up": "上升区", "top": "顶部区"}
_STAGE_LABELS = {
    "D1": "破位下跌", "D2": "主跌", "D3": "下跌中继",
    "B1": "底部盘整", "B2": "探底回升", "B3": "回踩确认",
    "U1": "上升初期", "U2": "主升", "U3": "上升中继", "U4": "加速赶顶",
    "T1": "高位震荡",
    "R1": "上升回撤", "R2": "下跌反弹",
}
# 事件型阶段：描述的是「当天发生的动作」，不是可以停留的状态。
# 全市场历史实测：B2 平均持续 1.51 个交易日（中位 1 天），D1 平均 2.79 天；
# 而真正的阶段（D2 6.09、B3 5.54、B1 4.89）都在 4 天以上。调用方据此决定
# 是否把它们当作可持仓状态，例如筛选/回测应把它们当触发信号而非持仓依据。
EVENT_STAGES = frozenset({"B2", "D1"})


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if b is None or b == 0:
        return default
    return a / b


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    """Trailing mean aligned to `values`; None while insufficient data."""
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out.append(running / window)
        else:
            out.append(None)
    return out


def _slope(ma_arr: list[float | None], ago: int) -> float | None:
    """Percent change of the MA between `ago` bars back and now."""
    now = ma_arr[-1]
    then = ma_arr[-1 - ago] if len(ma_arr) > ago else None
    if now is None or then is None or then == 0:
        return None
    return (now - then) / then


def prepare_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows that cannot be used as technical bars.

    Tongdaxin's front-adjusted export writes suspended sessions as a 0.00 price
    row.  Keeping those rows corrupts MA20/MA60, the 60-bar high/low range and
    the volume ratio, which fabricates stages (A-share names can carry hundreds
    of such rows).  Both the scalar and the series path call this, so they stay
    consistent with each other and with the price series a human sees.

    Technical indicators compare a bar with the previous *traded* bar, so
    dropping the placeholder is the correct treatment — not forward-filling.
    """
    if df.empty:
        return df
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"bars are missing columns: {', '.join(missing)}")
    prices = df[["high", "low", "close"]].astype(float)
    usable = np.isfinite(prices).all(axis=1) & (prices["close"] > 0) & (prices["high"] > 0) & (prices["low"] > 0)
    return df.loc[usable]


def classify_stage(df: pd.DataFrame) -> dict[str, Any]:
    """Classify the current lifecycle stage of a stock.

    `df` must be a DataFrame indexed by date (ascending) with at least the
    columns ``open``, ``high``, ``low``, ``close``, ``volume`` (amount optional).
    Suspended placeholder rows (0.00 prices) are dropped first.

    Returns a dict with keys: ``status``, ``region``, ``region_label``,
    ``stage``, ``stage_label``, ``detail``, ``evidence``.
    """
    df = prepare_bars(df)
    closes = [float(x) for x in df["close"].tolist()]
    highs = [float(x) for x in df["high"].tolist()]
    lows = [float(x) for x in df["low"].tolist()]
    volumes = [float(x) for x in df["volume"].tolist()]

    if len(closes) < MIN_DAYS:
        return {
            "status": "insufficient_data",
            "region": None, "region_label": None,
            "stage": None, "stage_label": None,
            "detail": f"交易日不足{MIN_DAYS}日",
            "evidence": {"bars": len(closes)},
        }

    close = closes[-1]
    ma5_arr = _rolling_mean(closes, 5)
    ma10_arr = _rolling_mean(closes, 10)
    ma20_arr = _rolling_mean(closes, 20)
    ma60_arr = _rolling_mean(closes, 60)

    ma5 = float(ma5_arr[-1] or 0.0)
    ma10 = float(ma10_arr[-1] or 0.0)
    ma20 = float(ma20_arr[-1] or 0.0)
    ma60 = float(ma60_arr[-1] or 0.0)

    slope20 = _slope(ma20_arr, 5) or 0.0
    slope60 = _slope(ma60_arr, 10) or 0.0
    # slope20 as of 5 bars ago (to detect "just turned down/up")
    slope20_prev = _slope(ma20_arr[:-5], 5) if len(ma20_arr) > 10 else 0.0
    if slope20_prev is None:
        slope20_prev = 0.0

    high_60 = max(highs[-60:])
    low_60 = min(lows[-60:])
    mid_60 = (high_60 + low_60) / 2
    pos_high = _safe_div(close - high_60, high_60)
    pos_low = _safe_div(close - low_60, low_60)
    bias20 = _safe_div(close - ma20, ma20)
    range_span = high_60 - low_60
    range_pos = _safe_div(close - low_60, range_span, 0.5) if range_span > 0 else 0.5

    prior5 = volumes[-6:-1] if len(volumes) >= 6 else volumes[:-1]
    avg5 = sum(prior5) / len(prior5) if prior5 else 1.0
    vol_ratio = _safe_div(volumes[-1], avg5, 1.0)

    is_60d_high = close >= high_60 * 0.999
    is_60d_low = lows[-1] <= low_60 * 1.001
    high_20 = max(highs[-20:])
    low_20 = min(lows[-20:])
    is_20d_high = close >= high_20 * 0.999

    evidence = {
        "ma5": round(ma5, 3), "ma10": round(ma10, 3),
        "ma20": round(ma20, 3), "ma60": round(ma60, 3),
        "slope20": round(slope20, 5), "slope60": round(slope60, 5),
        "bias20": round(bias20, 4),
        "pos_high_60": round(pos_high, 4), "pos_low_60": round(pos_low, 4),
        "range_pos_60": round(range_pos, 4),
        "vol_ratio": round(vol_ratio, 3),
        "is_60d_high": bool(is_60d_high),
        "is_20d_high": bool(is_20d_high),
        "high_20": round(high_20, 3), "low_20": round(low_20, 3),
    }

    def _result(region: str, stage: str, detail: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "region": region,
            "region_label": _REGION_LABELS[region],
            "stage": stage,
            "stage_label": _STAGE_LABELS[stage],
            "is_event": stage in EVENT_STAGES,
            "detail": detail,
            "evidence": evidence,
        }

    # ---- region ----
    if slope60 > FLAT_SLOPE:
        if close > ma60:
            region = "up"
        elif range_pos > BASE_MAX_RANGE_POS:
            # MA60 still rising and price fell below it, yet sits in the upper half
            # of the 60-bar range: an uptrend pullback, not a bottom
            region = "up"
        else:
            region = "base"
    elif slope60 < -FLAT_SLOPE:
        if close < ma60:
            region = "down"
        elif pos_high < -TOP_MAX_DIST_FROM_HIGH:
            # MA60 rolling over and price still above it, but already >10% off the
            # 60-day high: a decline in progress, not high-level churn
            region = "down"
        else:
            region = "top"
    else:
        if slope20 > FLAT_SLOPE and close > ma60:
            region = "up"
        elif slope20 < -FLAT_SLOPE and close < ma60:
            region = "down"
        else:
            region = "base" if close < mid_60 else "top"

    ma_layout = ""
    if ma5 > ma10 > ma20 > ma60:
        ma_layout = "多头排列"
    elif ma5 < ma10 < ma20 < ma60:
        ma_layout = "空头排列"
    else:
        ma_layout = "纠缠"

    # ---- stage ----
    # B2/B3 are *events that happen inside a trend region*.  They label the bar
    # but never rewrite the region: a volume breakout at range_pos 95% is not a
    # bottom, and a "pullback holding the prior low" during a falling MA60 is
    # not a bottom confirmation either.
    breakout_position_ok = range_pos <= BASE_MAX_RANGE_POS or pos_high <= -TOP_MAX_DIST_FROM_HIGH
    if (region in ("base", "down") and breakout_position_ok
            and close > ma20 and vol_ratio >= VOL_BREAKOUT and slope20 > 0):
        return _result(region, "B2",
                       f"探底回升：放量(量比{vol_ratio:.2f})突破MA20({ma20:.2f})")

    if (region in ("base", "down")
            and low_20 > low_60 and high_20 > ma20 and close < ma20
            and slope60 >= -FLAT_SLOPE and range_pos <= BASE_MAX_RANGE_POS):
        return _result(region, "B3",
                       f"回踩确认：近20日高点{high_20:.2f}回踩至{close:.2f}，未破前低{low_20:.2f}")

    if region == "down":
        if ma5 > ma10:
            return _result("down", "D3",
                           f"下跌中继：中期空头，短期反弹(MA5>MA10)，收盘{close:.2f}，量比{vol_ratio:.2f}")
        if slope20 < 0 and slope20_prev >= 0:
            return _result("down", "D1",
                           f"破位下跌：MA20刚拐头向下，收盘{close:.2f}")
        return _result("down", "D2",
                       f"主跌：{ma_layout}，收盘{close:.2f}，60日新低={'是' if is_60d_low else '否'}")

    if region == "base":
        # MA60 still rising means the mid-term trend is intact and this is a deep
        # pullback, not a bottom: label it 上升回撤 instead of 底部盘整.
        if slope60 > FLAT_SLOPE:
            return _result("base", "R1",
                           f"上升回撤：MA60仍上行({slope60 * 100:+.2f}%)，收盘{close:.2f}跌破MA60({ma60:.2f})"
                           f"，区间位置{range_pos * 100:.0f}%")
        return _result("base", "B1",
                       f"底部盘整：{ma_layout}，收盘{close:.2f}，量比{vol_ratio:.2f}")

    if region == "up":
        if bias20 >= BIAS_CLIMAX:
            return _result("up", "U4",
                           f"加速赶顶：乖离率{bias20*100:.1f}%超{BIAS_CLIMAX*100:.0f}%")
        if ma5 < ma10:
            return _result("up", "U3",
                           f"上升中继：中期多头，短期回踩(MA5<MA10)，收盘{close:.2f}")
        prev_close = closes[-11] if len(closes) > 11 else closes[-1]
        prev_ma60 = ma60_arr[-11] if len(ma60_arr) > 11 else ma60
        if slope20 > 0 and prev_ma60 is not None and prev_close <= prev_ma60:
            return _result("up", "U1",
                           f"上升初期：收盘{close:.2f}刚站上MA60({ma60:.2f})")
        if close <= ma20:
            # 主升要求站上 MA20；跌破 MA20 的短期回踩仍属上升中继
            return _result("up", "U3",
                           f"上升中继：中期多头，收盘{close:.2f}低于MA20({ma20:.2f})，短期回踩")
        return _result("up", "U2",
                       f"主升：{ma_layout}，收盘{close:.2f}，量比{vol_ratio:.2f}")

    # region == "top"
    # MA60 falling under a price that is still near the high is a rally inside a
    # downtrend (下跌反弹), not high-level churn.
    if slope60 < -FLAT_SLOPE:
        return _result("top", "R2",
                       f"下跌反弹：MA60仍下行({slope60 * 100:+.2f}%)，收盘{close:.2f}"
                       f"距60日高点{pos_high * 100:+.1f}%")
    return _result("top", "T1",
                   f"高位震荡：{ma_layout}，收盘{close:.2f}，量比{vol_ratio:.2f}")


def classify_stage_from_code(code: str, export_dir=None) -> dict[str, Any]:
    """Convenience wrapper loading QFQ daily bars for `code` then classifying."""
    from app.tdx.qfq_kline import load_tdx_qfq_daily
    df = load_tdx_qfq_daily(code, export_dir) if export_dir else load_tdx_qfq_daily(code)
    return classify_stage(df)
