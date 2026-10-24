#!/usr/bin/env python3
"""Materialize current or strictly PIT five-rule first-wave snapshots."""
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
from app.first_wave_start import scan_symbol
from app.first_wave_snapshot import CURRENT, HISTORY, SCHEMA_VERSION
from app.stock_filter_history_progress import write_progress

ASSET = ROOT / 'data/derived/datasets/final/first_wave_qfq_ohlcv.parquet'


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        temp = Path(handle.name)
    os.replace(temp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trading-day', default='')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    historical = bool(args.trading_day)
    lock = HISTORY / f'{args.trading_day}.building'
    failure = HISTORY / f'{args.trading_day}.error.json'
    try:
        if not ASSET.is_file():
            raise SystemExit(f'missing required QFQ OHLCV asset: {ASSET}')
        df = pd.read_parquet(ASSET)
        df['date'] = pd.to_datetime(df['date'])
        target = pd.Timestamp(args.trading_day) if historical else df['date'].max()
        if target not in set(df['date']):
            raise SystemExit(f'{target.date()} is not an available QFQ trading day')
        df = df[df.date <= target]
        date = str(target.date())
        out = args.output or (HISTORY / f'{date}.json' if historical else CURRENT)
        if historical:
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.touch(exist_ok=True)
            failure.unlink(missing_ok=True)
            write_progress(HISTORY, date, stage='扫描20日四条件第一波启动', percent=1)
        rows = []
        groups = df.groupby(['market', 'symbol'], sort=True)
        total = groups.ngroups
        for index, ((market, symbol), bars) in enumerate(groups, 1):
            name = str(bars.iloc[-1].get('stock_name') or symbol)
            found = scan_symbol(bars, market=market, symbol=symbol, stock_name=name, as_of_date=date)
            if found:
                rows.append(found)
            if historical and (index % 25 == 0 or index == total):
                write_progress(HISTORY, date, stage='扫描20日四条件第一波启动', percent=2 + 96 * index / total, completed=index, total=total)
        payload = {'schema_version': SCHEMA_VERSION, 'as_of_date': date, 'data_date': str(df.date.max().date()),
                   'price_basis': 'tdx_export_qfq', 'amount_basis': 'tdx_export_daily_amount', 'rows': rows}
        atomic_json(out, payload)
        if historical:
            write_progress(HISTORY, date, stage='快照完成', percent=100, completed=total, total=total)
        print(json.dumps({'output': str(out), 'as_of_date': date, 'rows': len(rows)}, ensure_ascii=False))
    except (Exception, SystemExit) as exc:
        if historical:
            atomic_json(failure, {'schema_version': SCHEMA_VERSION, 'message': str(exc)})
        raise
    finally:
        if historical:
            lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
