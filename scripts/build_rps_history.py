#!/usr/bin/env python3
"""Build cross-sectional RPS history for all stocks for the past N trading days.

Stores as a single JSON array: [{trading_day, market, symbol, rps_20, rps_50, rps_120, rps_250}, ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TDX_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.json"
DEFAULT_NDAYS = 120


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cross-sectional RPS history dataset")
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ndays", type=int, default=DEFAULT_NDAYS,
                        help="Number of past trading days to include (default: 120)")
    args = parser.parse_args()

    reader = Reader.factory(market="std", tdxdir=args.tdxdir)
    ndays = max(1, args.ndays)

    # Step 1: Load close history for ALL stocks
    print(f"[1/3] Loading daily data for all stocks...", flush=True)
    with open(PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_current.json") as f:
        rps_rows = json.load(f)

    close_history: dict[str, list[float]] = {}
    trading_dates: dict[str, list[str]] = {}
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
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        dates = daily.index.strftime("%Y-%m-%d").tolist()
        if len(closes) >= 260:
            close_history[key] = closes
            trading_dates[key] = dates

    all_stocks = sorted(close_history.keys())
    print(f"  Loaded {len(all_stocks)} stocks with sufficient history", flush=True)

    # Step 2: Build a unified date index from the stock with most history
    max_len = max(len(dates) for dates in trading_dates.values())
    ref_dates = next(dates for dates in trading_dates.values() if len(dates) == max_len)
    # Use the last N trading days
    target_dates = ref_dates[-ndays:]
    print(f"[2/3] Computing cross-sectional RPS for {len(target_dates)} trading days ({target_dates[0]} ~ {target_dates[-1]})...", flush=True)

    all_rows: list[dict[str, Any]] = []

    for day_num, trading_day in enumerate(target_dates):
        # For each stock, find the index of this trading_day and compute returns
        rows_by_symbol: list[dict[str, Any]] = []
        for key in all_stocks:
            dates = trading_dates.get(key, [])
            closes = close_history.get(key, [])
            try:
                idx = dates.index(trading_day)
            except ValueError:
                continue
            if idx < 250:
                continue

            market_val, symbol_val = key.split(":", 1)

            def _ret(window: int) -> float | None:
                start = idx - window
                if start < 0 or closes[start] == 0:
                    return None
                return round((closes[idx] - closes[start]) / closes[start] * 100.0, 4)

            ret20 = _ret(20)
            ret50 = _ret(50)
            ret120 = _ret(120)
            ret250 = _ret(250)
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

        for row in rows_by_symbol:
            key = (row["market"], row["symbol"])
            all_rows.append({
                "trading_day": trading_day,
                "market": row["market"],
                "symbol": row["symbol"],
                "rps_20": rps20_map.get(key),
                "rps_50": rps50_map.get(key),
                "rps_120": rps120_map.get(key),
                "rps_250": rps250_map.get(key),
            })

        if (day_num + 1) % 10 == 0 or day_num == 0:
            print(f"  Day {day_num + 1}/{len(target_dates)} ({trading_day}): {len(all_rows)} total rows", flush=True)

    print(f"[3/3] Writing {len(all_rows)} rows to {args.output}...", flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(all_rows, ensure_ascii=False), encoding="utf-8")
    print(f"  Done: {output.stat().st_size / 1024 / 1024:.1f} MB", flush=True)
    print(json.dumps({"ok": True, "rows": len(all_rows), "trading_days": len(target_dates), "output": str(output)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
