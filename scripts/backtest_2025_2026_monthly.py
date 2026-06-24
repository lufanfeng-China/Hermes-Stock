#!/usr/bin/env python3
"""
RPS首次策略 — 2025-01 ~ 2026-06 月度回测 v3
权威定义 × vectorized趋势 × 无resource limit × groupby代替逐日filter
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
PARQUET_PATH = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING_24M = 500

# ── Vectorized trend ──
def classify_trend_vec(closes_series):
    n = len(closes_series)
    if n < 60: return "insufficient"
    close = closes_series.iloc[-1]
    ma20 = closes_series.rolling(20).mean()
    ma50 = closes_series.rolling(50).mean()
    m20, m50 = ma20.iloc[-1], ma50.iloc[-1]
    if pd.isna(m20) or pd.isna(m50): return "insufficient"
    s20 = (m20 - ma20.iloc[-6]) / ma20.iloc[-6] if n >= 6 and not pd.isna(ma20.iloc[-6]) else 0
    s50 = (m50 - ma50.iloc[-11]) / ma50.iloc[-11] if n >= 11 and not pd.isna(ma50.iloc[-11]) else 0
    if n >= 250:
        ma120 = closes_series.rolling(120).mean(); ma250 = closes_series.rolling(250).mean()
        m120, m250 = ma120.iloc[-1], ma250.iloc[-1]
        if not pd.isna(m120) and not pd.isna(m250):
            if m20 > m50 > m120 > m250 and close > m20 and s20 > 0 and s50 > 0: return "strong_bullish"
            if m20 < m50 < m120 < m250 and close < m20 and s20 < 0: return "strong_bearish"
    if n >= 120:
        ma120 = closes_series.rolling(120).mean()
        m120 = ma120.iloc[-1]
        if not pd.isna(m120):
            if m20 > m50 > m120 and close > m20 and s20 > 0: return "bullish"
            if m20 < m50 < m120 and close < m50: return "bearish"
    if m20 > m50 and close > m20: return "recovering"
    return "neutral"

def classify_short_trend_vec(closes_series):
    n = len(closes_series)
    if n < 30: return "insufficient"
    close = closes_series.iloc[-1]
    ma10 = closes_series.rolling(10).mean(); ma20 = closes_series.rolling(20).mean()
    m10, m20 = ma10.iloc[-1], ma20.iloc[-1]
    if pd.isna(m10) or pd.isna(m20): return "insufficient"
    s10 = (m10 - ma10.iloc[-4]) / ma10.iloc[-4] if n >= 4 and not pd.isna(ma10.iloc[-4]) else 0
    s20 = (m20 - ma20.iloc[-6]) / ma20.iloc[-6] if n >= 6 and not pd.isna(ma20.iloc[-6]) else 0
    if n >= 60:
        ma30 = closes_series.rolling(30).mean(); ma60 = closes_series.rolling(60).mean()
        m30, m60 = ma30.iloc[-1], ma60.iloc[-1]
        if not pd.isna(m30) and not pd.isna(m60):
            if m10 > m20 > m30 > m60 and close > m10 and s10 > 0 and s20 > 0: return "strong_bullish"
            if m10 < m20 < m30 < m60 and close < m10 and s10 < 0: return "strong_bearish"
    if n >= 30:
        ma30 = closes_series.rolling(30).mean(); m30 = ma30.iloc[-1]
        if not pd.isna(m30):
            if m10 > m20 > m30 and close > m10 and s10 > 0: return "bullish"
            if m10 < m20 < m30 and close < m20: return "bearish"
    if m10 > m20 and close > m10: return "recovering"
    return "neutral"

# ── Load ──
print("Loading RPS...", flush=True)
df_full = pd.read_parquet(PARQUET_PATH)
df_full['rps_total'] = df_full['rps_20'] + df_full['rps_50'] + df_full['rps_120'] + df_full['rps_250']
last_td = str(df_full['trading_day'].max())
print(f"  {len(df_full):,} rows, {df_full['trading_day'].nunique()} days, last={last_td}", flush=True)

all_td = sorted(df_full['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}

# Filter to 2025-2026.06
mask = (df_full['trading_day'] >= '2025-01-01') & (df_full['trading_day'] < '2026-07-01')
df_target = df_full[mask].copy()
target_days = sorted(df_target['trading_day'].unique())
print(f"  Target: {target_days[0]} ~ {target_days[-1]} ({len(target_days)} days, {len(df_target):,} rows)", flush=True)

# RPS>360 index (from full data)
print("Building RPS>360 index...", flush=True)
df_360 = df_full[df_full['rps_total'] > 360]
rps360_ever = {}
for (market, symbol), group in df_360.groupby(['market', 'symbol'], sort=False):
    rps360_ever[(market, symbol)] = group['trading_day'].min()
print(f"  {len(rps360_ever):,} stocks", flush=True)

# ── Process day by day using df_target (pre-filtered!) ──
print("Processing signals...", flush=True)
results = []
prev_day_rps = {}
daily_cache = {}
xdxr_cache = {}

for day_i, td in enumerate(target_days):
    if (day_i + 1) % 50 == 0:
        print(f"  day {day_i+1}/{len(target_days)} ({td}): {len(results)} signals", flush=True)
    
    day_df = df_target[df_target['trading_day'] == td]
    
    today_rps = {}
    for _, row in day_df.iterrows():
        market_str = row['market']
        symbol_str = row['symbol']
        key = (market_str, symbol_str)
        total = float(row['rps_total'])
        today_rps[key] = total
        
        if total < RPS_MIN: continue
        
        # 60d dedup
        ever_date = rps360_ever.get(key)
        if ever_date and ever_date < td:
            ever_idx = td_to_idx.get(ever_date, -1)
            td_idx_curr = td_to_idx[td]
            if ever_idx >= 0 and (td_idx_curr - ever_idx) <= 60: continue
        
        # Yesterday RPS <= 360
        prev_total = prev_day_rps.get(key)
        if prev_total is not None and prev_total > 360: continue
        
        # On-demand daily fetch
        stock_key = f"{market_str}{symbol_str}"
        if stock_key not in daily_cache:
            try:
                d = reader.daily(stock_key)
                if d is not None and not d.empty:
                    daily_cache[stock_key] = d.sort_index()
                else:
                    daily_cache[stock_key] = None
                    continue
            except:
                daily_cache[stock_key] = None
                continue
            # xdxr
            try:
                xd = quotes.xdxr(market=market_str, symbol=symbol_str)
                xm = {}
                if xd is not None and not xd.empty:
                    for _, xr in xd.iterrows():
                        sz = float(xr.get('songzhuangu',0) or 0)
                        if sz > 0:
                            xm[f"{int(xr['year']):04d}-{int(xr['month']):02d}-{int(xr['day']):02d}"] = sz
                xdxr_cache[stock_key] = xm
            except:
                xdxr_cache[stock_key] = {}
        
        df_stock = daily_cache.get(stock_key)
        xm = xdxr_cache.get(stock_key, {})
        if df_stock is None: continue
        
        if td not in df_stock.index:
            m = df_stock.index >= td
            if m.sum() == 0: continue
            entry_idx = df_stock.index.get_loc(df_stock.index[m][0])
        else:
            entry_idx = df_stock.index.get_loc(td)
        
        closes_before = df_stock.iloc[:entry_idx+1]['close']
        if len(closes_before) < 60: continue
        
        trend = classify_trend_vec(closes_before)
        if trend not in ("bullish", "strong_bullish"): continue
        short_trend = classify_short_trend_vec(closes_before)
        if short_trend not in ("bullish", "strong_bullish"): continue
        
        close_t = closes_before.iloc[-1]
        ma10 = closes_before.iloc[-10:].mean()
        if abs(close_t - ma10) / ma10 >= 0.10: continue
        if close_t < closes_before.iloc[-10:].max() - 1e-9: continue
        
        entry_idx += 1
        if entry_idx >= len(df_stock): continue
        
        ep = df_stock.iloc[entry_idx]['open']
        if ep <= 0: continue
        
        remaining = len(df_stock) - entry_idx
        
        def compute_return(hold_days):
            end_idx = min(entry_idx + hold_days, len(df_stock) - 1)
            exit_idx = end_idx + 1 if end_idx + 1 < len(df_stock) else end_idx
            ep_adj = ep
            for i_day in range(min(hold_days, remaining)):
                ds = str(df_stock.index[entry_idx + i_day])[:10]
                if ds in xm:
                    ep_adj *= 1.0 / (1.0 + xm[ds] / 10.0)
            exit_px = df_stock.iloc[exit_idx]['open'] if exit_idx < len(df_stock) else df_stock.iloc[-1]['close']
            if ep_adj <= 0: return None
            return round((exit_px - ep_adj) / ep_adj * 100, 2)
        
        ret_hold = compute_return(remaining - 1)
        ret_24 = compute_return(HOLDING_24M) if remaining > HOLDING_24M else None
        
        results.append({
            'code': symbol_str, 'date': td, 'month': td[:7],
            'rps': round(total, 2), 'ret_hold': ret_hold, 'ret_24': ret_24,
        })
    
    prev_day_rps = today_rps

print(f"\n  {len(results)} signals total", flush=True)

# ── Output ──
print()
print("=" * 110)
print("  RPS首次策略 — 2025-01 ~ 2026-06 月度回测")
print(f"  权威定义: RPS≥360上穿 + 60日去重 + 趋势多头 + 短趋势多头 + 距MA10<10% + 10日最高")
print(f"  买入: T+1开盘 | 等权 | xdxr送转股已调整 | 数据截止: {last_td}")
print("=" * 110)

by_month = defaultdict(list)
for r in results:
    by_month[r['month']].append(r)

print(f"\n  {'买入月份':<10} {'笔数':>4} {'24月退出均':>10} {'持有至今均':>10} {'24月胜率':>8} {'持有胜率':>8}")
print(f"  {'─'*65}")

all_24 = []; all_hold = []
for month in sorted(by_month.keys()):
    mr = by_month[month]; n = len(mr)
    r24 = [r['ret_24'] for r in mr if r['ret_24'] is not None]
    rh = [r['ret_hold'] for r in mr if r['ret_hold'] is not None]
    a24 = f"{sum(r24)/len(r24):+6.1f}%" if r24 else "N/A"
    ah = f"{sum(rh)/len(rh):+6.1f}%" if rh else "N/A"
    w24 = f"{sum(1 for x in r24 if x>0)/len(r24)*100:>3.0f}%" if r24 else ""
    wh = f"{sum(1 for x in rh if x>0)/len(rh)*100:>3.0f}%" if rh else ""
    print(f"  {month:<10} {n:>4} {a24:>10} {ah:>10} {w24:>8} {wh:>8}")
    all_24.extend(r24); all_hold.extend(rh)

print(f"\n  {'─'*65}")
print(f"  合计           {len(results):>4} ", end="")
a24 = f"{sum(all_24)/len(all_24):+6.1f}%" if all_24 else "N/A"
ah = f"{sum(all_hold)/len(all_hold):+6.1f}%" if all_hold else "N/A"
w24 = f"{sum(1 for x in all_24 if x>0)/len(all_24)*100:>3.0f}%" if all_24 else ""
wh = f"{sum(1 for x in all_hold if x>0)/len(all_hold)*100:>3.0f}%" if all_hold else ""
print(f"{a24:>10} {ah:>10} {w24:>8} {wh:>8}")
n24 = len(all_24) if all_24 else 0
print(f"\n  24月退出: {n24}/{len(results)}笔 | 持有至今: {len(all_hold)}/{len(results)}笔 | 截止: {last_td}")
