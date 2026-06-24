#!/usr/bin/env python3
"""
RPS首次策略 — 全周期回测 (2013~2024)
流式处理: 按天分批读Parquet, 逐日生成信号+模拟, 避免全量内存dict
"""
import sys, json, resource
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict, OrderedDict

try:
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 12 * 1024**3))
except Exception as e:
    print(f"  [warn] memory limit: {e}", file=sys.stderr)

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING_24M = 500
HOLDING_12M = 250

# ── Load full RPS dataset (88MB parquet → ~300MB in memory, acceptable) ──
print("Loading RPS history...", file=sys.stderr)
PARQUET_PATH = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"
df_full = pd.read_parquet(PARQUET_PATH)
df_full['rps_total'] = df_full['rps_20'] + df_full['rps_50'] + df_full['rps_120'] + df_full['rps_250']
print(f"  {len(df_full):,} rows, {df_full['trading_day'].nunique()} days, {df_full['trading_day'].min()} ~ {df_full['trading_day'].max()}", file=sys.stderr)
print(f"  Memory: {df_full.memory_usage(deep=True).sum()/1024**2:.0f} MB", file=sys.stderr)

all_td = sorted(df_full['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}

target_days = [d for d in all_td if d < '2024-07-01']
print(f"  Target: {target_days[0]} ~ {target_days[-1]} ({len(target_days)} days)", file=sys.stderr)

# ── Build RPS>360 first-occurrence index ──
print("Building RPS>360 first-occurrence index...", file=sys.stderr)
df_360 = df_full[df_full['rps_total'] > 360]
rps360_ever = {}
for (market, symbol), group in df_360.groupby(['market', 'symbol'], sort=False):
    rps360_ever[(market, symbol)] = group['trading_day'].min()
print(f"  {len(rps360_ever):,} stocks ever hit RPS>360", file=sys.stderr)

# ── Pre-fetch daily data for ALL stocks (needed for signal filtering + simulation) ──
# Load all stock codes from a sample day
sample = pd.read_parquet(PARQUET_PATH, filters=[('trading_day','=',target_days[0])],
                         columns=['market','symbol'])
all_stocks = sorted(set(zip(sample['market'], sample['symbol'])))
print(f"  {len(all_stocks)} stocks in universe", file=sys.stderr)

print(f"Fetching daily + xdxr data for {len(all_stocks)} stocks...", file=sys.stderr)
daily_cache = {}
xdxr_cache = {}

for i, (m, c) in enumerate(all_stocks):
    if (i+1) % 500 == 0: print(f"  daily {i+1}/{len(all_stocks)}...", file=sys.stderr)
    try:
        d = reader.daily(f"{m}{c}")
        if d is not None and not d.empty:
            daily_cache[f"{m}{c}"] = d.sort_index()
    except: pass
    
    try:
        xd = quotes.xdxr(market=m, symbol=c)
        xm = {}
        if xd is not None and not xd.empty:
            for _, row in xd.iterrows():
                sz = float(row.get('songzhuangu',0) or 0)
                if sz > 0:
                    xm[f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"] = sz
        xdxr_cache[f"{m}{c}"] = xm
    except: xdxr_cache[f"{m}{c}"] = {}

print(f"  {len(daily_cache)} stocks with daily data", file=sys.stderr)

# ── Stream through days, generate signals and simulate ──
print("Processing signals day by day...", file=sys.stderr)
results = []
signals_total = 0
skipped_followup = 0

prev_day_rps = {}  # {(market,symbol): rps_total}

for day_i, td in enumerate(target_days):
    if (day_i + 1) % 200 == 0:
        print(f"  day {day_i+1}/{len(target_days)} ({td}): {signals_total} signals, {len(results)} complete", file=sys.stderr)
    
    # Load today's RPS data
    day_df = pd.read_parquet(PARQUET_PATH, filters=[('trading_day','=',td)]).copy()
    day_df['rps_total'] = day_df['rps_20'] + day_df['rps_50'] + day_df['rps_120'] + day_df['rps_250']
    
    today_rps = {}  # {(market,symbol): rps_total}
    for _, row in day_df.iterrows():
        key = (row['market'], row['symbol'])
        total = row['rps_total']
        today_rps[key] = total
        
        # Check signal conditions
        if total < RPS_MIN: continue
        
        # 60d dedup
        ever_date = rps360_ever.get(key)
        if ever_date and ever_date < td:
            ever_idx = td_to_idx.get(ever_date, -1)
            td_idx = td_to_idx[td]
            if ever_idx >= 0 and (td_idx - ever_idx) <= 60: continue
        
        # Yesterday RPS <= 360
        prev_total = prev_day_rps.get(key)
        if prev_total is not None and prev_total > 360: continue
        
        # Need daily data for trend filter + simulation
        stock_key = f"{row['market']}{row['symbol']}"
        df_stock = daily_cache.get(stock_key)
        if df_stock is None: continue
        
        # Find entry point
        if td not in df_stock.index:
            m = df_stock.index >= td
            if m.sum() == 0: continue
            entry_idx = df_stock.index.get_loc(df_stock.index[m][0])
        else:
            idx_pos = df_stock.index.get_loc(td)
            entry_idx = idx_pos + 1 if idx_pos + 1 < len(df_stock) else idx_pos
        
        if entry_idx + HOLDING_24M >= len(df_stock):
            skipped_followup += 1
            continue
        
        # Trend filter (using data up to signal date)
        closes_before = df_stock.iloc[max(0, entry_idx-60):entry_idx]['close'].astype(float).tolist()
        if len(closes_before) < 60: continue
        
        # Simple trend check: MA20 > MA50 and close > MA20
        def ma(arr, w):
            return sum(arr[-w:])/w if len(arr) >= w else 0
        if ma(closes_before, 20) <= ma(closes_before, 50) or closes_before[-1] <= ma(closes_before, 20):
            continue
        
        # Check if somewhat near MA10
        ma10 = ma(closes_before, 10)
        if abs(closes_before[-1] - ma10) / ma10 * 100 >= 10: continue
        
        # 10-day high
        if closes_before[-1] < max(closes_before[-10:]): continue
        
        # ── Simulate 24M hold ──
        w = df_stock.iloc[entry_idx:entry_idx + HOLDING_24M + 2]
        ep = w.iloc[0]['open']
        if ep <= 0: continue
        
        xm = xdxr_cache.get(stock_key, {})
        w_dates = [str(d)[:10] for d in w.index]
        
        # 24M with xdxr
        ep24 = ep
        for i_day in range(min(HOLDING_24M, len(w))):
            if i_day < len(w_dates) and w_dates[i_day] in xm:
                ep24 *= 1.0/(1.0+xm[w_dates[i_day]]/10.0)
        exit24 = w.iloc[HOLDING_24M+1]['open'] if HOLDING_24M+1 < len(w) else w.iloc[-1]['close']
        ret_24 = round((exit24 - ep24) / ep24 * 100, 2) if ep24 > 0 else None
        
        # 12M
        ep12 = ep
        for i_day in range(min(HOLDING_12M, len(w))):
            if i_day < len(w_dates) and w_dates[i_day] in xm:
                ep12 *= 1.0/(1.0+xm[w_dates[i_day]]/10.0)
        exit12 = w.iloc[HOLDING_12M+1]['open'] if HOLDING_12M+1 < len(w) else w.iloc[HOLDING_12M]['close']
        ret_12 = round((exit12 - ep12) / ep12 * 100, 2) if ep12 > 0 else None
        
        results.append({
            'code': row['symbol'], 'date': td, 'rps': round(total, 2),
            'ret_12': ret_12, 'ret_24': ret_24
        })
        signals_total += 1
    
    prev_day_rps = today_rps

print(f"\n  {signals_total} signals, {len(results)} complete, {skipped_followup} skipped (insufficient follow-up)", file=sys.stderr)

# ── Output ──
print()
print("=" * 120)
print("  RPS首次策略 — 全周期回测 (RPS≥360, 60日去重, T+1开盘, 24月持有)")
print(f"  信号区间: {target_days[0]} ~ {target_days[-1]}, 数据: {all_td[0]} ~ {all_td[-1]}")
print("=" * 120)

by_year = defaultdict(list)
for r in results:
    by_year[r['date'][:4]].append(r)

print(f"\n  {'─'*80}")
print(f"  {'年份':<8} {'信号数':>6} {'12月均收益':>12} {'12月胜率':>9} {'24月均收益':>12} {'24月胜率':>9}")
print(f"  {'─'*80}")

all_12 = []; all_24 = []

for year in sorted(by_year.keys()):
    yr = by_year[year]
    r12 = [r['ret_12'] for r in yr if r['ret_12'] is not None]
    r24 = [r['ret_24'] for r in yr if r['ret_24'] is not None]
    n = len(yr)
    
    a12 = f"{sum(r12)/len(r12):+7.1f}%" if r12 else "N/A"
    w12 = f"{sum(1 for x in r12 if x>0)/len(r12)*100:>5.0f}%" if r12 else "N/A"
    a24 = f"{sum(r24)/len(r24):+7.1f}%" if r24 else "N/A"
    w24 = f"{sum(1 for x in r24 if x>0)/len(r24)*100:>5.0f}%" if r24 else "N/A"
    
    print(f"  {year:<8} {n:>6} {a12:>12} {w12:>9} {a24:>12} {w24:>9}")
    all_12.extend(r12); all_24.extend(r24)

print(f"  {'─'*80}")
a12_all = sum(all_12)/len(all_12) if all_12 else 0
w12_all = sum(1 for x in all_12 if x>0)/len(all_12)*100 if all_12 else 0
a24_all = sum(all_24)/len(all_24) if all_24 else 0
w24_all = sum(1 for x in all_24 if x>0)/len(all_24)*100 if all_24 else 0
print(f"  {'合计':<8} {len(results):>6} {a12_all:>+11.1f}% {w12_all:>8.0f}% {a24_all:>+11.1f}% {w24_all:>8.0f}%")

# Market context
print(f"\n  市场背景:")
context = {
    '2013': '震荡筑底（创业板牛市起点）','2014': '下半年券商暴动，沪指翻倍',
    '2015': '疯牛+股灾（6月高点，千股跌停）','2016': '熔断+震荡修复',
    '2017': '结构性牛市（白马股行情）','2018': '熊市（贸易战）',
    '2019': '复苏反弹（科创板开板）','2020': '疫情暴跌+V型反弹（新能源爆发）',
    '2021': '结构性牛市（新能源、半导体）','2022': '熊市（美联储加息）',
    '2023': '震荡分化（AI行情）','2024': '震荡修复',
}
for yr in sorted(by_year.keys()):
    if yr in context:
        n = len(by_year[yr])
        r24 = [r['ret_24'] for r in by_year[yr] if r['ret_24'] is not None]
        a24 = f"{sum(r24)/len(r24):+.1f}%" if r24 else "N/A"
        print(f"    {yr}: {n}笔, 24月均{a24} | {context[yr]}")

# Distribution
print(f"\n  {'─'*80}")
print(f"  24月收益分布 (已完成{len(all_24)}笔):")
buckets = [(-100, -50), (-50, -25), (-25, -10), (-10, 0), (0, 10), (10, 25),
           (25, 50), (50, 100), (100, 200), (200, 500), (500, 9999)]
for lo, hi in buckets:
    cnt = sum(1 for r in all_24 if lo <= r < hi)
    pct = cnt/len(all_24)*100 if all_24 else 0
    bar = '█' * int(pct)
    rng = f"{lo:+d}~{hi:+d}" if hi < 9999 else f">{lo:+d}"
    print(f"  {rng:>12} {cnt:>5} ({pct:>5.1f}%) {bar}")
