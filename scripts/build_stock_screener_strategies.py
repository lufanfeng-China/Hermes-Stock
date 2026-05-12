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
    load_rps_rows,
)

DEFAULT_TDX_DIR = "/mnt/c/new_tdx64"
DEFAULT_OUTPUT = DEFAULT_DATASET_DIR / "dataset_stock_screener_strategies_current.json"
STRATEGY_STANDARD = "rps_standard_launch"
STRATEGY_ATTACK = "rps_attack"
STRATEGY_PULLBACK = "rps_pullback"
STRATEGY_FIRST = "rps_first"
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
        signal = evaluate_rps_pullback_signal(
            latest_rps,
            {"rps_20": ref3_rps20.get(symbol)},
            {"rps_50": ref5_rps50.get(symbol)},
            signal_context["candidate_bars"].get(symbol, []),
        )
        results.append(
            {
                "trading_day": row.get("trading_day"),
                "market": str(row.get("market", "")).strip().lower(),
                "symbol": symbol,
                "strategy": STRATEGY_PULLBACK,
                "strategy_label": STRATEGY_METADATA[STRATEGY_PULLBACK]["label"],
                "passed": bool(signal.get("passed")),
                "conditions": signal.get("conditions") or {},
                "generated_at": generated_at,
                "data_source": "local_tongdaxin_daily+dataset_stock_rps_current",
            }
        )
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
    merged.extend(rows)
    merged.sort(key=lambda item: (str(item.get("strategy", "")), not bool(item.get("passed")), str(item.get("market", "")), str(item.get("symbol", ""))))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stock screener strategy datasets")
    parser.add_argument("--strategy", default=STRATEGY_STANDARD, choices=sorted(STRATEGY_METADATA))
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    if args.strategy == STRATEGY_STANDARD:
        rows = build_rps_standard_launch_rows(tdxdir=args.tdxdir)
    elif args.strategy == STRATEGY_ATTACK:
        rows = build_rps_attack_rows(tdxdir=args.tdxdir)
    elif args.strategy == STRATEGY_PULLBACK:
        rows = build_rps_pullback_rows(tdxdir=args.tdxdir)
    else:
        rows = build_rps_first_rows(tdxdir=args.tdxdir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output_rows = merge_strategy_rows_for_output(output, args.strategy, rows)
    output.write_text(json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    passed_count = sum(1 for row in rows if row.get("passed"))
    print(json.dumps({"ok": True, "strategy": args.strategy, "rows": len(rows), "passed": passed_count, "output": str(output), "output_rows": len(output_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
