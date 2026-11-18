#!/usr/bin/env python3
"""Atomically publish current turnover percentile and auditable daily samples."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.stock_filter_turnover_snapshot import build_turnover_snapshot, load_reports_bulk

FINAL = ROOT / 'data/derived/datasets/final'
WAREHOUSE = ROOT / 'data/derived/financial_ts/by_quarter'
QFQ = FINAL / 'stock_filter_qfq_daily.parquet'
RPS = FINAL / 'dataset_stock_rps_history.parquet'
OUTPUT = FINAL / 'stock_filter_turnover_percentile_current.json'


def main() -> None:
    rps = pd.read_parquet(RPS, columns=['trading_day', 'market', 'symbol'])
    if rps.empty:
        raise ValueError('RPS universe is empty; turnover publication blocked')
    day = str(rps['trading_day'].max())
    universe = rps[rps['trading_day'] == day]
    keys = set(universe['market'].astype(str) + ':' + universe['symbol'].astype(str).str.zfill(6))
    del rps, universe
    # Every published historical day compares with its OWN prior year of
    # complete seven-day windows. An arbitrary two-year calendar filter loses
    # the six effective prehistory observations for sparse/suspended listings.
    bars = pd.read_parquet(QFQ, columns=['date', 'market', 'symbol', 'open', 'close', 'volume'])
    if bars.empty or bars['date'].max().strftime('%Y-%m-%d') != day:
        raise ValueError(f'QFQ daily source not aligned with RPS {day}; publication blocked')
    reports = load_reports_bulk(WAREHOUSE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    history_path = FINAL / f'stock_filter_turnover_daily_{day}.parquet'
    temporary = None
    writer = None
    buffer = []
    audit_rows = 0

    def flush() -> None:
        nonlocal writer, audit_rows
        if not buffer:
            return
        table = pa.Table.from_pylist(buffer)
        if writer is None:
            writer = pq.ParquetWriter(temporary, table.schema, compression='zstd')
        writer.write_table(table)
        audit_rows += len(buffer)
        buffer.clear()

    def append(rows: list[dict]) -> None:
        buffer.extend(rows)
        if len(buffer) >= 25000:
            flush()

    try:
        with NamedTemporaryFile(dir=FINAL, prefix='.turnover-daily-', suffix='.parquet', delete=False) as handle:
            temporary = Path(handle.name)
        payload, _ = build_turnover_snapshot(bars, reports, as_of_date=day,
                                             universe_keys=keys, on_daily=append)
        flush()
        if writer is None:
            raise ValueError('no auditable turnover sample; publication blocked')
        writer.close()
        writer = None
        os.replace(temporary, history_path)
        temporary = None
        payload['daily_audit_file'] = history_path.name
        payload['daily_audit_rows'] = audit_rows
        with NamedTemporaryFile('w', encoding='utf-8', dir=FINAL,
                                prefix='.turnover-current-', suffix='.json', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        os.replace(temporary, OUTPUT)
        temporary = None
    finally:
        if writer is not None:
            writer.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'output': str(OUTPUT), 'daily_audit_file': str(history_path),
                      'as_of_date': day, 'stocks': len(keys), 'daily_rows': audit_rows,
                      'valid_percentiles': sum(row['turnover_percentile_1y'] is not None
                                               for row in payload['stocks'].values())}, ensure_ascii=False))


if __name__ == '__main__':
    main()
