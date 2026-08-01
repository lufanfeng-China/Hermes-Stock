#!/usr/bin/env python3
"""Pre-compute 5-year price percentile for all A-share stocks.
Reads TDX local .day files, computes where current close sits in 5-year range.
Output: data/derived/datasets/final/dataset_price_percentile_5y.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.tdx.qfq_kline import load_tdx_qfq_daily
DATA_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
TDX_DIR = r"/home/lufanfeng/tdx_data"  # WSL path

OUTPUT_PATH = DATA_DIR / "dataset_price_percentile_5y.json"
YEARS = 5
MIN_DAYS = 60  # minimum trading days required


def compute_percentile(close_prices: list[float]) -> dict:
    """Compute where latest price sits in the distribution."""
    if len(close_prices) < MIN_DAYS:
        return None
    latest = close_prices[-1]
    below = sum(1 for p in close_prices if p <= latest)
    pct = below / len(close_prices) * 100

    high = max(close_prices)
    low = min(close_prices)
    mean = sum(close_prices) / len(close_prices)

    if pct < 20:
        band = "极低"
    elif pct < 40:
        band = "低"
    elif pct < 60:
        band = "中"
    elif pct < 80:
        band = "高"
    else:
        band = "极高"

    return {
        "price_percentile_5y": round(pct, 1),
        "price_band_5y": band,
        "high_5y": round(high, 2),
        "low_5y": round(low, 2),
        "mean_5y": round(mean, 2),
        "latest_close": round(latest, 2),
        "trading_days": len(close_prices),
    }


def main():
    t0 = time.time()
    # Raw .day files only provide the security universe; percentile is QFQ-based.

    # Get all .day file symbols by scanning TDX directory
    symbols = set()
    for market_dir_name in ("sh", "sz", "bj"):
        mdir = Path(TDX_DIR) / "vipdoc" / market_dir_name / "lday"
        if mdir.exists():
            for f in mdir.glob("*.day"):
                # Files are like sh600000.day or 600000.day
                code = f.stem
                if code.startswith(market_dir_name):
                    code = code[len(market_dir_name):]
                if code.isdigit() and len(code) == 6:
                    symbols.add(code)

    print(f"Found {len(symbols)} symbols, computing 5-year percentile...")

    results: dict[str, dict] = {}
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=YEARS)
    done = 0
    errors = 0

    for symbol in sorted(symbols):
        try:
            daily = load_tdx_qfq_daily(symbol)
            if daily is None or daily.empty:
                errors += 1
                continue

            daily.index = pd.to_datetime(daily.index)
            daily = daily.sort_index()
            recent = daily[daily.index >= cutoff]

            if len(recent) < MIN_DAYS:
                errors += 1
                continue

            closes = recent["close"].dropna().tolist()
            result = compute_percentile(closes)
            if result:
                result["price_basis"] = "tdx_export_qfq"
                results[symbol] = result

            done += 1
            if done % 500 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed
                remaining = (len(symbols) - done - errors) / rate
                print(f"  {done}/{len(symbols)} ({done*100//len(symbols)}%) "
                      f"— {elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining, {errors} errors")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error {symbol}: {e}")

    elapsed = time.time() - t0
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(results)} stocks in {elapsed:.0f}s ({elapsed/len(results):.2f}s per stock)")
    print(f"Errors: {errors}")
    print(f"Output: {OUTPUT_PATH}")

    # Quick stats
    pcts = [r["price_percentile_5y"] for r in results.values()]
    if pcts:
        print(f"Percentile range: {min(pcts):.1f} - {max(pcts):.1f}, mean: {sum(pcts)/len(pcts):.1f}")


if __name__ == "__main__":
    main()
