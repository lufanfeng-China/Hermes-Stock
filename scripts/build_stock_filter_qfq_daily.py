#!/usr/bin/env python3
"""Build front-adjusted daily bars plus disclosed free-float shares for stock filtering."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search.index import load_security_rows
from app.tdx.qfq_kline import load_tdx_qfq_daily

OUT = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.parquet"
META = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.meta.json"
FLOAT_FILE = ROOT / "data" / "derived" / "financial_ts" / "by_quarter" / "2026Q2.parquet"


def _market(symbol: str) -> str:
    return "sh" if symbol.startswith("6") else "sz" if symbol.startswith(("00", "30")) else "bj" if symbol.startswith("92") else ""


def main() -> None:
    floats = pd.read_parquet(FLOAT_FILE)
    floats.index = floats.index.map(lambda x: str(x).zfill(6))
    rows, failures = [], {}
    codes = sorted({str(row.get("symbol") or "").zfill(6) for row in load_security_rows()})
    for n, symbol in enumerate(codes, 1):
        market = _market(symbol)
        if not market:
            continue
        try:
            bars = load_tdx_qfq_daily(symbol).reset_index()[["date", "open", "close", "volume"]]
            bars["market"], bars["symbol"] = market, symbol
            raw_float = floats.loc[symbol].get("自由流通股(股)") if symbol in floats.index else None
            bars["free_float_shares"] = pd.to_numeric(raw_float, errors="coerce")
            rows.append(bars)
        except Exception as exc:
            failures[f"{market}:{symbol}"] = str(exc)
        if n % 500 == 0:
            print(f"[{n}/{len(codes)}]", flush=True)
    if not rows:
        raise RuntimeError("no QFQ rows built")
    frame = pd.concat(rows, ignore_index=True).sort_values(["market", "symbol", "date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT, index=False)
    META.write_text(json.dumps({"schema_version": "stock-filter-qfq-daily-v2", "price_basis": "tdx_export_qfq", "float_share_anchor": "2026Q2", "rows": len(frame), "stocks": frame[["market", "symbol"]].drop_duplicates().shape[0], "failures": failures}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "rows": len(frame), "stocks": frame[["market", "symbol"]].drop_duplicates().shape[0], "failures": len(failures)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
