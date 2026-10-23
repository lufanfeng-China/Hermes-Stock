#!/usr/bin/env python3
"""Build the current QFQ all-A daily-equal-weight relative-strength snapshot."""
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
from app.market_relative_strength import build_market_relative_strength

SOURCE = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.parquet"
OUT = ROOT / "data" / "derived" / "datasets" / "final" / "market_relative_strength_current.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--min-universe", type=int, default=100)
    args = parser.parse_args()
    frame = pd.read_parquet(args.source, columns=["date", "market", "symbol", "close"])
    payload = build_market_relative_strength(frame, min_eligible_universe=args.min_universe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        temporary = Path(handle.name)
    os.replace(temporary, args.output)
    print(json.dumps({"output": str(args.output), "stocks": len(payload["stocks"]), "as_of_date": payload["as_of_date"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
