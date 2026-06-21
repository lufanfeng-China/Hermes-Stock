#!/usr/bin/env python3
"""
全量RPS历史构建 — 从TDX日线目录扫描所有股票
"""
import sys, json, os, glob
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX_LDAY = '/mnt/c/new_tdx64/vipdoc/sh/lday'
TDX_SZ_LDAY = '/mnt/c/new_tdx64/vipdoc/sz/lday'
OUTPUT = PROJECT / 'data/derived/datasets/final/dataset_stock_rps_history.json'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir='/mnt/c/new_tdx64')

# ── Step 1: discover all stocks from TDX .day files ──
print("[1/4] Discovering stocks from TDX...", flush=True)
stocks = []
for market, lday_dir in [('sh', TDX_LDAY), ('sz', TDX_SZ_LDAY)]:
    for f in glob.glob(os.path.join(lday_dir, '*.day')):
        code = os.path.splitext(os.path.basename(f))[0]
        # sh/day/60xxxx.day or sz/day/00xxxx.day etc
        if code.startswith('sh') or code.startswith('sz'):
            code = code[2:]
        # Skip indices
        if code.startswith('999') or code.startswith('399'): continue
        stocks.append({'market': market, 'code': code})

print(f"  Found {len(stocks)} .day files", flush=True)

# ── Step 2: load close history ──
print("[2/4] Loading daily data...", flush=True)
close_history = {}
trading_dates = {}
count = 0
for s in stocks:
    count += 1
    if count % 500 == 0: print(f"  {count}/{len(stocks)}...", flush=True)
    try:
        df = reader.daily(f"{s['market']}{s['code']}")
        if df is None or df.empty: continue
        df = df.sort_index()
        closes = df['close'].astype(float).tolist()
        dates = df.index.strftime('%Y-%m-%d').tolist()
        if len(closes) < 260: continue  # need at least 1 year
        key = f"{s['market']}:{s['code']}"
        close_history[key] = closes
        trading_dates[key] = dates
    except: pass

print(f"  Loaded {len(close_history)} stocks", flush=True)

# ── Step 3: find reference dates ──
max_len = max(len(d) for d in trading_dates.values())
ref_dates = next(d for d in trading_dates.values() if len(d) == max_len)
# Use ALL days (or cap at reasonable number)
ndays = len(ref_dates)
print(f"[3/4] Computing RPS for {ndays} days ({ref_dates[0]} ~ {ref_dates[-1]})...", flush=True)

all_rows = []
all_keys = sorted(close_history.keys())

for day_num, trading_day in enumerate(ref_dates):
    rows_by_symbol = []
    for key in all_keys:
        dates = trading_dates.get(key, [])
        closes = close_history.get(key, [])
        try:
            idx = dates.index(trading_day)
        except ValueError:
            continue
        if idx < 250: continue
        
        market_val, code = key.split(':', 1)
        
        def _ret(window):
            start = idx - window
            if start < 0 or closes[start] == 0: return None
            return round((closes[idx] - closes[start]) / closes[start] * 100.0, 4)
        
        ret20, ret50, ret120, ret250 = _ret(20), _ret(50), _ret(120), _ret(250)
        if all(v is None for v in [ret20, ret50, ret120, ret250]): continue
        rows_by_symbol.append({
            'market': market_val, 'code': code,
            'return_20_pct': ret20, 'return_50_pct': ret50,
            'return_120_pct': ret120, 'return_250_pct': ret250,
        })
    
    if not rows_by_symbol: continue
    
    # Cross-sectional RPS ranking
    n = len(rows_by_symbol)
    def rank_rps(rows, field):
        srt = sorted(rows, key=lambda r: float(r[field]) if r[field] is not None else float('-inf'), reverse=True)
        result = {}
        for rank, r in enumerate(srt, 1):
            val = r[field]
            result[(r['market'], r['code'])] = round((n - rank + 1) / n * 100.0, 2) if val is not None else None
        return result
    
    rps20 = rank_rps(rows_by_symbol, 'return_20_pct')
    rps50 = rank_rps(rows_by_symbol, 'return_50_pct')
    rps120 = rank_rps(rows_by_symbol, 'return_120_pct')
    rps250 = rank_rps(rows_by_symbol, 'return_250_pct')
    
    for row in rows_by_symbol:
        k = (row['market'], row['code'])
        all_rows.append({
            'trading_day': trading_day, 'market': row['market'], 'symbol': row['code'],
            'rps_20': rps20.get(k), 'rps_50': rps50.get(k),
            'rps_120': rps120.get(k), 'rps_250': rps250.get(k),
        })
    
    if (day_num+1) % 50 == 0:
        print(f"  {day_num+1}/{ndays} ({trading_day}): {len(all_rows)} rows", flush=True)

# ── Step 4: save ──
print(f"[4/4] Writing {len(all_rows)} rows...", flush=True)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(all_rows, ensure_ascii=False), encoding='utf-8')
MB = OUTPUT.stat().st_size / 1024 / 1024
print(f"  Done: {MB:.1f} MB, {len(all_rows)} rows, {ndays} days ({ref_dates[0]} ~ {ref_dates[-1]})", flush=True)
