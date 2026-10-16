#!/usr/bin/env python3
"""Build the strict annual/quarterly financial snapshot for /stock-filter.

Uses a single annual anchor (2025A) and a single quarterly anchor (2026Q2), so
all filterable stocks are comparable.  It never uses percentile financial snapshots.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.financial.reports import _materialize_financial_report, _load_raw_daily_bars, build_report_release_price_performance
from app.search import index as search_index
from app.stock_filter_snapshot import build_strict_financial_record

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
OUT = ROOT / "data" / "derived" / "datasets" / "final" / "strict_financial_health_snapshot_2025A__2026Q2.json"
PERIODS = ("2021A", "2022A", "2023A", "2024A", "2025A", "2025Q2", "2026Q2")


class _Materializer:
    _derive_sub_fields = staticmethod(search_index._derive_sub_fields)
    _pick = staticmethod(search_index._pick)


def _market_map() -> dict[str, str]:
    # The warehouse index has only codes.  Derive market from the project's A-share
    # universe convention, rather than taking the first TNF hit (e.g. SH000001 index).
    result: dict[str, str] = {}
    for row in search_index.load_security_rows():
        symbol = str(row.get("symbol") or "").zfill(6)
        market = "sh" if symbol.startswith("6") else "sz" if symbol.startswith(("00", "30")) else "bj" if symbol.startswith("92") else ""
        if market:
            result[symbol] = market
    return result


def _industry_map() -> dict[tuple[str, str], tuple[str | None, str | None]]:
    result = {}
    for row in search_index.load_industry_rows():
        market, symbol = str(row.get("market") or "").lower(), str(row.get("symbol") or "").zfill(6)
        if market == "2":
            market = "bj"
        result[(market, symbol)] = (
            str(row.get("industry_level_1_name") or "").strip() or None,
            str(row.get("industry_level_2_name") or "").strip() or None,
        )
    return result


def _read_periods() -> dict[str, pd.DataFrame]:
    frames = {}
    for period in PERIODS:
        path = WAREHOUSE / f"{period}.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path)
        frame.index = frame.index.map(lambda value: str(value).zfill(6))
        frames[period] = frame
    return frames


def _report(period: str, row: pd.Series) -> dict:
    year = period[:4]
    suffix = period[4:]
    report_date = f"{year}{'1231' if suffix == 'A' else {'Q1': '0331', 'Q2': '0630', 'Q3': '0930'}[suffix]}"
    announce_date = row.get("announce_date") or row.get("财报公告日期") or ""
    return _materialize_financial_report(_Materializer, {
        "report_date": report_date, "announce_date": announce_date, "year": year, "period": period, "row": row,
    })


def build_snapshot() -> dict:
    frames, markets, industries = _read_periods(), _market_map(), _industry_map()
    codes = set.intersection(*(set(frame.index) for frame in frames.values()))
    stocks = {}
    for n, symbol in enumerate(sorted(codes), 1):
        market = markets.get(symbol)
        if not market:
            continue
        reports = [_report(period, frames[period].loc[symbol]) for period in PERIODS]
        industry_l1, industry_l2 = industries.get((market, symbol), (None, None))
        record = build_strict_financial_record(
            reports, industry_level_1=industry_l1, annual_anchor="2025A", quarterly_anchor="2026Q2",
        )
        raw_bars = _load_raw_daily_bars(search_index, symbol)
        latest_close = raw_bars[-1].get("close") if raw_bars else None
        record["report_release_price_performance"] = build_report_release_price_performance(
            announce_date=reports[-1].get("announce_date"), daily_bars=raw_bars, current_price=latest_close,
            current_price_as_of=raw_bars[-1].get("trading_day") if raw_bars else None,
        )
        stocks[f"{market}:{symbol}"] = record
        if n % 500 == 0:
            print(f"[{n}/{len(codes)}]", flush=True)
    return {"schema_version": "stock-filter-strict-financial-v1", "annual_anchor": "2025A", "quarterly_anchor": "2026Q2", "periods_loaded": list(PERIODS), "stocks": stocks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    payload = build_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        temp = Path(handle.name)
    os.replace(temp, args.output)
    print(json.dumps({"output": str(args.output), "stocks": len(payload["stocks"]), "annual_anchor": "2025A", "quarterly_anchor": "2026Q2"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
