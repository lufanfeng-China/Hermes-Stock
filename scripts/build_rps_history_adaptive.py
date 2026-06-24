#!/usr/bin/env python3
"""
Adaptive RPS history gap-fill: auto-detects earliest possible RPS date
from TDX .day files, fills gap to existing Parquet dataset.
"""
import sys, os, struct, time, json
from pathlib import Path

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
EXISTING = PROJECT / 'data/derived/datasets/final/dataset_stock_rps_history.parquet'

sys.path.insert(0, str(PROJECT))

# ── Step 0: Discover earliest TDX data date ──
print("[0/5] Checking TDX data range...", flush=True)

CHECK_CODES = [
    ('sh', '600000'), ('sh', '600519'), ('sh', '601318'),
    ('sz', '000001'), ('sz', '000002'), ('sz', '300750'),
]

earliest_date = None
for market, code in CHECK_CODES:
    path = f'{TDX}/vipdoc/{market}/lday/{market}{code}.day'
    if not os.path.exists(path):
        continue
    sz = os.path.getsize(path)
    recs = sz // 32
    with open(path, 'rb') as f:
        first = f.read(32)
    d = struct.unpack('<I', first[:4])[0]
    date_str = f'{d//10000}-{(d%10000)//100:02d}-{d%100:02d}'
    print(f"  {market}{code}: {recs} records, from {date_str}", flush=True)
    if earliest_date is None or date_str < earliest_date:
        earliest_date = date_str

print(f"  Earliest TDX data: {earliest_date}", flush=True)

if earliest_date is None:
    print("ERROR: No .day files found", flush=True)
    sys.exit(1)

# Need 250 trading days (~1 calendar year) of lookback
# So earliest possible RPS date ≈ earliest TDX date + ~1 year
# We'll compute this precisely after loading data

import pandas as pd
import numpy as np

# ── Step 1: Load existing dataset ──
print("[1/5] Loading existing Parquet...", flush=True)
df_existing = pd.read_parquet(EXISTING)
existing_start = df_existing['trading_day'].min()
existing_end = df_existing['trading_day'].max()
stocks = sorted(set(zip(df_existing['market'], df_existing['symbol'])))
print(f"  Existing: {len(df_existing):,} rows, {len(stocks):,} stocks", flush=True)
print(f"  Range: {existing_start} ~ {existing_end}", flush=True)

# ── Step 2: Load daily data ──
print("[2/5] Loading daily data...", flush=True)
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

close_history = {}
date_history = {}

for i, (market, symbol) in enumerate(stocks):
    if (i+1) % 500 == 0:
        print(f"  {i+1}/{len(stocks)}...", flush=True)
    try:
        df = reader.daily(symbol=symbol)
        if df is None or df.empty:
            continue
        df = df.sort_index()
        if len(df) < 260:
            continue
        key = f"{market}:{symbol}"
        close_history[key] = df['close'].astype(float).tolist()
        date_history[key] = df.index.strftime('%Y-%m-%d').tolist()
    except Exception:
        continue

print(f"  Loaded {len(close_history)} stocks", flush=True)

# ── Step 3: Determine fill date range ──
print("[3/5] Determining fill range...", flush=True)

# Find the stock with most data to use as reference
max_len = max(len(d) for d in date_history.values())
ref_dates = next(d for d in date_history.values() if len(d) == max_len)

# Find earliest date where 250d lookback is satisfied
# The 250th element (index 249) is the first with full lookback
earliest_rps_date = ref_dates[249] if len(ref_dates) > 249 else ref_dates[0]
print(f"  Earliest possible RPS date (250d lookback): {earliest_rps_date}", flush=True)
print(f"  Existing data starts: {existing_start}", flush=True)

# Target: fill from earliest_rps_date to the day before existing_start
target_dates = [d for d in ref_dates if earliest_rps_date <= d < existing_start]

if not target_dates:
    print("  No gap to fill! Data is complete.", flush=True)
    sys.exit(0)

print(f"  Gap: {len(target_dates)} days ({target_dates[0]} ~ {target_dates[-1]})", flush=True)

# ── Step 4: Compute RPS for gap ──
print(f"[4/5] Computing RPS for gap...", flush=True)

all_keys = sorted(close_history.keys())
new_rows = []

for day_num, trading_day in enumerate(target_dates):
    rows_by_symbol = []
    for key in all_keys:
        dates = date_history.get(key, [])
        closes = close_history.get(key, [])
        try:
            idx = dates.index(trading_day)
        except ValueError:
            continue
        if idx < 250:
            continue

        market_val, symbol_val = key.split(':', 1)

        def _ret(window):
            start = idx - window
            if start < 0 or closes[start] == 0:
                return None
            return round((closes[idx] - closes[start]) / closes[start] * 100.0, 4)

        ret20 = _ret(20)
        ret50 = _ret(50)
        ret120 = _ret(120)
        ret250 = _ret(250)
        if all(v is None for v in [ret20, ret50, ret120, ret250]):
            continue
        rows_by_symbol.append({
            'market': market_val, 'symbol': symbol_val,
            'return_20_pct': ret20, 'return_50_pct': ret50,
            'return_120_pct': ret120, 'return_250_pct': ret250,
        })

    if not rows_by_symbol:
        continue

    n = len(rows_by_symbol)

    def rank_rps(rows, field):
        srt = sorted(rows, key=lambda r: float(r[field]) if r[field] is not None else float('-inf'), reverse=True)
        result = {}
        for rank, r in enumerate(srt, 1):
            val = r[field]
            result[(r['market'], r['symbol'])] = round((n - rank + 1) / n * 100.0, 2) if val is not None else None
        return result

    rps20 = rank_rps(rows_by_symbol, 'return_20_pct')
    rps50 = rank_rps(rows_by_symbol, 'return_50_pct')
    rps120 = rank_rps(rows_by_symbol, 'return_120_pct')
    rps250 = rank_rps(rows_by_symbol, 'return_250_pct')

    for row in rows_by_symbol:
        k = (row['market'], row['symbol'])
        new_rows.append({
            'trading_day': trading_day,
            'market': row['market'],
            'symbol': row['symbol'],
            'rps_20': rps20.get(k),
            'rps_50': rps50.get(k),
            'rps_120': rps120.get(k),
            'rps_250': rps250.get(k),
        })

    if (day_num + 1) % 30 == 0 or day_num == 0:
        print(f"  {day_num+1}/{len(target_dates)} ({trading_day}): {len(new_rows):,} new rows", flush=True)

print(f"  New rows: {len(new_rows):,}", flush=True)

# ── Step 5: Merge and save ──
print("[5/5] Merging and saving...", flush=True)

if new_rows:
    df_new = pd.DataFrame(new_rows)
    df_merged = pd.concat([df_new, df_existing], ignore_index=True)
    df_merged = df_merged.sort_values(['trading_day', 'market', 'symbol']).reset_index(drop=True)
    df_merged.to_parquet(EXISTING, compression='snappy', index=False)
    sz = os.path.getsize(EXISTING) / 1024 / 1024
    print(f"  Merged: {len(df_merged):,} rows, {sz:.1f} MB", flush=True)
    print(f"  Range: {df_merged['trading_day'].min()} ~ {df_merged['trading_day'].max()}", flush=True)
    print(f"  Trading days: {df_merged['trading_day'].nunique()}", flush=True)
else:
    print("  No new data to merge.", flush=True)

print("Done.", flush=True)
