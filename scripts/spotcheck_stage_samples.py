#!/usr/bin/env python3
"""Human-auditable spot check of the stage history.

For every stage, draws a seeded sample of (stock, trading_day) rows, rebuilds the
classification from QFQ bars truncated at that date, and prints the evidence a
human needs to judge whether the label is plausible:

    close vs MA5/10/20/60, MA layout, slope20/slope60, bias20,
    position inside the 60-bar range, volume ratio, plus 20-bar return.

Usage:
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/spotcheck_stage_samples.py
    ... --per-stage 8 --seed 7
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify import MIN_DAYS, classify_stage  # noqa: E402
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
STAGE_ORDER = ["D1", "D2", "D3", "B1", "B2", "B3", "U1", "U2", "U3", "U4", "T1"]


def layout(evidence: dict) -> str:
    ma5, ma10, ma20, ma60 = (evidence[key] for key in ("ma5", "ma10", "ma20", "ma60"))
    if ma5 > ma10 > ma20 > ma60:
        return "多头排列"
    if ma5 < ma10 < ma20 < ma60:
        return "空头排列"
    return "纠缠"


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage history spot check")
    parser.add_argument("--history", type=Path, default=FINAL / "stage_history.parquet")
    parser.add_argument("--per-stage", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    history = pd.read_parquet(args.history)
    # filter + group once; keep frames (not 12.5M dicts) and sample by position
    pool_frame = history[history["trading_day"] < "2026-10-01"]
    pools = {stage: part for stage, part in pool_frame.groupby("stage", observed=True)}
    rng = random.Random(args.seed)
    mismatches = 0
    checked = 0

    for stage in STAGE_ORDER:
        pool = pools.get(stage)
        if pool is None or pool.empty:
            print(f"\n{stage}: no samples")
            continue
        count = min(args.per_stage, len(pool))
        picks = [pool.iloc[position].to_dict() for position in rng.sample(range(len(pool)), count)]
        print(f"\n=== {stage} ===")
        for record in picks:
            symbol, day = record["symbol"], record["trading_day"]
            try:
                frame = load_tdx_qfq_daily(symbol)
            except Exception as exc:  # noqa: BLE001
                print(f"  {symbol} {day}  LOAD FAIL {exc}")
                continue
            frame = frame[frame.index <= pd.Timestamp(day)]
            if len(frame) < MIN_DAYS:
                print(f"  {symbol} {day}  too few bars ({len(frame)})")
                continue

            recomputed = classify_stage(frame)
            checked += 1
            ok = recomputed["stage"] == stage
            if not ok:
                mismatches += 1
            evidence = recomputed["evidence"]
            closes = frame["close"].astype(float)
            ret20 = (closes.iloc[-1] / closes.iloc[-21] - 1) * 100 if len(closes) > 21 else float("nan")
            print(
                f"  {'OK ' if ok else 'XX '}{symbol} {day} "
                f"close={closes.iloc[-1]:.2f} MA5/10/20/60="
                f"{evidence['ma5']}/{evidence['ma10']}/{evidence['ma20']}/{evidence['ma60']} "
                f"{layout(evidence)} slope20={evidence['slope20'] * 100:+.2f}% "
                f"slope60={evidence['slope60'] * 100:+.2f}% bias20={evidence['bias20'] * 100:+.1f}% "
                f"pos60={evidence['pos_low_60'] * 100:.0f}~{evidence['pos_high_60'] * 100:.0f}% "
                f"vol={evidence['vol_ratio']:.2f} ret20={ret20:+.1f}%"
                + ("" if ok else f"  >> recomputed {recomputed['region']}/{recomputed['stage']}")
            )

    print(f"\nchecked {checked} samples | mismatches {mismatches}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
