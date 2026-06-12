#!/usr/bin/env python3
"""Build stock screener preset-strategy signal datasets from local Tongdaxin daily data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.index import (
    DEFAULT_DATASET_DIR,
    load_industry_valuation_rows,
    load_rps_rows,
)

DEFAULT_TDX_DIR = "/mnt/c/new_tdx64"
DEFAULT_OUTPUT = DEFAULT_DATASET_DIR / "dataset_stock_screener_strategies_current.json"
STRATEGY_FIRST = "rps_first"
STRATEGY_MA_CROSS = "ma_cross"
STRATEGY_WASHOUT = "washout"
STRATEGY_RPS_CLIMB = "rps_climb"
STRATEGY_BLOWUP_STALL = "blowup_stall"
STRATEGY_BLOWUP_BREAK = "blowup_break"
STRATEGY_MA_PULLBACK = "ma_pullback"
STRATEGY_METADATA = {
    STRATEGY_FIRST: {
        "label": "RPS首次",
    },
    STRATEGY_MA_CROSS: {
        "label": "均线选股",
    },
    STRATEGY_WASHOUT: {
        "label": "涨停洗盘",
    },
    STRATEGY_RPS_CLIMB: {
        "label": "RPS爬升",
    },
    STRATEGY_BLOWUP_STALL: {
        "label": "爆量滞涨",
    },
    STRATEGY_BLOWUP_BREAK: {
        "label": "爆量突破",
    },
    STRATEGY_MA_PULLBACK: {
        "label": "均线回踩",
    },
}


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _return_pct(closes: list[float], end_index: int, window: int) -> float | None:
    start_index = end_index - window
    if start_index < 0 or end_index < 0 or end_index >= len(closes):
        return None
    base = closes[start_index]
    if base == 0:
        return None
    return (closes[end_index] - base) / base * 100.0


def _compute_past_days_rps(reader, rps_rows, ndays=5):
    """Compute cross-sectional RPS for the past N trading days.
    
    Uses the pre-computed RPS history dataset to look up RPS values for prior days.
    Returns a list of dicts, one per past day (index 0 = yesterday).
    Each dict maps (market, symbol) → {rps_20, rps_50, rps_120, rps_250}.
    """
    import json as _json
    
    history_path = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.json"
    if not history_path.exists():
        return []
    
    all_history = _json.loads(history_path.read_text(encoding="utf-8"))
    
    # Get unique trading days sorted
    trading_days = sorted(set(str(h.get("trading_day", "")) for h in all_history if h.get("trading_day")))
    if not trading_days:
        return []
    
    # Build lookup: trading_day → {(market, symbol): {rps_20, rps_50, rps_120, rps_250}}
    rps_by_day: dict[str, dict[tuple[str, str], dict[str, float | None]]] = {}
    for h in all_history:
        td = str(h.get("trading_day", ""))
        if td not in rps_by_day:
            rps_by_day[td] = {}
        key = (str(h.get("market", "")).strip().lower(), str(h.get("symbol", "")).strip())
        rps_by_day[td][key] = {
            "rps_20": h.get("rps_20"),
            "rps_50": h.get("rps_50"),
            "rps_120": h.get("rps_120"),
            "rps_250": h.get("rps_250"),
        }
    
    # Latest day is index -1. Yesterday = -2, 2 days ago = -3, etc.
    result = []
    for i in range(2, min(2 + ndays, len(trading_days) + 1)):
        td = trading_days[-i] if i <= len(trading_days) else None
        if td and td in rps_by_day:
            result.append(rps_by_day[td])
    
    return result


def _rps_first_candidates(rps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find stocks where RPS total (rps20+rps50+rps120+rps250) crosses above 360 today."""
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        rps120 = _coerce_float(row.get("rps_120"))
        rps250 = _coerce_float(row.get("rps_250"))
        if None in (rps20, rps50, rps120, rps250):
            continue
        rps_total = rps20 + rps50 + rps120 + rps250
        if rps_total > 360:
            candidates.append(row)
    return candidates

def build_rps_first_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """RPS首次：RPS总分(rps20+rps50+rps120+rps250)上穿360, 且过去60个交易日首次满足."""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    candidates = _rps_first_candidates(rps_rows)
    if not candidates:
        return []

    # Compute cross-sectional RPS for past 60 trading days
    past_rps_by_day = _compute_past_days_rps(reader, rps_rows, ndays=60)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    results: list[dict[str, Any]] = []
    for row in candidates:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        key = (market_val, symbol_val)

        rps20_t = _coerce_float(row.get("rps_20")) or 0
        rps50_t = _coerce_float(row.get("rps_50")) or 0
        rps120_t = _coerce_float(row.get("rps_120")) or 0
        rps250_t = _coerce_float(row.get("rps_250")) or 0
        total_today = rps20_t + rps50_t + rps120_t + rps250_t

        # Check if this stock ever had RPS total > 360 in the past 60 days
        ever_met = False
        yesterday_total = None
        for day_idx, day_rps in enumerate(past_rps_by_day):
            rps = day_rps.get(key, {})
            r20 = rps.get("rps_20")
            r50 = rps.get("rps_50")
            r120 = rps.get("rps_120")
            r250 = rps.get("rps_250")
            if None in (r20, r50, r120, r250):
                continue
            day_total = r20 + r50 + r120 + r250
            if day_idx == 0:  # yesterday
                yesterday_total = day_total
            if day_total > 360:
                ever_met = True
                break

        is_first = not ever_met
        crossed = yesterday_total is not None and yesterday_total <= 360

        conditions: dict[str, object] = {
            "rps_total": round(total_today, 2),
            "rps20": round(rps20_t, 2),
            "rps50": round(rps50_t, 2),
            "rps120": round(rps120_t, 2),
            "rps250": round(rps250_t, 2),
            "cross_above_360": crossed,
            "yesterday_total": round(yesterday_total, 2) if yesterday_total is not None else None,
            "first_in_60d": is_first,
        }

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_FIRST,
            "strategy_label": STRATEGY_METADATA[STRATEGY_FIRST]["label"],
            "passed": is_first and crossed,
            "conditions": conditions,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current+dataset_stock_rps_history",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_ma_cross_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """均线选股：MA5上穿MA20 + MA30>MA5>MA20>MA10 + 阳线 + MA5/MA10上升 + 均线粘合<10%"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        if len(closes) < 35:
            continue

        def _ma(values, period, idx):
            if idx < period - 1:
                return None
            return sum(values[idx - period + 1 : idx + 1]) / period

        ti = len(closes) - 1
        yi = ti - 1

        ma5_t = _ma(closes, 5, ti)
        ma10_t = _ma(closes, 10, ti)
        ma20_t = _ma(closes, 20, ti)
        ma30_t = _ma(closes, 30, ti)
        ma5_y = _ma(closes, 5, yi)
        ma10_y = _ma(closes, 10, yi)
        ma20_y = _ma(closes, 20, yi)

        if None in (ma5_t, ma10_t, ma20_t, ma30_t, ma5_y, ma10_y, ma20_y):
            continue

        # COND1: CROSS(MA5, MA20)
        cross = ma5_t > ma20_t and ma5_y <= ma20_y
        # COND2: MA30 > MA5 > MA20 > MA10
        order_ok = ma30_t > ma5_t > ma20_t > ma10_t
        # COND3+4: we use yesterday's close vs open as approximation for 阳线 + rising
        opens = daily["open"].astype(float).tolist()
        bullish = closes[ti] > opens[ti] if len(opens) > ti else True
        rising = ma5_t > ma5_y and ma10_t > ma10_y
        # COND5: spread < 10%
        mas = [ma5_t, ma10_t, ma20_t, ma30_t]
        spread = (max(mas) - min(mas)) / min(mas) * 100.0
        sticky = spread < 10.0

        passed = cross and order_ok and bullish and rising and sticky

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_MA_CROSS,
            "strategy_label": STRATEGY_METADATA[STRATEGY_MA_CROSS]["label"],
            "passed": passed,
            "conditions": {
                "cross_ma5_ma20": cross,
                "order_ma30_5_20_10": order_ok,
                "bullish": bullish,
                "rising_ma5_ma10": rising,
                "sticky_pct": round(spread, 2),
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results

def build_ma_pullback_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """均线回踩：多头趋势(MA20>MA60+RPS20>60)+回踩MA20支撑(回调5-15%)+止跌信号(缩量+阳线+下影线)"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        if rps20 is None or rps50 is None:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        opens = daily["open"].astype(float).tolist()
        highs = daily["high"].astype(float).tolist()
        lows = daily["low"].astype(float).tolist()
        volumes = daily["volume"].astype(float).tolist()
        if len(closes) < 70:
            continue

        def _ma(values, period, idx):
            if idx < period - 1:
                return None
            return sum(values[idx - period + 1 : idx + 1]) / period

        ti = len(closes) - 1
        close_t = closes[ti]

        ma20_t = _ma(closes, 20, ti)
        ma60_t = _ma(closes, 60, ti)
        if None in (ma20_t, ma60_t):
            continue

        # ---- Layer 1: 确认多头趋势 ----
        # MA20 > MA60 (中长期多头排列)
        bull_ma = ma20_t > ma60_t
        # close > MA60 (没破中长线)
        above_ma60 = close_t > ma60_t
        # RPS强度
        rps_ok = rps20 > 60.0 or rps50 > 65.0
        if not (bull_ma and above_ma60 and rps_ok):
            continue

        # ---- Layer 2: 检测回调至支撑位 ----
        # 20日最高
        recent_high = max(highs[max(0, ti - 19):ti + 1])
        pullback_pct = (recent_high - close_t) / recent_high * 100.0

        # 科技股放宽到18%（688/300/301开头）
        is_tech = symbol_val.startswith(("688", "300", "301"))
        pb_max = 18.0 if is_tech else 15.0
        if pullback_pct < 5.0 or pullback_pct > pb_max:
            continue

        # 距MA20距离
        dist_ma20 = (close_t - ma20_t) / ma20_t * 100.0
        if dist_ma20 < -3.0 or dist_ma20 > 2.0:
            continue

        # 缩量下跌: 近5日均量 / 20日均量 < 0.8
        vol_5_avg = sum(volumes[max(0, ti - 4):ti + 1]) / min(5, ti + 1)
        vol_20_avg = sum(volumes[max(0, ti - 19):ti + 1]) / min(20, ti + 1)
        vol_shrink = (vol_5_avg / vol_20_avg) < 0.8 if vol_20_avg > 0 else False

        # 最近5日未创新低
        low_recent5 = min(lows[max(0, ti - 4):ti + 1])
        low_prev5 = min(lows[max(0, ti - 9):max(0, ti - 4) + 1]) if ti >= 5 else low_recent5
        no_new_low = low_recent5 >= low_prev5

        if not (vol_shrink and no_new_low):
            continue

        # ---- Layer 3: 确认买入信号 ----
        # 今日止跌: 收阳 或 收盘>昨收
        close_y = closes[ti - 1] if ti > 0 else close_t
        open_t = opens[ti] if len(opens) > ti else close_t
        stopped_falling = close_t >= close_y or close_t > open_t

        # 量能回暖: 今日量 > 5日均量
        vol_recovery = volumes[ti] > vol_5_avg if len(volumes) > ti else False

        # 下影线比例
        candle_range = highs[ti] - lows[ti] if ti < len(highs) else 1
        lower_shadow = (min(open_t, close_t) - lows[ti]) / candle_range if candle_range > 0 else 0

        if not (stopped_falling and vol_recovery):
            continue

        passed = True

        # ---- 信号评分 ----
        pb_norm = min(pullback_pct / pb_max, 1.0)
        dist_score = max(0, 1.0 - abs(dist_ma20) / 3.0)
        rps_score = rps20 / 100.0
        vol_score = min(volumes[ti] / vol_5_avg, 2.0) / 2.0 if vol_5_avg > 0 else 0
        shadow_score = min(lower_shadow / 0.5, 1.0)
        candlestick_bonus = 0.05 if lower_shadow > 0.5 else 0.0

        signal_score = round(
            pb_norm * 0.30
            + dist_score * 0.20
            + rps_score * 0.20
            + vol_score * 0.15
            + shadow_score * 0.10
            + candlestick_bonus,
            4
        )

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_MA_PULLBACK,
            "strategy_label": STRATEGY_METADATA[STRATEGY_MA_PULLBACK]["label"],
            "passed": passed,
            "conditions": {
                "pullback_pct": round(pullback_pct, 2),
                "dist_ma20_pct": round(dist_ma20, 2),
                "rps20": round(rps20, 2),
                "rps50": round(rps50, 2) if rps50 else None,
                "vol_ratio": round(volumes[ti] / vol_5_avg, 2) if vol_5_avg > 0 and len(volumes) > ti else None,
                "lower_shadow": round(lower_shadow, 2),
                "ma20": round(ma20_t, 2),
                "ma60": round(ma60_t, 2),
                "close": round(close_t, 2),
                "is_tech": is_tech,
                "signal_score": signal_score,
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
        })

    results.sort(key=lambda item: (
        -float(item.get("conditions", {}).get("signal_score", 0)),
        item.get("market", ""),
        item.get("symbol", ""),
    ))
    return results


def build_washout_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """涨停洗盘：30日内有首板涨停; 涨停次日高开低走且量2-4倍; 最新价首次站上洗盘日开盘价"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def _limit_up_threshold(symbol_str: str) -> float:
        """Return limit-up gain threshold based on board (symbol prefix)."""
        if symbol_str.startswith("688"):
            return 19.5
        if symbol_str.startswith(("300", "301")):
            return 19.5
        if symbol_str.startswith("92"):
            return 29.5
        return 9.5

    results: list[dict[str, Any]] = []
    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        opens = daily["open"].astype(float).tolist()
        highs = daily["high"].astype(float).tolist()
        volumes = daily["volume"].astype(float).tolist()
        if len(closes) < 60:
            continue

        threshold = _limit_up_threshold(symbol_val)
        n = len(closes)

        # Condition A: Find a 首板涨停 in the last 30 trading days
        # 首板 = limit-up day where the previous day was NOT a limit-up
        lu_idx = -1
        scan_start = max(0, n - 30)
        for i in range(n - 2, scan_start - 1, -1):  # n-2 to leave room for next-day check
            # Check if bar i is a limit-up
            c = closes[i]
            h = highs[i]
            prev_c = closes[i - 1]
            if prev_c <= 0 or c <= 0:
                continue
            gain_pct = (c - prev_c) / prev_c * 100.0
            if gain_pct >= threshold and c >= h * 0.99:
                # Check if it was a 首板 (previous day NOT a limit-up)
                # Need to check i-1 was not a limit-up
                if i - 1 >= 0:
                    prev_prev_c = closes[i - 2] if i - 2 >= 0 else 0
                    if prev_prev_c > 0:
                        prev_gain = (closes[i - 1] - prev_prev_c) / prev_prev_c * 100.0
                        prev_h = highs[i - 1]
                        if prev_gain >= threshold and closes[i - 1] >= prev_h * 0.99:
                            continue  # Previous day was also limit-up, not a 首板
                lu_idx = i
                break

        if lu_idx < 0:
            continue  # No 首板涨停 in last 30 days

        # Condition B: 涨停次日高开低走，成交量2-4倍
        next_idx = lu_idx + 1
        if next_idx >= n:
            continue  # No next-day data

        next_open = opens[next_idx]
        next_close = closes[next_idx]
        prev_close = closes[lu_idx]

        # 高开: next_open > prev_close
        if next_open <= prev_close:
            continue

        # 低走: next_close < next_open (bearish candle)
        if next_close >= next_open:
            continue

        # 成交量: next_vol / lu_vol between 2x and 4x
        lu_vol = volumes[lu_idx]
        next_vol = volumes[next_idx]
        if lu_vol <= 0:
            continue
        vol_ratio = next_vol / lu_vol
        if vol_ratio < 2.0 or vol_ratio > 4.0:
            continue

        washout_open = next_open  # The open of the washout day (target to break above)

        # Condition C: 最新价首次站上涨停后一个交易日（洗盘日）的开盘价
        current_close = closes[-1]
        if current_close <= washout_open:
            continue

        # 首次站上: 洗盘日后、今天之前的所有交易日收盘价都 ≤ 洗盘日开盘价
        first_breakout = True
        for j in range(next_idx + 1, n - 1):
            if closes[j] > washout_open:
                first_breakout = False
                break
        if not first_breakout:
            continue

        # All conditions passed — no PE-TTM filter
        passed = True

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_WASHOUT,
            "strategy_label": STRATEGY_METADATA[STRATEGY_WASHOUT]["label"],
            "passed": passed,
            "conditions": {
                "limit_up_gain_pct": round((closes[lu_idx] - closes[lu_idx - 1]) / closes[lu_idx - 1] * 100.0, 2),
                "washout_open_above": round((next_open - prev_close) / prev_close * 100.0, 2),
                "washout_body_pct": round((next_open - next_close) / next_open * 100.0, 2),
                "vol_ratio": round(vol_ratio, 2),
                "current_above_washout_open": round((current_close - washout_open) / washout_open * 100.0, 2),
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_rps_climb_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """RPS爬升：RPS20>50>120>250多头排列; RPS20>50; RPS20/50/120连续3天高于5日前"""
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    # Load RPS history dataset
    history_path = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.json"
    if not history_path.exists():
        return []
    all_history = json.loads(history_path.read_text(encoding="utf-8"))

    # Build per-stock lookup: {(market, symbol): {trading_day: {rps_20, rps_50, rps_120, rps_250}}}
    stock_history: dict[tuple[str, str], dict[str, dict[str, float | None]]] = {}
    for h in all_history:
        key = (str(h.get("market", "")).strip(), str(h.get("symbol", "")).strip())
        if key not in stock_history:
            stock_history[key] = {}
        stock_history[key][str(h.get("trading_day", ""))] = {
            "rps_20": h.get("rps_20"),
            "rps_50": h.get("rps_50"),
            "rps_120": h.get("rps_120"),
            "rps_250": h.get("rps_250"),
        }

    sample_dates = sorted(next(iter(stock_history.values())).keys()) if stock_history else []
    if not sample_dates:
        return []

    results: list[dict[str, Any]] = []
    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        key = (market_val, symbol_val)
        hist = stock_history.get(key, {})
        if not hist:
            continue

        # Get ordered history for this stock
        today_str = sample_dates[-1]
        ordered = sorted(
            [(d, h) for d, h in hist.items() if d <= today_str],
            key=lambda x: x[0],
        )
        if len(ordered) < 10:
            continue

        # Find today's index in ordered list
        today_idx = None
        for i, (d, _h) in enumerate(ordered):
            if d == today_str:
                today_idx = i
                break
        if today_idx is None or today_idx < 7:
            continue

        def _rps_at(idx: int) -> dict[str, float | None]:
            _, h = ordered[idx]
            return {
                "rps_20": _coerce_float(h.get("rps_20")),
                "rps_50": _coerce_float(h.get("rps_50")),
                "rps_120": _coerce_float(h.get("rps_120")),
                "rps_250": _coerce_float(h.get("rps_250")),
            }

        today = _rps_at(today_idx)

        # Condition 1: RPS20 > RPS50 > RPS120 > RPS250 (bullish alignment)
        r20 = today["rps_20"]
        r50 = today["rps_50"]
        r120 = today["rps_120"]
        r250 = today["rps_250"]
        if None in (r20, r50, r120, r250):
            continue
        if not (r20 > r50 > r120 > r250):
            continue

        # Condition 2: RPS20 > 50
        if r20 <= 50:
            continue

        # Condition 3: RPS20/50/120 > 5-day-ago values, for 3 consecutive days
        def _climb_ok(day_idx: int) -> bool:
            """Check if at day_idx, all RPS20/50/120 are above their 5-day-ago values."""
            ref_idx = day_idx - 5
            if ref_idx < 0:
                return False
            cur = _rps_at(day_idx)
            ref = _rps_at(ref_idx)
            for w in ("rps_20", "rps_50", "rps_120"):
                cv = cur[w]
                rv = ref[w]
                if cv is None or rv is None or cv <= rv:
                    return False
            return True

        climb_today = _climb_ok(today_idx)
        climb_yesterday = _climb_ok(today_idx - 1)
        climb_2d_ago = _climb_ok(today_idx - 2)

        if not (climb_today and climb_yesterday and climb_2d_ago):
            continue

        passed = True

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_RPS_CLIMB,
            "strategy_label": STRATEGY_METADATA[STRATEGY_RPS_CLIMB]["label"],
            "passed": passed,
            "conditions": {
                "rps20": round(r20, 2),
                "rps50": round(r50, 2),
                "rps120": round(r120, 2),
                "rps250": round(r250, 2),
                "bullish_alignment": True,
                "climb_3days": True,
            },
            "generated_at": generated_at,
            "data_source": "dataset_stock_rps_current+dataset_stock_rps_history",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_blowup_break_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """爆量突破：连续两天真阳线上涨; 每天量>3倍50日均量; 涨前5天量均<2倍50日均量"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        opens = daily["open"].astype(float).tolist()
        volumes = daily["volume"].astype(float).tolist()
        if len(closes) < 55:  # need 2 up days + 50 MA + 1 extra
            continue

        n = len(closes)
        t_idx = n - 1   # today
        y_idx = n - 2   # yesterday

        # Condition 1: 连续两天上涨，且每天收盘>开盘（真阳线）
        if not (closes[t_idx] > closes[y_idx] > closes[y_idx - 1]):
            continue
        if not (closes[t_idx] > opens[t_idx] and closes[y_idx] > opens[y_idx]):
            continue

        # 50日成交均量基线: 涨前一天的 50 日均量
        # 涨前一天 = y_idx - 1 (the day before the first up day)
        ma_start = y_idx - 1 - 49
        if ma_start < 0:
            continue
        ma_vol = sum(volumes[ma_start : y_idx]) / 50.0
        if ma_vol <= 0:
            continue

        # Condition 2: 两天上涨的成交量都 > 3x 50日均量
        vol_y = volumes[y_idx]
        vol_t = volumes[t_idx]
        if not (vol_y > ma_vol * 3.0 and vol_t > ma_vol * 3.0):
            continue

        # Condition 3: 涨前5天的成交量都 < 2x 50日均量
        vol_before_ok = True
        for j in range(y_idx - 5, y_idx):
            if j < 0:
                vol_before_ok = False
                break
            if volumes[j] >= ma_vol * 2.0:
                vol_before_ok = False
                break
        if not vol_before_ok:
            continue

        passed = True

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_BLOWUP_BREAK,
            "strategy_label": STRATEGY_METADATA[STRATEGY_BLOWUP_BREAK]["label"],
            "passed": passed,
            "conditions": {
                "vol_ratio_y": round(vol_y / ma_vol, 2),
                "vol_ratio_t": round(vol_t / ma_vol, 2),
                "before_5d_all_below_2x": True,
                "ma_vol": round(ma_vol, 0),
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_blowup_stall_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """爆量滞涨：放巨量但涨幅极小甚至冲高回落，疑似主力出货。

    条件：量>2.5x50日均量 + 涨幅<2% + 上影线>40% 或 近20日>10%
    按信号强度排序：量比越大×涨幅越小×上影越长 = 信号越强
    """
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        if len(daily) < 75:
            continue

        n = len(daily)
        closes = daily["close"].astype(float).tolist()
        opens = daily["open"].astype(float).tolist()
        highs = daily["high"].astype(float).tolist()
        lows = daily["low"].astype(float).tolist()
        volumes = daily["volume"].astype(float).tolist()

        t = n - 1

        ma_start = t - 50
        if ma_start < 0:
            continue
        ma_vol = sum(volumes[ma_start:t]) / 50.0
        if ma_vol <= 0:
            continue

        vol_r = volumes[t] / ma_vol
        if vol_r < 2.5:
            continue

        o_t, c_t, h_t, l_t = opens[t], closes[t], highs[t], lows[t]
        rng = h_t - l_t
        if rng == 0:
            continue
        upper_r = (h_t - max(o_t, c_t)) / rng
        chg = (c_t / closes[t - 1] - 1) * 100

        if chg > 2.0:
            continue

        has_shadow = upper_r > 0.4

        p20 = max(0, t - 20)
        if p20 >= t:
            continue
        ret20 = (c_t / closes[p20] - 1) * 100
        is_high = ret20 > 10.0

        if not (has_shadow or is_high):
            continue

        score = round(vol_r * (1 + upper_r) / max(abs(chg), 0.1), 2)
        if score < 10:
            continue

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_BLOWUP_STALL,
            "strategy_label": STRATEGY_METADATA[STRATEGY_BLOWUP_STALL]["label"],
            "passed": True,
            "conditions": {
                "vol_ratio": round(vol_r, 2),
                "change_pct": round(chg, 2),
                "upper_shadow_ratio": round(upper_r, 2),
                "ret_20d_pct": round(ret20, 2),
                "has_upper_shadow": has_shadow,
                "is_high_position": is_high,
                "ma_vol": round(ma_vol, 0),
                "signal_score": score,
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (-float(item.get("conditions", {}).get("signal_score", 0)),
                                    item.get("market", ""), item.get("symbol", "")))
    return results


def merge_strategy_rows_for_output(output: Path, strategy: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_rows: list[dict[str, Any]] = []
    if output.exists():
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                existing_rows = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                existing_rows = [row for row in payload["rows"] if isinstance(row, dict)]
        except Exception:
            existing_rows = []
    merged = [row for row in existing_rows if str(row.get("strategy", "")).strip() != strategy]
    if rows:
        merged.extend(rows)
    else:
        # Sentinel row: marks this strategy as "built with 0 results" so the API
        # can distinguish from "not yet built" and show 0 results instead of all.
        merged.append({
            "trading_day": "",
            "market": "__sentinel__",
            "symbol": "000000",
            "strategy": strategy,
            "strategy_label": STRATEGY_METADATA.get(strategy, {}).get("label", strategy),
            "passed": False,
            "conditions": {},
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "data_source": "sentinel",
        })
    merged.sort(key=lambda item: (str(item.get("strategy", "")), not bool(item.get("passed")), str(item.get("market", "")), str(item.get("symbol", ""))))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stock screener strategy datasets")
    parser.add_argument("--strategy", default=STRATEGY_FIRST, choices=sorted(STRATEGY_METADATA))
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--trading-day", default=None, help="Build as of historical date (YYYY-MM-DD)")
    args = parser.parse_args()

    trading_day = args.trading_day

    # When trading_day is set, use date-specific output
    if trading_day:
        output = DEFAULT_DATASET_DIR / f"dataset_stock_screener_strategies_{trading_day}.json"
    else:
        output = Path(args.output)

    # Monkey-patch load_rps_rows to use historical RPS when trading_day is set
    if trading_day:
        from app.search.index import load_rps_rows_as_of
        import app.search.index as _idx

        _orig_load_rps_rows = _idx.load_rps_rows
        _idx.load_rps_rows = lambda **kw: load_rps_rows_as_of(trading_day)

        # Also monkey-patch rps_pullback / rps_first which read history directly
        _orig_Reader_factory = Reader.factory

        def _patched_factory(*fa, **kw):
            reader = _orig_Reader_factory(*fa, **kw)
            _orig_daily = reader.daily

            def _daily_wrapper(**dkw):
                result = _orig_daily(**dkw)
                if result is not None and not result.empty and trading_day:
                    result = result.sort_index()
                    mask = result.index <= trading_day
                    result = result.loc[mask]
                return result

            reader.daily = _daily_wrapper
            return reader

        Reader.factory = staticmethod(_patched_factory)

    try:
        if args.strategy == STRATEGY_FIRST:
            rows = build_rps_first_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_MA_CROSS:
            rows = build_ma_cross_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_WASHOUT:
            rows = build_washout_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_RPS_CLIMB:
            rows = build_rps_climb_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_BLOWUP_STALL:
            rows = build_blowup_stall_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_BLOWUP_BREAK:
            rows = build_blowup_break_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_MA_PULLBACK:
            rows = build_ma_pullback_rows(tdxdir=args.tdxdir)
        else:
            rows = build_ma_cross_rows(tdxdir=args.tdxdir)
    finally:
        # Restore monkey-patches
        if trading_day:
            _idx.load_rps_rows = _orig_load_rps_rows
            Reader.factory = staticmethod(_orig_Reader_factory)

    output.parent.mkdir(parents=True, exist_ok=True)
    output_rows = merge_strategy_rows_for_output(output, args.strategy, rows)
    output.write_text(json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    passed_count = sum(1 for row in rows if row.get("passed"))
    print(json.dumps({"ok": True, "strategy": args.strategy, "rows": len(rows), "passed": passed_count, "output": str(output), "output_rows": len(output_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
