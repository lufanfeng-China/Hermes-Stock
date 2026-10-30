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

import pandas as pd

# --- tunable thresholds (empirical defaults; calibrate against distribution) ---
FLAT_SLOPE = 0.005        # |slope| below this is treated as "flat"
BIAS_CLIMAX = 0.18        # close vs MA20 extension that flags U4 climax
VOL_BREAKOUT = 1.5        # volume / 5-day-average volume for a breakout day
MIN_DAYS = 60             # minimum bars required to classify

_REGION_LABELS = {"down": "下跌区", "base": "底部区", "up": "上升区", "top": "顶部区"}
_STAGE_LABELS = {
    "D1": "破位下跌", "D2": "主跌", "D3": "下跌中继",
    "B1": "底部盘整", "B2": "探底回升", "B3": "回踩确认",
    "U1": "上升初期", "U2": "主升", "U3": "上升中继", "U4": "加速赶顶",
    "T1": "高位震荡",
}


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


def classify_stage(df: pd.DataFrame) -> dict[str, Any]:
    """Classify the current lifecycle stage of a stock.

    `df` must be a DataFrame indexed by date (ascending) with at least the
    columns ``open``, ``high``, ``low``, ``close``, ``volume`` (amount optional).

    Returns a dict with keys: ``status``, ``region``, ``region_label``,
    ``stage``, ``stage_label``, ``detail``, ``evidence``.
    """
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
            "detail": detail,
            "evidence": evidence,
        }

    # ---- region ----
    if slope60 > FLAT_SLOPE:
        region = "up" if close > ma60 else "base"
    elif slope60 < -FLAT_SLOPE:
        region = "down" if close < ma60 else "top"
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
    # B2 探底回升: volume breakout above MA20 (a reversal signal that can fire
    # while still in the down region).  Forces region to base.
    if close > ma20 and vol_ratio >= VOL_BREAKOUT and slope20 > 0:
        return _result("base", "B2",
                       f"探底回升：放量(量比{vol_ratio:.2f})突破MA20({ma20:.2f})")

    # B3 回踩确认: pullback holding above the prior low after a bounce; only
    # when mid-term has not turned up (otherwise it is an U3 uptrend pullback).
    if low_20 > low_60 and high_20 > ma20 and close < ma20 and slope60 <= FLAT_SLOPE:
        return _result("base", "B3",
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
        return _result("up", "U2",
                       f"主升：{ma_layout}，收盘{close:.2f}，量比{vol_ratio:.2f}")

    # region == "top"
    return _result("top", "T1",
                   f"高位震荡：{ma_layout}，收盘{close:.2f}，量比{vol_ratio:.2f}")


def classify_stage_from_code(code: str, export_dir=None) -> dict[str, Any]:
    """Convenience wrapper loading QFQ daily bars for `code` then classifying."""
    from app.tdx.qfq_kline import load_tdx_qfq_daily
    df = load_tdx_qfq_daily(code, export_dir) if export_dir else load_tdx_qfq_daily(code)
    return classify_stage(df)
