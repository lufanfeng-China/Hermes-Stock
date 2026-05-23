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
    evaluate_rps_attack_signal,
    evaluate_rps_pullback_signal,
    evaluate_rps_standard_launch_signal,
    load_industry_valuation_rows,
    load_rps_rows,
)

DEFAULT_TDX_DIR = "/mnt/c/new_tdx64"
DEFAULT_OUTPUT = DEFAULT_DATASET_DIR / "dataset_stock_screener_strategies_current.json"
STRATEGY_STANDARD = "rps_standard_launch"
STRATEGY_ATTACK = "rps_attack"
STRATEGY_PULLBACK = "rps_pullback"
STRATEGY_FIRST = "rps_first"
STRATEGY_MA_CROSS = "ma_cross"
STRATEGY_FIRST_BOARD = "first_board"
STRATEGY_WASHOUT = "washout"
STRATEGY_RPS_CLIMB = "rps_climb"
STRATEGY_BLOWUP_STALL = "blowup_stall"
STRATEGY_METADATA = {
    STRATEGY_STANDARD: {
        "label": "RPS标准",
    },
    STRATEGY_ATTACK: {
        "label": "RPS进攻",
    },
    STRATEGY_PULLBACK: {
        "label": "RPS回踩",
    },
    STRATEGY_FIRST: {
        "label": "RPS首次",
    },
    STRATEGY_MA_CROSS: {
        "label": "均线选股",
    },
    STRATEGY_FIRST_BOARD: {
        "label": "首板股池",
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


def _rps_by_symbol(return_by_symbol: dict[str, float | None]) -> dict[str, float]:
    valid = [(symbol, value) for symbol, value in return_by_symbol.items() if value is not None]
    valid.sort(key=lambda item: (-float(item[1]), item[0]))
    universe_size = len(valid)
    if universe_size == 0:
        return {}
    return {
        symbol: round(((universe_size - rank + 1) / universe_size) * 100.0, 2)
        for rank, (symbol, _value) in enumerate(valid, start=1)
    }


def _latest_rps_candidates(rps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        rps120 = _coerce_float(row.get("rps_120"))
        rps250 = _coerce_float(row.get("rps_250"))
        if None in (rps20, rps50, rps120, rps250):
            continue
        rps_base = rps250 >= 80 and rps120 >= 85 and rps50 >= 88 and rps20 >= 92
        rps_structure = rps20 > rps50 and rps50 >= rps120 - 3 and rps120 >= rps250 - 5
        if rps_base and rps_structure:
            candidates.append(row)
    return candidates


def _latest_rps_attack_candidates(rps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        rps120 = _coerce_float(row.get("rps_120"))
        rps250 = _coerce_float(row.get("rps_250"))
        if None in (rps20, rps50, rps120, rps250):
            continue
        rps_base = rps250 >= 75 and rps120 >= 80 and rps50 >= 82 and rps20 >= 88
        rps_structure = rps20 > rps50 and rps120 >= rps250 - 8
        if rps_base and rps_structure:
            candidates.append(row)
    return candidates


def _build_signal_context(
    rps_rows: list[dict[str, Any]],
    *,
    tdxdir: str,
    candidate_symbols: set[str],
) -> dict[str, dict[str, object]]:
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    context: dict[str, dict[str, object]] = {
        "ref3_return20": {},
        "ref5_return50": {},
        "ref1_return20": {},
        "ref2_return20": {},
        "ref3_return50": {},
        "candidate_bars": {},
    }

    for row in rps_rows:
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        try:
            daily = reader.daily(symbol=symbol)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = [float(value) for value in daily["close"].astype(float).tolist()]
        if len(closes) < 121:
            continue
        latest_index = len(closes) - 1
        context["ref3_return20"][symbol] = _return_pct(closes, latest_index - 3, 20)
        context["ref5_return50"][symbol] = _return_pct(closes, latest_index - 5, 50)
        context["ref1_return20"][symbol] = _return_pct(closes, latest_index - 1, 20)
        context["ref2_return20"][symbol] = _return_pct(closes, latest_index - 2, 20)
        context["ref3_return50"][symbol] = _return_pct(closes, latest_index - 3, 50)

        if symbol in candidate_symbols:
            tail = daily.tail(270)
            bars: list[dict[str, float]] = []
            for _index, bar in tail.iterrows():
                bars.append(
                    {
                        "open": float(bar["open"]),
                        "close": float(bar["close"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "volume": float(bar["volume"]),
                    }
                )
            context["candidate_bars"][symbol] = bars
    return context


def build_rps_standard_launch_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    rps_rows = load_rps_rows()
    candidates = _latest_rps_candidates(rps_rows)
    candidate_symbols = {str(row.get("symbol", "")).strip() for row in candidates}
    rps_by_symbol = {str(row.get("symbol", "")).strip(): row for row in rps_rows if str(row.get("symbol", "")).strip()}
    signal_context = _build_signal_context(rps_rows, tdxdir=tdxdir, candidate_symbols=candidate_symbols)
    ref3_rps20 = _rps_by_symbol(signal_context["ref3_return20"])
    ref5_rps50 = _rps_by_symbol(signal_context["ref5_return50"])
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    results: list[dict[str, Any]] = []
    for row in candidates:
        symbol = str(row.get("symbol", "")).strip()
        latest_rps = rps_by_symbol.get(symbol) or {}
        ref3_rps = {"rps_20": ref3_rps20.get(symbol)}
        ref5_rps = {"rps_50": ref5_rps50.get(symbol)}
        signal = evaluate_rps_standard_launch_signal(
            latest_rps,
            ref3_rps,
            ref5_rps,
            signal_context["candidate_bars"].get(symbol, []),
        )
        results.append(
            {
                "trading_day": row.get("trading_day"),
                "market": str(row.get("market", "")).strip().lower(),
                "symbol": symbol,
                "strategy": STRATEGY_STANDARD,
                "strategy_label": STRATEGY_METADATA[STRATEGY_STANDARD]["label"],
                "passed": bool(signal.get("passed")),
                "conditions": signal.get("conditions") or {},
                "generated_at": generated_at,
                "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
            }
        )
    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_rps_attack_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    rps_rows = load_rps_rows()
    candidates = _latest_rps_attack_candidates(rps_rows)
    candidate_symbols = {str(row.get("symbol", "")).strip() for row in candidates}
    rps_by_symbol = {str(row.get("symbol", "")).strip(): row for row in rps_rows if str(row.get("symbol", "")).strip()}
    signal_context = _build_signal_context(rps_rows, tdxdir=tdxdir, candidate_symbols=candidate_symbols)
    ref1_rps20 = _rps_by_symbol(signal_context["ref1_return20"])
    ref2_rps20 = _rps_by_symbol(signal_context["ref2_return20"])
    ref3_rps50 = _rps_by_symbol(signal_context["ref3_return50"])
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    results: list[dict[str, Any]] = []
    for row in candidates:
        symbol = str(row.get("symbol", "")).strip()
        latest_rps = rps_by_symbol.get(symbol) or {}
        signal = evaluate_rps_attack_signal(
            latest_rps,
            {"rps_20": ref1_rps20.get(symbol)},
            {"rps_20": ref2_rps20.get(symbol)},
            {"rps_50": ref3_rps50.get(symbol)},
            signal_context["candidate_bars"].get(symbol, []),
        )
        results.append(
            {
                "trading_day": row.get("trading_day"),
                "market": str(row.get("market", "")).strip().lower(),
                "symbol": symbol,
                "strategy": STRATEGY_ATTACK,
                "strategy_label": STRATEGY_METADATA[STRATEGY_ATTACK]["label"],
                "passed": bool(signal.get("passed")),
                "conditions": signal.get("conditions") or {},
                "generated_at": generated_at,
                "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
            }
        )
    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_rps_pullback_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """RPS回踩：RPS20从50以下首次突破70，回踩期间(RPS20<70)RPS50≥70且RPS120/250≥75，过去5日未出现过。"""
    import json as _json
    rps_rows = load_rps_rows()

    # Initial filter: today RPS20 > 70
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        if rps20 is not None and rps20 > 70:
            candidates.append(row)
    if not candidates:
        return []

    # Load RPS history dataset
    history_path = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.json"
    if not history_path.exists():
        return []
    all_history = _json.loads(history_path.read_text(encoding="utf-8"))

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

    # Get sorted trading days from any stock's history
    sample_dates = sorted(next(iter(stock_history.values())).keys()) if stock_history else []
    if not sample_dates:
        return []

    def _check_pullback(ordered: list, target_idx: int) -> tuple[bool, bool, int]:
        """Check pullback condition for a given day index. Returns (passed, has_pullback, pullback_days).

        The pullback is a continuous streak where RPS20 < 70.
        Within this streak (or immediately before it), RPS20 must be < 50.
        During the entire streak: RPS50 >= 70, RPS120 >= 75, RPS250 >= 75.
        """
        # Walk backwards from target_idx to find the pullback streak (RPS20 < 70)
        # and check if RPS20 ever < 50 within or immediately before the streak
        pullback_start = target_idx  # will be the index where RPS20 last went >= 70
        found_low = False
        pullback_ok = True
        pullback_days = 0

        for i in range(target_idx - 1, max(0, target_idx - 30) - 1, -1):
            h = ordered[i][1]
            r20 = _coerce_float(h.get("rps_20"))

            if r20 is not None and r20 < 50:
                found_low = True

            if r20 is not None and r20 < 70:
                # Inside pullback streak
                pullback_days += 1
                pullback_start = i
                r50 = _coerce_float(h.get("rps_50"))
                r120 = _coerce_float(h.get("rps_120"))
                r250 = _coerce_float(h.get("rps_250"))
                if (r50 is None or r50 < 70 or
                    r120 is None or r120 < 75 or
                    r250 is None or r250 < 75):
                    pullback_ok = False
                    break
            else:
                # RPS20 >= 70 — end of pullback streak
                # If we haven't found a low < 50 yet, check if the day right before
                # the streak had RPS20 < 50 (it would have been caught in the loop
                # since this is the first day outside the streak)
                break

        has_pullback = pullback_days > 0
        return pullback_ok and has_pullback and found_low, has_pullback, pullback_days

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for row in candidates:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        key = (market_val, symbol_val)
        hist = stock_history.get(key, {})
        if not hist:
            continue

        today_str = sample_dates[-1]
        ordered = sorted(
            [(d, h) for d, h in hist.items() if d <= today_str],
            key=lambda x: x[0],
        )
        if len(ordered) < 30:
            continue

        # Find today's index
        today_idx = None
        for i, (d, _h) in enumerate(ordered):
            if d == today_str:
                today_idx = i
                break
        if today_idx is None:
            continue

        # Check today's condition
        today_passed, has_pullback, pullback_days = _check_pullback(ordered, today_idx)
        if not today_passed:
            continue

        # "首次" check: was this condition met in the past 5 trading days?
        ever_met = False
        for day_offset in range(1, 6):
            past_idx = today_idx - day_offset
            if past_idx < 30:
                continue
            past_rps20 = _coerce_float(ordered[past_idx][1].get("rps_20"))
            if past_rps20 is not None and past_rps20 > 70:
                past_passed, _, _ = _check_pullback(ordered, past_idx)
                if past_passed:
                    ever_met = True
                    break

        is_first = not ever_met

        conditions: dict[str, object] = {
            "today_rps20_gt_70": True,
            "found_low_below_50": True,
            "pullback_ok": today_passed,
            "pullback_day_count": pullback_days,
            "has_pullback": has_pullback,
            "first_time": is_first,
            "ever_met_past_5_days": ever_met,
        }

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_PULLBACK,
            "strategy_label": STRATEGY_METADATA[STRATEGY_PULLBACK]["label"],
            "passed": is_first,
            "conditions": conditions,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current+dataset_stock_rps_history",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def _rps_first_candidates(rps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find stocks where 3 out of 4 RPS >= 90 and the remaining one >= 80."""
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        rps120 = _coerce_float(row.get("rps_120"))
        rps250 = _coerce_float(row.get("rps_250"))
        if None in (rps20, rps50, rps120, rps250):
            continue
        above_90 = sum(1 for v in (rps20, rps50, rps120, rps250) if v >= 90)
        below_80 = sum(1 for v in (rps20, rps50, rps120, rps250) if v < 80)
        if above_90 >= 3 and below_80 == 0:
            candidates.append(row)
    return candidates


def _compute_past_days_rps(
    reader: Reader,
    rps_rows: list[dict[str, Any]],
    ndays: int = 5,
) -> list[dict[tuple[str, str], dict[str, float | None]]]:
    """Compute cross-sectional RPS for the past N trading days for all stocks.

    Returns a list of length ndays, where index 0 = yesterday (1 day ago),
    index 1 = 2 days ago, etc.
    Each element is {(market, symbol): {'rps_20': ..., 'rps_50': ..., 'rps_120': ..., 'rps_250': ...}}
    """
    close_history: dict[str, list[float]] = {}
    for row in rps_rows:
        market_val = str(row.get("market", "")).strip()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue
        key = f"{market_val}:{symbol_val}"
        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        closes = daily.sort_index()["close"].astype(float).tolist()
        if len(closes) >= 260 + ndays:
            close_history[key] = closes

    results: list[dict[tuple[str, str], dict[str, float | None]]] = []

    for day_offset in range(1, ndays + 1):
        rows_by_symbol: list[dict[str, Any]] = []
        for key, closes in close_history.items():
            market_val, symbol_val = key.split(":", 1)
            idx = len(closes) - 1 - day_offset  # today-1=yesterday, today-2=2 days ago...
            if idx < 250:
                continue
            ret20 = _return_pct(closes, idx, 20)
            ret50 = _return_pct(closes, idx, 50)
            ret120 = _return_pct(closes, idx, 120)
            ret250 = _return_pct(closes, idx, 250)
            if all(v is None for v in [ret20, ret50, ret120, ret250]):
                continue
            rows_by_symbol.append({
                "market": market_val,
                "symbol": symbol_val,
                "return_20_pct": ret20,
                "return_50_pct": ret50,
                "return_120_pct": ret120,
                "return_250_pct": ret250,
            })

        if not rows_by_symbol:
            results.append({})
            continue

        universe_size = len(rows_by_symbol)

        def _rank_rps(rows: list[dict[str, Any]], field: str) -> dict[tuple[str, str], float | None]:
            sorted_rows = sorted(
                rows,
                key=lambda r: float(r[field]) if r[field] is not None else float("-inf"),
                reverse=True,
            )
            result: dict[tuple[str, str], float | None] = {}
            for rank, r in enumerate(sorted_rows, start=1):
                value = r[field]
                if value is None:
                    result[(r["market"], r["symbol"])] = None
                else:
                    result[(r["market"], r["symbol"])] = round(
                        (universe_size - rank + 1) / universe_size * 100.0, 2
                    )
            return result

        rps20_map = _rank_rps(rows_by_symbol, "return_20_pct")
        rps50_map = _rank_rps(rows_by_symbol, "return_50_pct")
        rps120_map = _rank_rps(rows_by_symbol, "return_120_pct")
        rps250_map = _rank_rps(rows_by_symbol, "return_250_pct")

        day_result: dict[tuple[str, str], dict[str, float | None]] = {}
        for row in rows_by_symbol:
            key = (row["market"], row["symbol"])
            day_result[key] = {
                "rps_20": rps20_map.get(key),
                "rps_50": rps50_map.get(key),
                "rps_120": rps120_map.get(key),
                "rps_250": rps250_map.get(key),
            }
        results.append(day_result)

    return results


def build_rps_first_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """RPS首次：今天任意3个RPS≥90且余下1个≥80，且过去5个交易日从未满足此条件。"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    candidates = _rps_first_candidates(rps_rows)
    if not candidates:
        return []

    # Compute cross-sectional RPS for the past 5 trading days (index 0=yesterday, 1=2days ago, ...)
    past_rps_by_day = _compute_past_days_rps(reader, rps_rows, ndays=5)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    results: list[dict[str, Any]] = []
    for row in candidates:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        key = (market_val, symbol_val)

        # Check if this stock ever met the 3-of-4 condition in the past 5 days
        ever_met = False
        past_days_detail: dict[str, object] = {}
        for day_idx, day_rps in enumerate(past_rps_by_day):
            rps = day_rps.get(key, {})
            rps20 = rps.get("rps_20")
            rps50 = rps.get("rps_50")
            rps120 = rps.get("rps_120")
            rps250 = rps.get("rps_250")
            days_ago = day_idx + 1
            
            above_90 = sum(1 for v in (rps20, rps50, rps120, rps250) if v is not None and v >= 90)
            below_80 = sum(1 for v in (rps20, rps50, rps120, rps250) if v is not None and v < 80)
            day_met = above_90 >= 3 and below_80 == 0

            past_days_detail[f"day_{days_ago}_met"] = day_met
            past_days_detail[f"day_{days_ago}_above_90_count"] = above_90
            past_days_detail[f"day_{days_ago}_rps20"] = rps20
            past_days_detail[f"day_{days_ago}_rps50"] = rps50
            past_days_detail[f"day_{days_ago}_rps120"] = rps120
            past_days_detail[f"day_{days_ago}_rps250"] = rps250
            if day_met:
                ever_met = True

        is_first = not ever_met

        conditions: dict[str, object] = {
            "today_rps20_ge_90": True,
            "today_rps50_ge_90": True,
            "today_rps120_ge_90": True,
            "today_rps250_ge_90": True,
            **past_days_detail,
        }

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_FIRST,
            "strategy_label": STRATEGY_METADATA[STRATEGY_FIRST]["label"],
            "passed": is_first,
            "conditions": conditions,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
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


def build_first_board_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """首板股池：30日内有涨停; 周/月线处于底部; 回撤5%-20%; PE-TTM 0~50"""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    # Build PE-TTM lookup from relative valuation dataset
    valuation_groups = load_industry_valuation_rows()
    pe_ttm_map: dict[tuple[str, str], float] = {}
    for group in valuation_groups:
        for member in group.get("member_valuation_rows", []) or []:
            market = str(member.get("market", "")).strip().lower()
            symbol = str(member.get("symbol", "")).strip()
            pe = _coerce_float(member.get("pe_ttm"))
            if market and symbol and pe is not None:
                pe_ttm_map[(market, symbol)] = pe

    def _limit_up_threshold(market_str: str, symbol_str: str) -> float:
        """Return limit-up gain threshold based on board (symbol prefix)."""
        if symbol_str.startswith("688"):
            return 19.5  # STAR / 科创板 (sh market)
        if symbol_str.startswith(("300", "301")):
            return 19.5  # ChiNext / 创业板 (sz market)
        if market_str == "bj" or symbol_str.startswith("92"):
            return 29.5  # BSE / 北交所
        return 9.5  # 主板 (sh.60xxxx, sz.00xxxx)

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
        highs = daily["high"].astype(float).tolist()
        if len(closes) < 250:
            continue

        # Condition A: 30天内有过涨停
        threshold = _limit_up_threshold(market_val, symbol_val)
        lu_idx = -1
        scan_start = max(0, len(closes) - 30)
        for i in range(len(closes) - 1, scan_start - 1, -1):
            if i == 0:
                continue
            c = closes[i]
            h = highs[i]
            prev_c = closes[i - 1]
            if prev_c <= 0:
                continue
            gain_pct = (c - prev_c) / prev_c * 100.0
            if gain_pct >= threshold and c >= h * 0.99:
                lu_idx = i
                break

        if lu_idx < 0:
            continue  # No limit-up in last 30 days

        # Condition B: 距离上次涨停股价回撤5%-20%
        limit_up_close = closes[lu_idx]
        current_close = closes[-1]
        if limit_up_close <= 0:
            continue
        pullback_pct = (limit_up_close - current_close) / limit_up_close * 100.0
        if pullback_pct < 5.0 or pullback_pct > 20.0:
            continue

        # Condition C: 周线和月线在底部位置
        max_100 = max(closes[-100:])
        min_100 = min(closes[-100:])
        if max_100 == min_100:
            continue
        week_position = (current_close - min_100) / (max_100 - min_100)
        week_bottom = week_position < 0.30

        max_250 = max(closes[-250:])
        min_250 = min(closes[-250:])
        if max_250 == min_250:
            continue
        month_position = (current_close - min_250) / (max_250 - min_250)
        month_bottom = month_position < 0.30

        if not week_bottom or not month_bottom:
            continue

        # Condition D: 市盈率TTM 0~50
        pe_ttm = pe_ttm_map.get((market_val, symbol_val))
        if pe_ttm is None or pe_ttm <= 0 or pe_ttm > 50:
            continue

        # All conditions passed
        passed = True

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_FIRST_BOARD,
            "strategy_label": STRATEGY_METADATA[STRATEGY_FIRST_BOARD]["label"],
            "passed": passed,
            "conditions": {
                "has_limit_up_30d": True,
                "pullback_pct": round(pullback_pct, 2),
                "week_bottom": week_bottom,
                "month_bottom": month_bottom,
                "pe_ttm": round(pe_ttm, 2),
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+relative_valuation",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
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


def build_blowup_stall_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """爆量滞涨：连续两天真阳线上涨; 每天量>3倍50日均量; 涨前5天量均<2倍50日均量"""
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
            "strategy": STRATEGY_BLOWUP_STALL,
            "strategy_label": STRATEGY_METADATA[STRATEGY_BLOWUP_STALL]["label"],
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


def merge_strategy_rows_for_output(output: Path, strategy: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace one strategy's rows while preserving other strategies in the shared output file."""
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
    parser.add_argument("--strategy", default=STRATEGY_STANDARD, choices=sorted(STRATEGY_METADATA))
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
        if args.strategy == STRATEGY_STANDARD:
            rows = build_rps_standard_launch_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_ATTACK:
            rows = build_rps_attack_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_PULLBACK:
            rows = build_rps_pullback_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_FIRST:
            rows = build_rps_first_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_MA_CROSS:
            rows = build_ma_cross_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_FIRST_BOARD:
            rows = build_first_board_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_WASHOUT:
            rows = build_washout_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_RPS_CLIMB:
            rows = build_rps_climb_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_BLOWUP_STALL:
            rows = build_blowup_stall_rows(tdxdir=args.tdxdir)
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
