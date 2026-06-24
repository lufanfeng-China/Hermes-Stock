#!/usr/bin/env python3
"""
RPS首次策略 — 全周期月度回测 (2013~2026)
纯 RPS>365 过滤, 对比: 持有至今 / 12月 / 24月
"""
import sys, resource
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

try:
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 12 * 1024**3))
except: pass

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
PARQUET_PATH = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 365
HOLDING_12M = 250
HOLDING_24M = 500

# ── Trend helpers (from RPS首次 preset) ──
def classify_trend(closes):
    n = len(closes)
    if n < 60: return "insufficient"
    def ma(arr, w):
        r = [None]*len(arr)
        for i in range(len(arr)):
            if i >= w-1: r[i] = sum(arr[i-w+1:i+1])/w
        return r
    def last(arr):
        for v in reversed(arr):
            if v is not None: return v
        return None
    ma20=ma(closes,20); ma50=ma(closes,50)
    ma120=ma(closes,120) if n>=120 else None
    ma250=ma(closes,250) if n>=250 else None
    m20=last(ma20); m50=last(ma50)
    m120=last(ma120) if ma120 else None
    m250=last(ma250) if ma250 else None
    if m20 is None or m50 is None: return "insufficient"
    close=closes[-1]
    s20=(m20-(ma20[-6] if len(ma20)>=6 and ma20[-6] is not None else m20))/((ma20[-6] or 1))
    s50=(m50-(ma50[-11] if len(ma50)>=11 and ma50[-11] is not None else m50))/((ma50[-11] or 1))
    if m250 and m120 and m20>m50>m120>m250 and close>m20 and s20>0 and s50>0: return "strong_bullish"
    if m120 and m20>m50>m120 and close>m20 and s20>0: return "bullish"
    if m250 and m120 and m20<m50<m120<m250 and close<m20 and s20<0: return "strong_bearish"
    if m120 and m20<m50<m120 and close<m50: return "bearish"
    if m20>m50 and close>m20: return "recovering"
    return "neutral"

def classify_short_trend(closes):
    n = len(closes)
    if n < 30: return "insufficient"
    def ma(arr,w):
        r=[None]*len(arr)
        for i in range(len(arr)):
            if i>=w-1: r[i]=sum(arr[i-w+1:i+1])/w
        return r
    def last(arr):
        for v in reversed(arr):
            if v is not None: return v
        return None
    ma10=ma(closes,10); ma20=ma(closes,20)
    ma30=ma(closes,30) if n>=30 else None
    ma60=ma(closes,60) if n>=60 else None
    m10=last(ma10); m20=last(ma20)
    m30=last(ma30) if ma30 else None
    m60=last(ma60) if ma60 else None
    if m10 is None or m20 is None: return "insufficient"
    close=closes[-1]
    s10=(m10-(ma10[-4] if len(ma10)>=4 and ma10[-4] is not None else m10))/((ma10[-4] or 1))
    s20=(m20-(ma20[-6] if len(ma20)>=6 and ma20[-6] is not None else m20))/((ma20[-6] or 1))
    if m60 and m30 and m10>m20>m30>m60 and close>m10 and s10>0 and s20>0: return "strong_bullish"
    if m30 and m10>m20>m30 and close>m10 and s10>0: return "bullish"
    if m60 and m30 and m10<m20<m30<m60 and close<m10 and s10<0: return "strong_bearish"
    if m30 and m10<m20<m30 and close<m20: return "bearish"
    if m10>m20 and close>m10: return "recovering"
    return "neutral"

# ── Load RPS ──
print("Loading RPS...", file=sys.stderr)
df_full = pd.read_parquet(PARQUET_PATH)
df_full['rps_total'] = df_full['rps_20'] + df_full['rps_50'] + df_full['rps_120'] + df_full['rps_250']
print(f"  {len(df_full):,} rows, {df_full['trading_day'].nunique()} days, {df_full['trading_day'].min()} ~ {df_full['trading_day'].max()}", file=sys.stderr)

all_td = sorted(df_full['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}

# Target all days from 2013 onward
# Skip the first day since we need yesterday data for cross check
target_days = [d for d in all_td if d >= '2013-01-16']
print(f"  Target: {target_days[0]} ~ {target_days[-1]} ({len(target_days)} days)", file=sys.stderr)

# ── Rule 2: track most recent SIGNAL for 60d dedup (not first RPS>360) ──
last_signal = {}

# ── Pre-fetch daily data ──
# Get ALL unique stocks across the entire period (not just first day)
all_market_symbol = df_full[['market', 'symbol']].drop_duplicates()
all_stocks = sorted(set(zip(all_market_symbol['market'], all_market_symbol['symbol'])))
print(f"  {len(all_stocks)} stocks", file=sys.stderr)

print(f"Fetching daily data for {len(all_stocks)} stocks...", file=sys.stderr)
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
        xdxr_mkt = 0 if m in ('sz', '0') else 1
        xd = quotes.xdxr(market=xdxr_mkt, symbol=c)
        xm = {}
        if xd is not None and not xd.empty:
            for _, row in xd.iterrows():
                sz = float(row.get('songzhuangu',0) or 0)
                if sz > 0:
                    xm[f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"] = sz
        xdxr_cache[f"{m}{c}"] = xm
    except: xdxr_cache[f"{m}{c}"] = {}

print(f"  {len(daily_cache)} stocks with daily data", file=sys.stderr)

# ── Stream through days ──
print("Processing signals...", file=sys.stderr)
results = []
signals_total = 0
skipped = 0
prev_day_rps = {}

# ── Rule 1: Preload prev_day_rps with day before first target ──
first_td_idx = td_to_idx.get(target_days[0], -1)
if first_td_idx > 0:
    prev_td = all_td[first_td_idx - 1]
    prev_day_df = df_full[df_full['trading_day'] == prev_td]
    for _, row in prev_day_df.iterrows():
        prev_day_rps[(row['market'], row['symbol'])] = float(row['rps_total'])

for day_i, td in enumerate(target_days):
    if (day_i + 1) % 300 == 0:
        print(f"  day {day_i+1}/{len(target_days)} ({td}): {signals_total} signals, {len(results)} complete", file=sys.stderr)
    
    day_df = df_full[df_full['trading_day'] == td].copy()
    day_df['rps_total'] = day_df['rps_20'] + day_df['rps_50'] + day_df['rps_120'] + day_df['rps_250']
    
    today_rps = {}
    for _, row in day_df.iterrows():
        key = (row['market'], row['symbol'])
        total = row['rps_total']
        today_rps[key] = total
        
        if total < RPS_MIN: continue
        
        # Rule 2: 60d dedup by most recent SIGNAL
        last_date = last_signal.get(key)
        if last_date is not None:
            last_idx = td_to_idx.get(last_date, -1)
            td_idx_curr = td_to_idx[td]
            if last_idx >= 0 and (td_idx_curr - last_idx) <= 60: continue
        
        # Yesterday RPS <= RPS_MIN (首次上穿)
        prev_total = prev_day_rps.get(key)
        if prev_total is not None and prev_total > RPS_MIN: continue
        
        # Get daily data for trend filter
        stock_key = f"{row['market']}{row['symbol']}"
        df_stock = daily_cache.get(stock_key)
        if df_stock is None: continue
        
        # Find signal date position for trend analysis
        if td not in df_stock.index:
            m = df_stock.index >= td
            if m.sum() == 0: continue
            entry_idx = df_stock.index.get_loc(df_stock.index[m][0])
        else:
            idx_pos = df_stock.index.get_loc(td)
            entry_idx = idx_pos
        
        # Extract ALL closes history up to signal date for trend filter
        closes_before = df_stock.iloc[:entry_idx+1]['close'].astype(float).tolist()
        if len(closes_before) < 60: continue
        
        # Trend filters (RPS首次 preset)
        trend = classify_trend(closes_before)
        if trend not in ("bullish", "strong_bullish"): continue
        short_trend = classify_short_trend(closes_before)
        if short_trend not in ("bullish", "strong_bullish"): continue
        
        # Close within 10% of MA10
        ma10 = sum(closes_before[max(0,len(closes_before)-10):]) / 10
        if abs(closes_before[-1] - ma10) / ma10 * 100 >= 10: continue
        
        # Close is 10-day high
        if closes_before[-1] < max(closes_before[max(0,len(closes_before)-10):]) - 1e-9: continue
        
        # Entry: next trading day after signal
        entry_idx = entry_idx + 1  # next day
        if entry_idx >= len(df_stock): continue
        
        ep = df_stock.iloc[entry_idx]['open']
        if ep <= 0: continue
        
        xm = xdxr_cache.get(stock_key, {})
        remaining = len(df_stock) - entry_idx
        
        # ── Strategy exit simulations (day-by-day walk-forward) ──
        STOP_LOSS = -0.15
        TAKE_PROFIT = 0.30
        TIME_EXIT_DAYS = 122  # ~6 months
        
        best_close = ep
        ep_orig = ep  # save original entry price for separate calculations
        ret_s1 = None  # fixed SL/TP + time
        ret_s3 = None  # trailing stop + time
        ret_hold = None
        ret_12 = None
        
        for i_day in range(remaining):
            idx = entry_idx + i_day
            day_close = float(df_stock.iloc[idx]['close'])
            
            # Apply xdxr adjustment for this day (cumulative on ep)
            ds = str(df_stock.index[idx])[:10]
            if ds in xm:
                ep *= 1.0 / (1.0 + xm[ds] / 10.0)
            
            # Strategy 1: Fixed SL/TP
            if ret_s1 is None:
                ret = (day_close - ep) / ep
                if ret <= STOP_LOSS:
                    ret_s1 = round(STOP_LOSS * 100, 2)
                elif ret >= TAKE_PROFIT:
                    ret_s1 = round(TAKE_PROFIT * 100, 2)
                elif i_day >= TIME_EXIT_DAYS:
                    ret_s1 = round(ret * 100, 2)
            
            # Strategy 3: Trailing stop
            if ret_s3 is None:
                best_close = max(best_close, day_close)
                ret_trail = (day_close - best_close) / best_close
                ret_abs = (day_close - ep) / ep
                if ret_trail <= STOP_LOSS:
                    ret_s3 = round(ret_abs * 100, 2)
                elif i_day >= TIME_EXIT_DAYS:
                    ret_s3 = round(ret_abs * 100, 2)
            
            # Hold-to-date (last day close)
            if i_day == remaining - 1:
                ret_hold = round((day_close - ep) / ep * 100, 2)
        
        # 12-month hold (use original entry price, apply xdxr separately)
        if remaining > HOLDING_12M:
            idx_12 = entry_idx + HOLDING_12M
            ep_12 = ep_orig
            for i_day in range(min(HOLDING_12M, remaining)):
                ds = str(df_stock.index[entry_idx + i_day])[:10]
                if ds in xm:
                    ep_12 *= 1.0 / (1.0 + xm[ds] / 10.0)
            close_12 = float(df_stock.iloc[min(idx_12, len(df_stock)-1)]['close'])
            ret_12 = round((close_12 - ep_12) / ep_12 * 100, 2)
        
        # If exited same day (no data after signal), fallback to hold
        if ret_s1 is None: ret_s1 = ret_hold
        if ret_s3 is None: ret_s3 = ret_hold
        if ret_hold is None:
            ret_hold = round((float(df_stock.iloc[entry_idx]['close']) - ep) / ep * 100, 2)
        
        # 5-year price position percentile
        signal_dt = pd.Timestamp(td)
        five_y_ago = signal_dt - pd.DateOffset(years=5)
        df_5y = df_stock[(df_stock.index >= five_y_ago) & (df_stock.index <= td)]
        pct_5y = None
        if len(df_5y) >= 60:
            closes_5y = df_5y['close'].astype(float)
            lo, hi = closes_5y.min(), closes_5y.max()
            if hi > lo:
                pct_5y = round((closes_5y.iloc[-1] - lo) / (hi - lo) * 100, 1)
        
        # 5年分位过滤: 仅保留0-40%
        if pct_5y is None or pct_5y >= 40:
            continue
        
        results.append({
            'code': row['symbol'],
            'date': td,
            'rps': round(total, 2),
            'ret_s1': ret_s1,
            'ret_s3': ret_s3,
            'ret_hold': ret_hold,
            'ret_12': ret_12,
            'pct_5y': pct_5y,
        })
        signals_total += 1
        last_signal[key] = td  # Rule 2
    
    prev_day_rps = today_rps

print(f"\n  {signals_total} signals generated, {len(results)} complete", file=sys.stderr)

# ── Output ──
print()
print("=" * 130)
print("  RPS首次策略 — 2024至今月度回测 (RPS上穿360 + 趋势多/强多 + 短趋势多/强多 + 距MA10<10% + 收盘10日最高)")
print(f"  信号区间: {target_days[0]} ~ {target_days[-1]}")
print("=" * 130)

# Monthly aggregation
by_month = defaultdict(list)
for r in results:
    by_month[r['date'][:7]].append(r)

print(f"\n  {'买入月份':<10} {'信号':>4} {'方案1(固止)':>10} {'方案3(移动)':>10} {'持有至今':>10} {'S1胜率':>7} {'S3胜率':>7}")
print(f"  {'─'*65}")

all_s1 = []; all_s3 = []; all_hold = []

for month in sorted(by_month.keys()):
    mr = by_month[month]
    n = len(mr)
    
    rs1 = [s['ret_s1'] for s in mr if s['ret_s1'] is not None]
    rs3 = [s['ret_s3'] for s in mr if s['ret_s3'] is not None]
    rh = [s['ret_hold'] for s in mr if s['ret_hold'] is not None]
    
    as1 = f"{sum(rs1)/len(rs1):+6.1f}%" if rs1 else "    N/A"
    as3 = f"{sum(rs3)/len(rs3):+6.1f}%" if rs3 else "    N/A"
    ah = f"{sum(rh)/len(rh):+6.1f}%" if rh else "    N/A"
    ws1 = f"{sum(1 for x in rs1 if x>0)/len(rs1)*100:>3.0f}%" if rs1 else "   —"
    ws3 = f"{sum(1 for x in rs3 if x>0)/len(rs3)*100:>3.0f}%" if rs3 else "   —"
    
    if n > 0:
        print(f"  {month:<10} {n:>4} {as1:>10} {as3:>10} {ah:>10} {ws1:>7} {ws3:>7}")
    
    all_s1.extend(rs1); all_s3.extend(rs3); all_hold.extend(rh)

as1 = f"{sum(all_s1)/len(all_s1):+6.1f}%" if all_s1 else "N/A"
as3 = f"{sum(all_s3)/len(all_s3):+6.1f}%" if all_s3 else "N/A"
ah = f"{sum(all_hold)/len(all_hold):+6.1f}%" if all_hold else "N/A"
ws1 = f"{sum(1 for x in all_s1 if x>0)/len(all_s1)*100:>3.0f}%" if all_s1 else ""
print(f"  {'─'*65}")
print(f"  {'合计':<10} {len(results):>4} {as1:>10} {as3:>10} {ah:>10} {ws1:>7}")

print(f"\n  注: 方案1=固定止盈+30%/-15%止损/6月退出; 方案3=移动止损-15%/6月退出。RPS≥{RPS_MIN}, 5年分位0-40%, xdxr已调整。持有至今=持有到{all_td[-1]}。")

# ── 5-year percentile distribution ──
pct_data = [r['pct_5y'] for r in results if r['pct_5y'] is not None]
if pct_data:
    buckets = [(0,20),(20,40)]
    print(f"\n  5年价格分位分布 ({len(pct_data)}/{len(results)} 信号):")
    print(f"  {'分位区间':<12} {'信号':>6} {'方案1均':>10} {'方案3均':>10} {'持有至今':>10}")
    print(f"  {'─'*50}")
    for lo, hi in buckets:
        in_range = [r for r in results if r['pct_5y'] is not None and lo <= r['pct_5y'] < hi]
        n = len(in_range)
        rs1 = [r['ret_s1'] for r in in_range if r['ret_s1'] is not None]
        rs3 = [r['ret_s3'] for r in in_range if r['ret_s3'] is not None]
        rh = [r['ret_hold'] for r in in_range if r['ret_hold'] is not None]
        as1 = f"{sum(rs1)/len(rs1):+6.1f}%" if rs1 else "    N/A"
        as3 = f"{sum(rs3)/len(rs3):+6.1f}%" if rs3 else "    N/A"
        ah = f"{sum(rh)/len(rh):+6.1f}%" if rh else "    N/A"
        print(f"  {lo:>2}%-{hi:>2}%       {n:>6} {as1:>10} {as3:>10} {ah:>10}")
