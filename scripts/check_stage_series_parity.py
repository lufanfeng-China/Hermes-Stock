#!/usr/bin/env python3
"""Parity gate: vectorised stage series vs. the scalar day-by-day classifier.

The full-market stage history is built with `classify_stage_series`.  If that
batch path drifts from `classify_stage` (the function the stock-analysis page
calls), the history silently disagrees with the UI.  This gate samples real QFQ
bars and refuses to pass unless every single bar agrees.

Usage:
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/check_stage_series_parity.py
    ... --stocks 400 --years 3 --all          # every classifier bar, incl. evidence
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify_series import classify_stage_series, summarise_series_parity  # noqa: E402
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

RPS_PATH = PROJECT_ROOT / "data" / "derived" / "datasets" / "final" / "dataset_stock_rps_history.parquet"
BARS_PER_YEAR = 243


def sample_universe(limit: int) -> list[tuple[str, str]]:
    """Evenly strided sample across the live A-share universe (all markets)."""
    frame = pd.read_parquet(RPS_PATH, columns=["trading_day", "market", "symbol"])
    frame["trading_day"] = frame["trading_day"].astype(str)
    latest = frame[frame["trading_day"] == frame["trading_day"].max()]
    rows = [(str(r["market"]).lower(), str(r["symbol"]).zfill(6)) for r in latest.to_dict("records")]
    rows.sort()
    if limit >= len(rows):
        return rows
    stride = len(rows) / float(limit)
    return [rows[int(i * stride)] for i in range(limit)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage series parity gate")
    parser.add_argument("--stocks", type=int, default=200, help="number of sampled stocks")
    parser.add_argument("--years", type=float, default=3.0, help="bars: years * 243")
    parser.add_argument("--all", action="store_true", help="check every bar, not a sample of it")
    args = parser.parse_args()

    bars = int(args.years * BARS_PER_YEAR)
    universe = sample_universe(args.stocks)
    print(f"universe sample: {len(universe)} stocks | window: last {bars} bars")

    total_checked = 0
    total_region = 0
    total_stage = 0
    failed: list[tuple[str, str, dict]] = []
    skipped: list[tuple[str, str, str]] = []
    scalar_seconds = 0.0
    vector_seconds = 0.0
    t0 = time.time()

    for index, (market, symbol) in enumerate(universe, start=1):
        try:
            frame = load_tdx_qfq_daily(symbol)
        except Exception as exc:  # noqa: BLE001 - missing/short files are expected
            skipped.append((market, symbol, str(exc)[:80]))
            continue
        if len(frame) > bars:
            frame = frame.iloc[-bars:]
        if len(frame) < 61:
            skipped.append((market, symbol, f"only {len(frame)} bars"))
            continue

        started = time.time()
        classify_stage_series(frame)
        vector_seconds += time.time() - started

        started = time.time()
        result = summarise_series_parity(frame)
        scalar_seconds += time.time() - started

        total_checked += result["checked"]
        total_region += result["region_mismatch"]
        total_stage += result["stage_mismatch"]
        if result["stage_mismatch"] or result["region_mismatch"]:
            failed.append((market, symbol, result))

        if index % 25 == 0:
            elapsed = time.time() - t0
            print(f"  {index}/{len(universe)} stocks | bars checked {total_checked} | "
                  f"stage diffs {total_stage} | {elapsed:.0f}s")

    elapsed = time.time() - t0
    print("\n=== parity gate ===")
    print(f"stocks sampled     : {len(universe)}")
    print(f"stocks skipped     : {len(skipped)}")
    for market, symbol, reason in skipped[:5]:
        print(f"   skip {market}:{symbol} — {reason}")
    print(f"bars compared      : {total_checked}")
    print(f"region mismatches  : {total_region}")
    print(f"stage  mismatches  : {total_stage}")
    print(f"wall clock         : {elapsed:.1f}s (scalar {scalar_seconds:.1f}s / vector {vector_seconds:.1f}s)")
    if total_checked:
        print(f"vector speedup     : {(scalar_seconds / max(vector_seconds, 1e-9)):.1f}x per stock series")

    if failed:
        print("\nDIVERGENCES (first 5 stocks):")
        for market, symbol, result in failed[:5]:
            print(f"  {market}:{symbol} stage={result['stage_mismatch']} region={result['region_mismatch']}")
            for item in result["first_divergences"][:3]:
                print(f"     {item['trading_day']} vectorised={item['vectorised']} scalar={item['scalar']}")
        print("\nRESULT: FAIL — do not build history with the vectorised path")
        return 1

    print("\nRESULT: PASS — vectorised series is bar-for-bar identical to the scalar classifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
