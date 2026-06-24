#!/usr/bin/env python3
"""Pre-compute 6-dimension technical evaluation for all A-share stocks.
Reads TDX daily data, computes trend/momentum/volume/position signals,
evaluates buy triggers with ATR stop-loss, outputs JSON.

Usage:
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/build_technical_eval.py
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/build_technical_eval.py --trading-day 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TDX_DIR = "/home/lufanfeng/tdx_data"
DATA_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
OUTPUT = DATA_DIR / "dataset_technical_eval.json"
RPS_PATH = DATA_DIR / "dataset_stock_rps_history.json"
PCT_PATH = DATA_DIR / "dataset_price_percentile_5y.json"

YEARS = 5
MIN_DAYS = 60              # minimum trading days
LOOKBACK = 260             # ~1 year for indicators
LONG_LOOKBACK = 1300       # ~5 years for MA250 + position

# ── helpers ──

def safe_div(a, b, default=0.0):
    if b is None or b == 0:
        return default
    return a / b

def rolling_mean(series, window):
    if len(series) < window:
        return [None] * len(series)
    return [None] * (window - 1) + list(pd.Series(series).rolling(window).mean().dropna())

def latest_non_null(series):
    for v in reversed(series):
        if v is not None:
            return v
    return None

# ── Market plate detection ──

def detect_market_plate(symbol, name=""):
    if "*ST" in name or "ST" in name:
        return "st"
    s = str(symbol)
    if s.startswith("688"):
        return "star"
    if s.startswith(("300", "301")):
        return "chinext"
    if s.startswith(("43", "83", "87", "88", "4", "8")) and len(s) == 6 and s[0] in "48":
        return "bj"
    return "main_board"

def get_limit_pct(plate):
    if plate == "st": return 0.05
    if plate in ("chinext", "star"): return 0.20
    if plate == "bj": return 0.30
    return 0.10

# ── Indicators ──

def compute_atr(highs, lows, closes, period=14):
    """ATR for the latest period bars."""
    if len(closes) < period + 1:
        return None, None, None
    tr = []
    for i in range(1, len(closes)):
        if any(v is None for v in (highs[i], lows[i], closes[i-1])):
            tr.append(None)
            continue
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i-1])
        l_pc = abs(lows[i] - closes[i-1])
        tr.append(max(h_l, h_pc, l_pc))
    valid = [v for v in tr[-period:] if v is not None]
    if len(valid) < 5:
        return None, None, None
    atr = sum(valid) / len(valid)
    latest_close = closes[-1]
    if latest_close and latest_close > 0:
        atr_pct = atr / latest_close
    else:
        atr_pct = None
    return atr, atr_pct, len(valid)

# ── Trend ──

def classify_trend(closes, available_days):
    """6-level trend classification."""
    if available_days < 60:
        return "insufficient_data", "数据不足", "交易日不足60日"

    ma20_arr = rolling_mean(closes, 20)
    ma50_arr = rolling_mean(closes, 50)
    ma120_arr = rolling_mean(closes, 120) if available_days >= 120 else None
    ma250_arr = rolling_mean(closes, 250) if available_days >= 250 else None

    ma20 = latest_non_null(ma20_arr)
    ma50 = latest_non_null(ma50_arr)
    ma120 = latest_non_null(ma120_arr) if ma120_arr else None
    ma250 = latest_non_null(ma250_arr) if ma250_arr else None

    if any(v is None for v in (ma20, ma50)):
        return ("insufficient_data" if available_days < 60 else "neutral",
                "数据不足" if available_days < 60 else "震荡", "MA计算数据不足")

    close = closes[-1]

    # Slopes
    ma20_5ago = ma20_arr[-6] if len(ma20_arr) >= 6 and ma20_arr[-6] is not None else ma20
    ma50_10ago = ma50_arr[-11] if len(ma50_arr) >= 11 and ma50_arr[-11] is not None else ma50
    ma20_slope = safe_div(ma20 - ma20_5ago, ma20_5ago) if ma20_5ago else 0
    ma50_slope = safe_div(ma50 - ma50_10ago, ma50_10ago) if ma50_10ago else 0
    ma120_slope = None
    if ma120_arr and len(ma120_arr) >= 21 and ma120_arr[-21] is not None and ma120:
        ma120_slope = safe_div(ma120 - ma120_arr[-21], ma120_arr[-21])

    # strong_bullish
    if (ma250 is not None and ma120 is not None and
        ma20 > ma50 > ma120 > ma250 and close > ma20 and
        ma20_slope > 0 and ma50_slope > 0):
        return "strong_bullish", "强多头", f"MA20({ma20:.1f})>MA50({ma50:.1f})>MA120({ma120:.1f})>MA250({ma250:.1f})"

    # bullish
    if ma120 is not None and ma20 > ma50 > ma120 and close > ma20 and ma20_slope > 0:
        return "bullish", "多头", f"MA20({ma20:.1f})>MA50({ma50:.1f})>MA120({ma120:.1f}), close>{ma20:.1f}"

    # recovering
    if ma20 > ma50 and close > ma20:
        slope_threshold = 0.01 if ma20 < 5 else (0.005 if ma20 <= 20 else 0.003)
        if ma20_slope >= slope_threshold:
            return "recovering", "修复中", f"MA20({ma20:.1f})>MA50({ma50:.1f}), close>{ma20:.1f}, MA20上行{ma20_slope*100:.1f}%"

    # strong_bearish
    if (ma250 is not None and ma120 is not None and
        ma20 < ma50 < ma120 < ma250 and close < ma20 and ma20_slope < 0):
        return "strong_bearish", "强空头", f"MA20<MA50<MA120<MA250, close<MA20"

    # bearish
    if ma120 is not None and ma20 < ma50 < ma120 and close < ma50:
        return "bearish", "空头", f"MA20<MA50<MA120, close<MA50"

    # neutral
    return "neutral", "震荡", f"均线缠绕无明确方向"


# ── Short-term Trend (MA10/20/30/60) ──

def classify_short_trend(closes, available_days):
    """6-level short-term trend using MA10/20/30/60 for faster signal."""
    if available_days < 30:
        return "insufficient_data", "数据不足", "交易日不足30日"

    ma10_arr = rolling_mean(closes, 10)
    ma20_arr = rolling_mean(closes, 20)
    ma30_arr = rolling_mean(closes, 30) if available_days >= 30 else None
    ma60_arr = rolling_mean(closes, 60) if available_days >= 60 else None

    ma10 = latest_non_null(ma10_arr)
    ma20 = latest_non_null(ma20_arr)
    ma30 = latest_non_null(ma30_arr) if ma30_arr else None
    ma60 = latest_non_null(ma60_arr) if ma60_arr else None

    if any(v is None for v in (ma10, ma20)):
        return ("insufficient_data" if available_days < 30 else "neutral",
                "数据不足" if available_days < 30 else "震荡", "MA计算数据不足")

    close = closes[-1]

    # Slopes
    ma10_3ago = ma10_arr[-4] if len(ma10_arr) >= 4 and ma10_arr[-4] is not None else ma10
    ma20_5ago = ma20_arr[-6] if len(ma20_arr) >= 6 and ma20_arr[-6] is not None else ma20
    ma10_slope = safe_div(ma10 - ma10_3ago, ma10_3ago) if ma10_3ago else 0
    ma20_slope = safe_div(ma20 - ma20_5ago, ma20_5ago) if ma20_5ago else 0
    ma30_slope = None
    if ma30_arr and len(ma30_arr) >= 11 and ma30_arr[-11] is not None and ma30:
        ma30_slope = safe_div(ma30 - ma30_arr[-11], ma30_arr[-11])

    # strong_bullish
    if (ma60 is not None and ma30 is not None and
        ma10 > ma20 > ma30 > ma60 and close > ma10 and
        ma10_slope > 0 and ma20_slope > 0):
        return "strong_bullish", "强多头", f"MA10({ma10:.1f})>MA20({ma20:.1f})>MA30({ma30:.1f})>MA60({ma60:.1f})"

    # bullish
    if ma30 is not None and ma10 > ma20 > ma30 and close > ma10 and ma10_slope > 0:
        return "bullish", "多头", f"MA10({ma10:.1f})>MA20({ma20:.1f})>MA30({ma30:.1f}), close>{ma10:.1f}"

    # recovering
    if ma10 > ma20 and close > ma10:
        slope_threshold = 0.01 if ma10 < 5 else (0.005 if ma10 <= 20 else 0.003)
        if ma10_slope >= slope_threshold:
            return "recovering", "修复中", f"MA10({ma10:.1f})>MA20({ma20:.1f}), close>{ma10:.1f}, MA10上行{ma10_slope*100:.1f}%"

    # strong_bearish
    if (ma60 is not None and ma30 is not None and
        ma10 < ma20 < ma30 < ma60 and close < ma10 and ma10_slope < 0):
        return "strong_bearish", "强空头", f"MA10<MA20<MA30<MA60, close<MA10"

    # bearish
    if ma30 is not None and ma10 < ma20 < ma30 and close < ma20:
        return "bearish", "空头", f"MA10<MA20<MA30, close<MA20"

    # neutral
    return "neutral", "震荡", f"均线缠绕无明确方向"


# ── Momentum ──

def classify_momentum(rps20, rps50, rps120):
    """6-level momentum from RPS data."""
    r20 = rps20 if rps20 is not None else 50
    r50 = rps50 if rps50 is not None else 50
    r120 = rps120 if rps120 is not None else 50

    if r20 >= 90 and r50 >= 85 and r120 >= 80:
        return "super_strong", "极强", f"RPS20={r20} RPS50={r50} RPS120={r120}"
    if r50 >= 70 and r120 >= 70:
        return "strong", "强势", f"RPS50={r50} RPS120={r120}"
    if r20 >= 80 and r50 >= 70 and 40 <= r120 < 70:
        return "startup", "启动", f"RPS20={r20} RPS50={r50} RPS120={r120}(抬升中)"
    if r20 >= 80 and r50 >= 70 and r120 < 40:
        return "early_startup", "早期启动", f"RPS20={r20} RPS50={r50} RPS120={r120}(基础弱)"
    if r120 < 30 and r50 < 50:
        return "weak", "弱势", f"RPS120={r120} RPS50={r50}"
    return "neutral", "中性", f"RPS120={r120}"

# ── Volume signal ──

def classify_volume(volumes, closes, open_prices, highs, lows):
    """Volume-price evaluation with candle pattern."""
    if len(volumes) < 21 or len(closes) < 6:
        return "normal", "正常", "数据不足"

    today_vol = volumes[-1]
    avg_vol_20 = sum(v for v in volumes[-21:-1] if v is not None) / max(1, len([v for v in volumes[-21:-1] if v is not None]))
    vol_ratio = safe_div(today_vol, avg_vol_20, 1.0)

    close_5ago = closes[-6] if len(closes) >= 6 else closes[-1]
    ret_5d = safe_div(closes[-1] - close_5ago, close_5ago)
    is_up = ret_5d > 0

    # Candle pattern
    if highs[-1] and lows[-1] and highs[-1] != lows[-1]:
        close_pos = (closes[-1] - lows[-1]) / (highs[-1] - lows[-1])
        open_p = open_prices[-1] if open_prices[-1] else closes[-1]
        upper_shadow = (highs[-1] - max(open_p, closes[-1])) / (highs[-1] - lows[-1])
    else:
        close_pos, upper_shadow = 0.5, 0.0

    if vol_ratio > 1.2 and is_up and close_pos > 0.5:
        label = "放量配合"
        signal = "bullish"
    elif vol_ratio < 0.6:
        label = "缩量"
        signal = "low_volume"
    elif (vol_ratio > 1.2 and not is_up) or (vol_ratio < 0.4 and ret_5d > 0.03):
        label = "量价背离"
        signal = "divergence"
    else:
        label = "正常"
        signal = "normal"

    detail = f"量比{vol_ratio:.2f} close_pos={close_pos:.2f}"
    return signal, label, detail, vol_ratio, close_pos, upper_shadow

# ── Position ──

def classify_position(price_pct_data, closes, available_days):
    """Position in historical range."""
    if price_pct_data:
        pct = price_pct_data.get("price_percentile_5y")
        if pct is not None:
            if pct > 90:
                # Check overheat: 20-day return > 30%
                if len(closes) >= 21:
                    ret20 = safe_div(closes[-1] - closes[-21], closes[-21])
                    if ret20 > 0.30:
                        return "overheated", "过热", f"5年分位{pct:.0f}% + 20日涨{ret20*100:.0f}%"
                return "high", "高位", f"5年分位{pct:.0f}%"
            elif pct > 75:
                return "high", "高位", f"5年分位{pct:.0f}%"
            elif pct > 25:
                return "mid", "中位", f"5年分位{pct:.0f}%"
            else:
                return "low", "低位", f"5年分位{pct:.0f}%"

    # Fallback: distance from 250-day high
    if len(closes) < 250:
        if available_days < 250:
            return "new_stock", "新股", f"上市不足250日"
    max250 = max(closes[-250:])
    dist = safe_div(closes[-1] - max250, max250)
    if dist < -0.30: return "low", "低位", f"距250日高点{dist*100:.0f}%"
    if dist > -0.10: return "high", "高位", f"距250日高点{dist*100:.0f}%"
    return "mid", "中位", f"距250日高点{dist*100:.0f}%"

# ── Golden Cross (均线上穿) ──

def detect_golden_crosses(closes, available):
    """Detect if any fast MA crossed above slow MA today.
    
    Returns (comma_separated_crosses, label, detail).
    """
    pairs = [
        ("5/10", 5, 10),
        ("10/20", 10, 20),
        ("5/20", 5, 20),
        ("20/60", 20, 60),
        ("5/60", 5, 60),
    ]
    crosses = []
    cross_labels = []
    cross_details = []

    if available < 61:
        return "", "", ""

    for code, fast_n, slow_n in pairs:
        if available < slow_n + 1:
            continue
        today_fast = sum(closes[-fast_n:]) / fast_n
        today_slow = sum(closes[-slow_n:]) / slow_n
        yesterday_fast = sum(closes[-fast_n-1:-1]) / fast_n
        yesterday_slow = sum(closes[-slow_n-1:-1]) / slow_n
        if today_fast > today_slow and yesterday_fast <= yesterday_slow:
            crosses.append(code)
            cross_labels.append(f"MA{fast_n}上穿MA{slow_n}")
            cross_details.append(
                f"MA{fast_n}({today_fast:.2f})>MA{slow_n}({today_slow:.2f})"
            )

    if not crosses:
        return "", "", ""
    return ",".join(crosses), ",".join(cross_labels), "; ".join(cross_details)


# ── MACD Golden Cross ──

def detect_macd_cross(closes, available):
    """Detect MACD(12,26,9) golden cross.
    
    Returns (signal, label, detail).
    signal: "zero_below" / "zero_above" / ""
    """
    if available < 35:
        return "", "", ""

    def ema(series, period):
        alpha = 2.0 / (period + 1)
        result = [series[0]]
        for i in range(1, len(series)):
            result.append(alpha * series[i] + (1 - alpha) * result[-1])
        return result

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = ema(dif, 9)

    if len(dif) < 2 or len(dea) < 2:
        return "", "", ""

    today_dif = dif[-1]
    today_dea = dea[-1]
    yesterday_dif = dif[-2]
    yesterday_dea = dea[-2]

    if not (today_dif > today_dea and yesterday_dif <= yesterday_dea):
        return "", "", ""

    macd_bar = 2.0 * (today_dif - today_dea)

    if today_dif < 0 and today_dea < 0:
        return "zero_below", "零轴下金叉", f"DIF({today_dif:.3f})<0, DEA({today_dea:.3f})<0"
    else:
        return "zero_above", "零轴上金叉", f"DIF({today_dif:.3f})>0, DEA({today_dea:.3f})>0"

# ── Buy triggers ──

def evaluate_buy_triggers(trend, trend_label, momentum, momentum_label,
                          closes, volumes, highs, lows, opens,
                          ma20_arr, atr_val, atr_pct, atr_bars,
                          vol_ratio, close_pos, upper_shadow,
                          market_plate, recently_limit_down=False,
                          one_word_limit_up=False, one_word_limit_down=False):
    """Evaluate all 4 buy trigger signals."""
    triggers = []
    limit_pct = get_limit_pct(market_plate)

    if len(closes) < 21:
        return triggers

    today_close = closes[-1]
    today_vol = volumes[-1]
    today_high = highs[-1]
    today_low = lows[-1]
    today_open = opens[-1] if opens[-1] else today_close
    ma20 = latest_non_null(ma20_arr)
    prev_ma20 = ma20_arr[-2] if len(ma20_arr) >= 2 else ma20

    # Daily return
    if len(closes) >= 2 and closes[-2] and closes[-2] > 0:
        daily_ret = (today_close - closes[-2]) / closes[-2]
    else:
        daily_ret = 0

    # --- Signal A: 放量突破 ---
    prev_10_high_close = max(closes[-11:-1]) if len(closes) >= 11 else max(closes[:-1])
    prev_10_bars = min(10, len(closes) - 1)
    cond_a = (
        trend not in ("bearish", "strong_bearish") and
        today_close > ma20 and
        closes[-2] <= prev_ma20 * 1.01 and
        today_close > prev_10_high_close and
        vol_ratio >= 1.2 and
        close_pos >= 0.65 and
        upper_shadow < 0.40 and
        daily_ret >= 0.01 and daily_ret < limit_pct - 0.005 and
        not one_word_limit_up and
        not recently_limit_down
    )
    if cond_a:
        entry = today_close
        subtype = "aggressive" if daily_ret >= limit_pct * 0.7 else "confirmed"
        sl_atr = entry - 1.5 * atr_val if atr_val else entry * 0.95
        sl_struct = min(ma20 * 0.97, today_low)
        sl = sl_atr if atr_val else sl_struct
        risk = safe_div(entry - sl, entry) if entry > 0 else 0
        triggers.append({
            "trigger": "breakout", "label": "放量突破买入",
            "strength": "confirmed" if risk <= 0.08 else "watch",
            "subtype": subtype,
            "detail": "放量站上MA20并突破前10日高点",
            "entry_price": round(entry, 2),
            "stop_loss": round(sl, 2),
            "atr_stop": round(sl_atr, 2) if atr_val else None,
            "structure_stop": round(sl_struct, 2),
            "risk_pct": round(risk, 4),
            "atr14": round(atr_val, 2) if atr_val else None,
        })

    # --- Signal B: 缩量回踩 ---
    cond_b = (
        trend in ("bullish", "strong_bullish") and
        today_low <= ma20 * 1.03 and
        today_close >= ma20 * 0.98 and
        today_close >= today_open and
        today_close > closes[-2] and
        vol_ratio < 0.9 and
        daily_ret > -0.08 and
        not one_word_limit_down and
        not recently_limit_down
    )
    if cond_b:
        entry = today_close
        sl_atr = entry - 1.5 * atr_val if atr_val else entry * 0.95
        sl_struct = ma20 * 0.97
        sl = min(sl_atr, sl_struct)
        risk = safe_div(entry - sl, entry) if entry > 0 else 0
        triggers.append({
            "trigger": "pullback", "label": "缩量回踩买入",
            "strength": "confirmed" if risk <= 0.08 else "watch",
            "subtype": "confirmed",
            "detail": "多头趋势中缩量回踩MA20并收阳",
            "entry_price": round(entry, 2),
            "stop_loss": round(sl, 2),
            "atr_stop": round(sl_atr, 2) if atr_val else None,
            "structure_stop": round(sl_struct, 2),
            "risk_pct": round(risk, 4),
            "atr14": round(atr_val, 2) if atr_val else None,
        })

    # --- Signal C: 金叉 ---
    ma50_arr_local = rolling_mean(closes, 50)
    ma50 = latest_non_null(ma50_arr_local)
    prev_ma20_2 = ma20_arr[-2] if len(ma20_arr) >= 2 else ma20
    prev_ma50_2 = ma50_arr_local[-2] if len(ma50_arr_local) >= 2 else ma50
    cond_c = (
        ma20 > ma50 and
        prev_ma20_2 is not None and prev_ma50_2 is not None and
        prev_ma20_2 <= prev_ma50_2 and
        trend not in ("bearish", "strong_bearish") and
        not one_word_limit_up
    )
    if cond_c:
        triggers.append({
            "trigger": "golden_cross", "label": "金叉观察",
            "strength": "watch",
            "subtype": "watch",
            "detail": "MA20上穿MA50，关注后续确认",
            "entry_price": round(today_close, 2),
            "stop_loss": round(today_close * 0.95, 2),
            "risk_pct": 0.05,
        })

    # --- Signal D: 强势突破 ---
    cond_d = (
        trend in ("bullish", "strong_bullish") and
        momentum in ("super_strong", "strong") and
        today_close == max(closes[-20:]) and
        vol_ratio > 0.8 and
        close_pos >= 0.5 and
        not one_word_limit_up
    )
    if cond_d:
        entry = today_close
        sl_atr = entry - 1.5 * atr_val if atr_val else entry * 0.95
        sl_struct = ma20
        sl = sl_atr if atr_val else sl_struct
        risk = safe_div(entry - sl, entry) if entry > 0 else 0
        triggers.append({
            "trigger": "strong_break", "label": "强势突破买入",
            "strength": "confirmed",
            "subtype": "confirmed",
            "detail": "强势股创新20日高",
            "entry_price": round(entry, 2),
            "stop_loss": round(sl, 2),
            "atr_stop": round(sl_atr, 2) if atr_val else None,
            "structure_stop": round(sl_struct, 2),
            "risk_pct": round(risk, 4),
            "atr14": round(atr_val, 2) if atr_val else None,
        })

    return triggers

# ── Conclusion ──

def decide_conclusion(short_trend, trend, momentum, volume_signal, position,
                      buy_triggers, one_word_limit_down, recently_limit_down):
    """Decision tree — primary: short_trend (MA10/20/30/60), modifier: trend (MA20/50/120/250)."""

    # Best buy trigger
    confirmed = [t for t in buy_triggers if t["strength"] == "confirmed"]
    watch_triggers = [t for t in buy_triggers if t["strength"] == "watch"]
    has_buy = len(confirmed) > 0
    has_watch = len(watch_triggers) > 0

    # ── Trend helpers ──
    ST_BULL = short_trend in ("strong_bullish", "bullish")
    ST_BEAR = short_trend in ("strong_bearish", "bearish")
    T_BULL  = trend in ("strong_bullish", "bullish")
    T_BEAR  = trend in ("strong_bearish", "bearish")
    T_STRONG_BEAR = trend == "strong_bearish"

    long_label = {"strong_bullish":"强多头","bullish":"多头","recovering":"修复中","neutral":"震荡",
                  "bearish":"空头","strong_bearish":"强空头"}.get(trend, trend)
    short_label = {"strong_bullish":"强多头","bullish":"多头","recovering":"修复中","neutral":"震荡",
                   "bearish":"空头","strong_bearish":"强空头"}.get(short_trend, short_trend)

    # Step 0: insufficient data
    if short_trend == "insufficient_data":
        return "insufficient_data", "数据不足", "gray", "交易日不足60日"

    # Step 1: forced avoid
    if one_word_limit_down:
        return "avoid", "回避", "red", "一字跌停，强制回避"
    if short_trend == "strong_bearish" and momentum == "weak":
        return "avoid", "回避", "red", f"短期{short_label} + 动量弱势"
    if volume_signal == "divergence" and ST_BEAR:
        return "avoid", "回避", "red", f"短期{short_label} + 量价背离"

    # Step 2: buy triggers
    if has_buy:
        best = confirmed[0]
        if ST_BULL and not T_BEAR:
            if momentum != "weak" and volume_signal != "divergence" and position != "overheated":
                if not recently_limit_down and best.get("risk_pct", 0) <= 0.08:
                    return "buy_confirmed", "确认买入", "green", f"短期{short_label} + {best['label']}"
        return "buy_watch", "买点观察", "yellow", f"有{best['label']}但条件不完全确认"
    if has_watch:
        return "buy_watch", "买点观察", "yellow", watch_triggers[0]["detail"]

    # Step 3: short-term bullish scenarios
    if short_trend == "strong_bullish" and T_BULL:
        if volume_signal != "divergence" and position != "overheated":
            return "bullish_strong", "短期强势", "green", f"短期{short_label} + 长期{long_label}共振"
        return "hold_watch", "观望持有", "yellow", f"短期强势但{position}过高"
    if short_trend == "strong_bullish" and T_BEAR:
        return "short_up_long_down", "短强长空", "yellow", f"短期{short_label}但长期{trend}压制"
    if short_trend == "bullish" and T_BULL:
        return "bullish", "短期偏多", "green", f"短期{short_label} + 长期{trend}配合"
    if short_trend == "bullish" and T_BEAR:
        return "short_up_long_down", "短线反弹", "yellow", f"短期偏多但长期{trend}，谨慎追高"
    if short_trend == "recovering" and not T_STRONG_BEAR:
        return "recovering", "修复中", "yellow", f"短期{short_label}，关注能否转势"
    if short_trend == "recovering" and T_STRONG_BEAR:
        return "hold_watch", "观望持有", "yellow", f"短期修复但长期强空压制"

    # Step 4: neutral
    if short_trend == "neutral" and T_BULL:
        return "neutral_bullish", "横盘偏多", "yellow", f"短期横盘，长期{trend}偏多"
    if short_trend == "neutral" and T_BEAR:
        return "neutral_bearish", "横盘偏空", "yellow", f"短期横盘，长期{trend}偏空"

    # Step 5: short-term bearish
    if ST_BEAR and volume_signal == "divergence":
        return "avoid", "回避", "red", f"短期{short_label}+量价背离"
    if short_trend == "bearish":
        if position == "low" and not T_STRONG_BEAR:
            return "left_observe", "左侧观察", "yellow", f"短期偏空但历史低位，等反转"
        return "avoid", "回避", "red", f"短期{short_label}，回避"
    if short_trend == "strong_bearish":
        if T_BULL and position == "low":
            return "short_down_long_up", "短空长多", "yellow", f"短期{short_label}但长期{trend}+低位"
        return "avoid", "回避", "red", f"短期{short_label}，回避"

    # Step 6: position-based
    if position == "low" and not ST_BEAR:
        return "left_observe", "左侧观察", "yellow", "历史低位，等趋势反转"
    if position == "overheated":
        return "hold_watch", "观望持有", "yellow", "位置过热"

    return "hold_watch", "观望持有", "yellow", "信号不明确，观望"

# ── Limit detection ──

def detect_limits(df, market_plate, lookback=3):
    """Detect limit up/down and one-word limits."""
    if len(df) < 2:
        return False, False, False, False

    limit_pct = get_limit_pct(market_plate)
    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # one-word limit up: high=low=close and near limit
    one_word_up = False
    if today["volume"] > 0:
        if today["high"] == today["low"] == today["close"]:
            if today["close"] >= yesterday["close"] * (1 + limit_pct - 0.005):
                one_word_up = True

    # one-word limit down
    one_word_down = False
    if today["volume"] > 0:
        if today["high"] == today["low"] == today["close"]:
            down_pct = 1 - limit_pct
            if today["close"] <= yesterday["close"] * (down_pct + 0.005):
                one_word_down = True

    # recent limit down (last N days)
    recent_down = False
    if lookback > 0 and len(df) >= lookback + 1:
        for i in range(1, lookback + 1):
            if len(df) - 1 - i < 0:
                break
            t = df.iloc[-1 - i]
            y = df.iloc[-2 - i]
            if t["volume"] > 0 and y["volume"] > 0:
                down_pct = 1 - limit_pct
                if t["close"] <= y["close"] * down_pct:
                    recent_down = True
                    break

    return one_word_up, one_word_down, recent_down


# ── Main ──

def main(trading_day: str | None = None):
    t0 = time.time()

    # Output path: use date-specific name if trading_day is set
    global OUTPUT
    if trading_day:
        OUTPUT = DATA_DIR / f"dataset_technical_eval_{trading_day}.json"

    # Load RPS data (array of records → dict keyed by symbol)
    rps_data = {}
    if RPS_PATH.is_file():
        with open(RPS_PATH) as f:
            raw = json.load(f)
        if isinstance(raw, list):
            # Filter by trading_day if specified
            by_symbol: dict[str, list] = {}
            for row in raw:
                td = str(row.get("trading_day", ""))
                if trading_day and td > trading_day:
                    continue
                sym = str(row.get("symbol", ""))
                if len(sym) == 6:
                    by_symbol.setdefault(sym, []).append(row)
            for sym, rows in by_symbol.items():
                rows.sort(key=lambda r: str(r.get("trading_day", "")), reverse=True)
                latest = rows[0]
                rps_data[sym] = {
                    "rps_20": latest.get("rps_20"),
                    "rps_50": latest.get("rps_50"),
                    "rps_120": latest.get("rps_120"),
                    "rps_250": latest.get("rps_250"),
                }
    print(f"RPS loaded: {len(rps_data)} symbols")

    # Load price percentile
    pct_data = {}
    if PCT_PATH.is_file():
        with open(PCT_PATH) as f:
            pct_data = json.load(f)
    print(f"Price percentile loaded: {len(pct_data)} entries")

    # Scan symbols
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    symbols = set()
    for market_dir in ("sh", "sz", "bj"):
        mdir = Path(TDX_DIR) / "vipdoc" / market_dir / "lday"
        if mdir.exists():
            for f in mdir.glob("*.day"):
                code = f.stem
                if code.startswith(market_dir):
                    code = code[len(market_dir):]
                if code.isdigit() and len(code) == 6:
                    symbols.add(code)

    symbols = sorted(symbols)
    print(f"Symbols: {len(symbols)}")

    results = {}
    done = errors = 0

    for symbol in symbols:
        try:
            daily = reader.daily(symbol=symbol)
            if daily is None or daily.empty:
                errors += 1; continue

            daily = daily.sort_index()
            # Truncate to trading_day if specified
            if trading_day:
                mask = daily.index <= trading_day
                daily = daily.loc[mask]
                if daily.empty:
                    errors += 1; continue
            if len(daily) < MIN_DAYS:
                errors += 1; continue

            closes = daily["close"].tolist()
            highs = daily["high"].tolist()
            lows = daily["low"].tolist()
            opens = daily["open"].tolist()
            volumes = daily["volume"].tolist()
            available = len(closes)

            # Data quality
            if available >= 250:
                dq = "full"
            elif available >= 120:
                dq = "partial_120"
            elif available >= 60:
                dq = "partial_60"
            else:
                dq = "insufficient"

            # Market plate
            plate = detect_market_plate(symbol)
            one_word_up, one_word_down, recent_down = detect_limits(daily, plate)

            # Indicators
            atr_val, atr_pct, atr_bars = compute_atr(highs, lows, closes)

            # Trend
            trend, trend_label, trend_detail = classify_trend(closes, available)

            # Short-term trend (MA10/20/30/60)
            short_trend, short_trend_label, short_trend_detail = classify_short_trend(closes, available)

            # Previous day's trend (for trend-switch filter)
            if available > 60:
                prev_trend, prev_trend_label, _prev_detail = classify_trend(closes[:-1], available - 1)
            else:
                prev_trend = prev_trend_label = ""
            # Previous day's short trend
            if available > 30:
                prev_short_trend, prev_short_trend_label, _ = classify_short_trend(closes[:-1], available - 1)
            else:
                prev_short_trend = prev_short_trend_label = ""
            ma20_arr = rolling_mean(closes, 20)

            # Momentum (from RPS)
            rps = rps_data.get(symbol, {})
            r20 = rps.get("rps_20") if isinstance(rps, dict) else None
            r50 = rps.get("rps_50") if isinstance(rps, dict) else None
            r120 = rps.get("rps_120") if isinstance(rps, dict) else None
            momentum, momentum_label, momentum_detail = classify_momentum(r20, r50, r120)

            # Volume
            vol_signal, vol_label, vol_detail, vol_ratio, close_pos, upper_shadow = classify_volume(
                volumes, closes, opens, highs, lows
            )

            # Position
            position, position_label, position_detail = classify_position(
                pct_data.get(symbol), closes, available
            )

            # Golden Cross
            golden_cross, golden_cross_label, golden_cross_detail = detect_golden_crosses(closes, available)
            # MACD Cross
            macd_cross, macd_cross_label, macd_cross_detail = detect_macd_cross(closes, available)

            # Buy triggers
            triggers = evaluate_buy_triggers(
                trend, trend_label, momentum, momentum_label,
                closes, volumes, highs, lows, opens,
                ma20_arr, atr_val, atr_pct, atr_bars,
                vol_ratio, close_pos, upper_shadow,
                plate, recent_down, one_word_up, one_word_down
            )

            # Conclusion
            conclusion, conclusion_label, conclusion_color, conclusion_reason = decide_conclusion(
                short_trend, trend, momentum, vol_signal, position,
                triggers, one_word_down, recent_down
            )

            # Best trigger
            best_t = triggers[0] if triggers else None

            results[symbol] = {
                "symbol": symbol,
                "data_quality": dq,
                "available_days": available,
                "market_plate": plate,
                "one_word_limit_up": one_word_up,
                "one_word_limit_down": one_word_down,
                "recently_limit_down": recent_down,
                "trend": trend,
                "trend_label": trend_label,
                "trend_detail": trend_detail,
                "trend_prev": prev_trend,
                "trend_prev_label": prev_trend_label,
                "short_trend": short_trend,
                "short_trend_label": short_trend_label,
                "short_trend_detail": short_trend_detail,
                "short_trend_prev": prev_short_trend,
                "short_trend_prev_label": prev_short_trend_label,
                "momentum": momentum,
                "momentum_label": momentum_label,
                "momentum_detail": momentum_detail,
                "volume_signal": vol_signal,
                "volume_label": vol_label,
                "volume_detail": vol_detail,
                "position": position,
                "position_label": position_label,
                "position_detail": position_detail,
                "golden_cross": golden_cross,
                "golden_cross_label": golden_cross_label,
                "golden_cross_detail": golden_cross_detail,
                "macd_cross": macd_cross,
                "macd_cross_label": macd_cross_label,
                "macd_cross_detail": macd_cross_detail,
                "atr14": round(atr_val, 2) if atr_val else None,
                "atr14_pct": round(atr_pct, 4) if atr_pct else None,
                "buy_triggers": triggers,
                "buy_trigger": best_t["trigger"] if best_t else None,
                "buy_trigger_label": best_t["label"] if best_t else None,
                "buy_trigger_detail": best_t["detail"] if best_t else None,
                "entry_price": best_t["entry_price"] if best_t else None,
                "stop_loss": best_t["stop_loss"] if best_t else None,
                "risk_pct": best_t["risk_pct"] if best_t else None,
                "conclusion": conclusion,
                "conclusion_label": conclusion_label,
                "conclusion_color": conclusion_color,
                "conclusion_reason": conclusion_reason,
            }

            done += 1
            if done % 500 == 0:
                elapsed = time.time() - t0
                print(f"  {done}/{len(symbols)} — {elapsed:.0f}s, {errors} err")

        except Exception as e:
            errors += 1

    # Write output
    output = {
        "data_date": trading_day or time.strftime("%Y-%m-%d"),
        "total_stocks": len(results),
        "stocks": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\nDone: {len(results)} stocks in {elapsed:.0f}s, {errors} errors")
    print(f"Output: {OUTPUT}")

    # Stats
    conclusions = {}
    for r in results.values():
        c = r["conclusion"]
        conclusions[c] = conclusions.get(c, 0) + 1
    print("\nConclusion distribution:")
    for c, n in sorted(conclusions.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build technical evaluation dataset")
    parser.add_argument("--trading-day", type=str, default=None,
                        help="Compute as of this date (YYYY-MM-DD). Default: today")
    args = parser.parse_args()
    main(trading_day=args.trading_day)
