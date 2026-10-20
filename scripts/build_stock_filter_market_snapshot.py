#!/usr/bin/env python3
"""Build the compact per-symbol QFQ metrics snapshot for /stock-filter."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.stock_filter_market_snapshot import build_market_metrics

SOURCE = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.parquet"
OUT = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_market_metrics_current.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    frame = pd.read_parquet(args.source, columns=["date", "market", "symbol", "open", "close", "volume", "free_float_shares"])
    payload = build_market_metrics(frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        temp = Path(handle.name)
    os.replace(temp, args.output)
    print(json.dumps({"output": str(args.output), "stocks": payload["stocks"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
