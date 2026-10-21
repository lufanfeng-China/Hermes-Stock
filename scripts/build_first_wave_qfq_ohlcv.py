#!/usr/bin/env python3
"""Build full-QFQ OHLCV asset used only by the first-wave scanner."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from app.search.index import load_security_rows
from app.tdx.qfq_kline import load_tdx_qfq_daily

OUT = ROOT / "data" / "derived" / "datasets" / "final" / "first_wave_qfq_ohlcv.parquet"
META = OUT.with_suffix(".meta.json")

def eligible(row: dict) -> tuple[str, str, str] | None:
    symbol = str(row.get("symbol") or "").zfill(6); name = str(row.get("stock_name") or "").strip()
    market = "sh" if symbol.startswith("6") else "sz" if symbol.startswith(("00", "30")) else ""
    if not market or not name or "ST" in name.upper() or name.startswith("*ST"): return None
    return market, symbol, name

def main() -> None:
    rows, failures = [], {}
    securities = [x for raw in load_security_rows() if (x := eligible(raw))]
    for i, (market, symbol, name) in enumerate(securities, 1):
        try:
            bars = load_tdx_qfq_daily(symbol).reset_index()
            bars["market"], bars["symbol"], bars["stock_name"] = market, symbol, name
            # TDX export amount is the actual daily traded monetary amount; prices remain QFQ only.
            bars["amount_basis"] = "tdx_export_daily_amount"
            rows.append(bars[["date","market","symbol","stock_name","open","high","low","close","volume","amount","amount_basis"]])
        except Exception as exc: failures[f"{market}:{symbol}"] = str(exc)
        if i % 250 == 0: print(f"[{i}/{len(securities)}]", flush=True)
    if not rows: raise RuntimeError("no full QFQ OHLCV rows built")
    frame = pd.concat(rows, ignore_index=True).sort_values(["market","symbol","date"])
    OUT.parent.mkdir(parents=True, exist_ok=True); frame.to_parquet(OUT, index=False)
    META.write_text(json.dumps({"schema_version":"first-wave-qfq-ohlcv-v1","price_basis":"tdx_export_qfq","amount_basis":"tdx_export_daily_amount","rows":len(frame),"stocks":len(securities)-len(failures),"failures":failures,"data_date":str(frame.date.max().date())}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output":str(OUT),"rows":len(frame),"stocks":frame[["market","symbol"]].drop_duplicates().shape[0],"failures":len(failures)},ensure_ascii=False))
if __name__ == "__main__": main()
