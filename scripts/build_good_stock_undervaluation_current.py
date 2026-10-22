#!/usr/bin/env python3
"""Build the current all-market good-stock + undervaluation diagnostic snapshot."""
from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.undervaluation.service import _strict_snapshot, build_current_diagnosis

OUT = ROOT / "data" / "derived" / "datasets" / "final" / "good_stock_undervaluation_current.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Test-only cap; 0 means all records")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    lock = args.output.with_suffix(".building")
    if lock.exists():
        raise SystemExit(f"existing build lock: {lock}")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"started_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    atexit.register(lambda: lock.unlink(missing_ok=True))
    keys = sorted((_strict_snapshot().get("stocks") or {}).keys())
    if args.limit > 0:
        keys = keys[:args.limit]
    rows, failures = [], []
    total = len(keys)
    for index, key in enumerate(keys, 1):
        market, symbol = key.split(":", 1)
        try:
            result = build_current_diagnosis(market, symbol)
            if result.get("ok"):
                rows.append(result)
            else:
                failures.append({"key": key, "reasons": result.get("reasons") or [result.get("status")]})
        except Exception as exc:
            failures.append({"key": key, "error": str(exc)})
        if index % 25 == 0 or index == total:
            print(json.dumps({"progress": index, "total": total, "diagnosed": len(rows), "failed": len(failures)}, ensure_ascii=False), flush=True)
    payload = {
        "schema_version": "good-stock-undervaluation-current-snapshot-v1",
        "built_at": datetime.now(timezone.utc).isoformat(), "scope": "current_snapshot_only",
        "stocks": rows, "failures": failures,
        "summary": {
            "universe_records": total, "diagnosed_records": len(rows), "failed_records": len(failures),
            "quadrants": {name: sum(1 for row in rows if (row.get("quadrant") or {}).get("quadrant") == name) for name in (
                "QUALITY_ELIGIBLE_HAS_MARGIN", "QUALITY_ELIGIBLE_NO_MARGIN", "NOT_QUALITY_ELIGIBLE_HAS_MARGIN", "NOT_QUALITY_ELIGIBLE_NO_MARGIN", "VALUATION_UNAVAILABLE")},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        temporary = Path(handle.name)
    os.replace(temporary, args.output)
    print(json.dumps({"output": str(args.output), **payload["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
