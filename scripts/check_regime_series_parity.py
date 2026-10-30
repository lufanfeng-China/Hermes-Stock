"""Parity: vectorised A/B/C/D series must match the scalar classifier bar by bar."""
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stage_regime import classify_regime
from app.stage_regime_series import classify_regime_series
from app.stage_classify import prepare_bars
from app.tdx.qfq_kline import load_tdx_qfq_daily

random.seed(5)
sample = [s for s in (
    "600309 600036 600016 600519 000001 000858 002415 300750 601318 600030 "
    "002594 601012 300059 600887 000651 002304 600276 601888 603259 688111 "
    "600000 600009 600011 600012 600017 600018 600019 600020 600021 600022"
).split()]

total = mismatches = 0
stage_by_code: dict[str, int] = {}
details = []
for symbol in sample:
    bars = prepare_bars(load_tdx_qfq_daily(symbol))
    if len(bars) < 120:
        continue
    series = classify_regime_series(bars)
    valid = series["valid"].to_numpy()
    for offset in (0, 7, 31, 90):
        truncated = bars.iloc[: len(bars) - offset]
        if len(truncated) < 60:
            continue
        scalar = classify_regime(truncated)
        row = series.iloc[len(truncated) - 1]
        total += 1
        stage_by_code[scalar["stage"]] = stage_by_code.get(scalar["stage"], 0) + 1
        same = str(row["stage"]) == scalar["stage"] and int(row["score"]) == scalar["score"]
        if not same:
            mismatches += 1
            details.append(f"{symbol} -{offset}: series={row['stage']}/{row['score']} scalar={scalar['stage']}/{scalar['score']}")
    counts = series["stage"].dropna().value_counts().to_dict()
    print(f"{symbol}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

print(f"\nchecked {total} (symbol, offset) points | mismatches {mismatches}")
print("stage mix:", stage_by_code)
for line in details[:10]:
    print("  MISMATCH", line)
sys.exit(0 if mismatches == 0 else 1)
