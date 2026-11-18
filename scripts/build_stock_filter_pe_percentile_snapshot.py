#!/usr/bin/env python3
"""Publish whole-market 5y daily PE-TTM percentiles from local raw TDX closes.

Financial warehouse rows are current revisions with announcement dates, NOT a
strict as-published historical revision ledger. Historical shares are reported
shares proxies; no QFQ closes or current quotes enter PE calculations.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.relative_valuation.pe_percentile_snapshot import compute_for_stock, load_disclosures_bulk

FINAL = ROOT / "data/derived/datasets/final"
MARKET_METRICS = FINAL / "stock_filter_market_metrics_current.json"
DEFAULT_OUTPUT = FINAL / "stock_filter_pe_percentile_current.json"
WAREHOUSE = ROOT / "data/derived/financial_ts/by_quarter"
TDX_DIR = Path("/mnt/c/new_tdx64")
_RECORD = struct.Struct("<IIIIIfII")


def read_raw_bars(reader, market: str, symbol: str, trading_day: str) -> list[tuple[date, float]]:
    """Read only the trailing 5y of raw .day records; Reader locates the TDX file.

    Read a bounded 1600-bar tail (around 6.5 trading years), then expand only
    when its earliest date is newer than the cutoff and earlier records exist.
    """
    if market not in {"sh", "sz", "bj"} or not re.fullmatch(r"\d{6}", symbol):
        raise ValueError(f"invalid market:symbol {market}:{symbol}")
    path = reader.find_path(symbol=symbol, subdir="lday", suffix="day")
    if path is None:
        return []
    end = date.fromisoformat(trading_day)
    try:
        cutoff = end.replace(year=end.year - 5)
    except ValueError:
        cutoff = end.replace(year=end.year - 5, day=28)
    size = Path(path).stat().st_size
    if size % _RECORD.size:
        raise ValueError(f"corrupt raw daily file: {path}")
    count = size // _RECORD.size
    take = min(count, 1600)
    while take:
        with open(path, "rb") as stream:
            stream.seek((count - take) * _RECORD.size)
            raw = stream.read(take * _RECORD.size)
        parsed = []
        for record in _RECORD.iter_unpack(raw):
            try:
                day = date.fromisoformat(str(record[0])[:4] + "-" + str(record[0])[4:6] + "-" + str(record[0])[6:8])
            except ValueError as exc:
                raise ValueError(f"invalid raw bar date: {path}") from exc
            parsed.append((day, record[4] / 100.0))
        if parsed[0][0] < cutoff or take == count:
            # Retain one older bar so the calculation distinguishes a true
            # five-year window from history that starts at/after the cutoff.
            older = [bar for bar in parsed if bar[0] < cutoff]
            return older[-1:] + [bar for bar in parsed if bar[0] >= cutoff]
        take = min(count, take * 2)
    return []


def build_snapshot(
    trading_day: str | None = None, *, output: Path | None = None,
    metrics_path: Path = MARKET_METRICS, warehouse_dir: Path = WAREHOUSE,
    tdx_dir: Path = TDX_DIR,
    universe_keys: list[str] | None = None,
) -> dict:
    """Validate sources, compute every actual screener key, atomically publish JSON."""
    if trading_day is None:
        from app.pipeline.commands import _latest_trading_day_for_refresh
        trading_day = _latest_trading_day_for_refresh()
        if not trading_day:
            raise ValueError("no latest raw trading day available")
    trading_day = date.fromisoformat(trading_day).isoformat()
    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8")).get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("empty market metrics universe")
    qfq_dates = []
    for key, row in metrics.items():
        if not re.fullmatch(r"(?:sh|sz|bj):\d{6}", key) or not isinstance(row, dict):
            raise ValueError(f"invalid universe entry: {key}")
        qfq_dates.append(str(row.get("qfq_as_of") or ""))
    # An individual halted/delisted security can have an older last bar; the
    # snapshot date is the maximum QFQ date across the market, not every row.
    main_qfq = [row.get('qfq_as_of') == trading_day for key, row in metrics.items()
                if key.startswith(('sh:', 'sz:'))]
    if max(qfq_dates) != trading_day or (main_qfq and sum(main_qfq) / len(main_qfq) < 0.95):
        raise ValueError(f"stale QFQ market snapshot: newest {max(qfq_dates)} != {trading_day}")

    if universe_keys is None:
        if Path(metrics_path) == MARKET_METRICS:
            from app.stock_filter import _universe
            filter_rows, effective_day = _universe()
            if effective_day != trading_day:
                raise ValueError(f"stale screener universe: {effective_day} != {trading_day}")
            universe_keys = [f"{row['market']}:{row['symbol']}" for row in filter_rows]
        else:
            universe_keys = list(metrics)
    universe_keys = sorted(set(universe_keys))
    if not universe_keys or any(not re.fullmatch(r'(?:sh|sz|bj):\d{6}', key) for key in universe_keys):
        raise ValueError('invalid or empty screener universe')

    from mootdx.reader import Reader
    reader = Reader.factory(market="std", tdxdir=str(tdx_dir))
    disclosures = load_disclosures_bulk(Path(warehouse_dir), trading_day)
    stocks = {}
    for key in universe_keys:
        market, symbol = key.split(":")
        bars = read_raw_bars(reader, market, symbol, trading_day)
        stocks[key] = compute_for_stock(bars, disclosures.get(symbol, []), trading_day)
    raw_coverage = sum(row["pe_percentile_5y_price_date"] == trading_day for row in stocks.values())
    main_market = [key for key in universe_keys if key.startswith(("sh:", "sz:"))]
    main_coverage = sum(stocks[key]["pe_percentile_5y_price_date"] == trading_day for key in main_market)
    if not raw_coverage or (main_market and main_coverage / len(main_market) < 0.8):
        raise ValueError(f"raw daily source coverage insufficient on {trading_day}: "
                         f"{main_coverage}/{len(main_market)} SH/SZ stocks")
    statuses = dict(sorted(Counter(row["pe_percentile_5y_status"] for row in stocks.values()).items()))
    valid = statuses.get("ok", 0)
    payload = {
        "schema_version": "stock-filter-pe-percentile-v1", "as_of_date": trading_day,
        "stocks": stocks,
        "summary": {"total": len(stocks), "raw_price_coverage": raw_coverage,
                    "valid_pe_count": valid, "coverage_pct": round(100 * valid / len(stocks), 2),
                    "status_counts": statuses},
    }
    target = Path(output) if output is not None else DEFAULT_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            tmp_name = stream.name
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trading-day", help="YYYY-MM-DD (defaults to latest raw trading day)")
    parser.add_argument("--output", type=Path, help="override current JSON destination")
    args = parser.parse_args(argv)
    result = build_snapshot(args.trading_day, output=args.output)
    print(json.dumps({"as_of_date": result["as_of_date"], "summary": result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
