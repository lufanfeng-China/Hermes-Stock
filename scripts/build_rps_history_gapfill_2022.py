#!/usr/bin/env python3
"""
Build RPS history for 2022-01-01 to 2022-08-11 (gap-fill).
Merges with existing Parquet dataset.
"""
import sys, os, time, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
EXISTING = PROJECT / 'data/derived/datasets/final/dataset_stock_rps_history.parquet'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

import pandas as pd
import numpy as np

START_DATE = '2022-01-01'
END_DATE = '2022-08-11'  # exclusive, existing data starts 2022-08-12

# ── Step 1: Load existing stock universe ──
print("[1/4] Loading existing dataset...", flush=True)
df_existing = pd.read_parquet(EXISTING)
stocks = sorted(set(zip(df_existing['market'], df_existing['symbol'])))
print(f"  Existing: {len(df_existing):,} rows, {len(stocks):,} stocks", flush=True)
print(f"  Date range: {df_existing['trading_day'].min()} ~ {df_existing['trading_day'].max()}", flush=True)

# ── Step 2: Load daily closes for all stocks (from 2020 to ensure 250d lookback) ──
print("[2/4] Loading daily data for all stocks...", flush=True)
close_history = {}   # key -> list of closes
date_history = {}    # key -> list of dates (YYYY-MM-DD)

for i, (market, symbol) in enumerate(stocks):
    if (i+1) % 500 == 0:
        print(f"  {i+1}/{len(stocks)}...", flush=True)
    try:
        df = reader.daily(symbol=symbol)
        if df is None or df.empty:
            continue
        df = df.sort_index()
        # Filter to dates after 2020-01-01 (enough lookback for 250d returns)
        mask = df.index >= '2020-01-01'
        df = df.loc[mask]
        if len(df) < 260:
            continue
        key = f"{market}:{symbol}"
        close_history[key] = df['close'].astype(float).tolist()
        date_history[key] = df.index.strftime('%Y-%m-%d').tolist()
    except Exception:
        continue

print(f"  Loaded {len(close_history)} stocks with sufficient history", flush=True)

# ── Step 3: Build target date list ──
# Find the intersection of all trading dates to get a common date index
# Use the stock with the most dates as reference
max_len = max(len(d) for d in date_history.values())
ref_dates = next(d for d in date_history.values() if len(d) == max_len)
target_dates = [d for d in ref_dates if START_DATE <= d < END_DATE]

print(f"[3/4] Computing RPS for {len(target_dates)} days ({target_dates[0]} ~ {target_dates[-1]})...", flush=True)

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

    # Cross-sectional RPS ranking
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

    if (day_num + 1) % 20 == 0 or day_num == 0:
        print(f"  {day_num+1}/{len(target_dates)} ({trading_day}): {len(new_rows):,} new rows", flush=True)

print(f"  Total new rows: {len(new_rows):,}", flush=True)

# ── Step 4: Merge and save ──
print("[4/4] Merging with existing and saving...", flush=True)
df_new = pd.DataFrame(new_rows)
df_merged = pd.concat([df_new, df_existing], ignore_index=True)
df_merged = df_merged.sort_values(['trading_day', 'market', 'symbol']).reset_index(drop=True)

# Save
df_merged.to_parquet(EXISTING, compression='snappy', index=False)
sz = os.path.getsize(EXISTING) / 1024 / 1024
print(f"  Merged: {len(df_merged):,} rows, {sz:.1f} MB", flush=True)
print(f"  Date range: {df_merged['trading_day'].min()} ~ {df_merged['trading_day'].max()}", flush=True)
print(f"  Trading days: {df_merged['trading_day'].nunique()}", flush=True)
print("Done.", flush=True)
