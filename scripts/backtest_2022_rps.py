#!/usr/bin/env python3
"""
RPS首次策略 — 2022年全年回测 (8-12月，数据从2022-08-12起)
24月持有，验证熊市→牛市周期表现
"""
import sys, json, resource
import pandas as pd
from pathlib import Path
from collections import defaultdict

# ── 内存保护：超 6GB 时 Python 自报 MemoryError，不会被 WSL OOM Killer 杀死 ──
try:
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 8 * 1024**3))
except Exception as e:
    print(f"  [warn] Could not set memory limit: {e}", file=sys.stderr)

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/home/lufanfeng/tdx_data'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING_24M = 500

# ── Trend helpers ──
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

# ── Load RPS history (Parquet: 38MB, ~300MB in memory) ──
print("Loading RPS history (Parquet)...", file=sys.stderr)
rps_path = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"
df = pd.read_parquet(rps_path)
# Compute RPS total for threshold filtering
df['rps_total'] = df['rps_20'] + df['rps_50'] + df['rps_120'] + df['rps_250']
print(f"  {len(df):,} rows, {df['trading_day'].nunique()} trading days", file=sys.stderr)

# Trading day index
all_td = sorted(df['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}

target_days = [d for d in all_td if d.startswith('2022-')]
print(f"  2022 (Aug-Dec): {len(target_days)} trading days", file=sys.stderr)

# ── Build rps_by_day only for needed days (target + their previous day) ──
need_days = set(target_days)
for td in target_days:
    idx = td_to_idx[td]
    if idx > 0:
        need_days.add(all_td[idx - 1])  # need prev day's RPS for the "yesterday ≤360" check

df_need = df[df['trading_day'].isin(need_days)]
rps_by_day = {}
for td, group in df_need.groupby('trading_day'):
    day_dict = {}
    for _, row in group.iterrows():
        key = (row['market'], row['symbol'])
        day_dict[key] = {
            'rps_20': row['rps_20'], 'rps_50': row['rps_50'],
            'rps_120': row['rps_120'], 'rps_250': row['rps_250'],
        }
    rps_by_day[td] = day_dict

# ── Build RPS>360 ever cache ──
print("Building RPS>360 first-occurrence index...", file=sys.stderr)
df_360 = df[df['rps_total'] > 360]
# First trading day each stock ever crossed RPS>360
rps360_ever = {}
for (market, symbol), group in df_360.groupby(['market', 'symbol']):
    rps360_ever[(market, symbol)] = group['trading_day'].min()
print(f"  {len(rps360_ever):,} stocks ever hit RPS>360", file=sys.stderr)

# ── Generate signals ──
print("Generating signals...", file=sys.stderr)
signals = []

for td in target_days:
    entries = rps_by_day.get(td, {})
    for (market, code), rps in entries.items():
        r20=rps.get('rps_20'); r50=rps.get('rps_50')
        r120=rps.get('rps_120'); r250=rps.get('rps_250')
        if any(v is None for v in (r20,r50,r120,r250)): continue
        total = r20+r50+r120+r250
        if total < RPS_MIN: continue
        
        # First in 60d
        ever_date = rps360_ever.get((market, code))
        if ever_date and ever_date < td:
            ever_idx = td_to_idx.get(ever_date, -1)
            td_idx = td_to_idx[td]
            if ever_idx >= 0 and (td_idx - ever_idx) <= 60: continue
        
        # Yesterday RPS <= 360
        td_idx = td_to_idx[td]
        if td_idx > 0:
            prev_td = all_td[td_idx-1]
            prev = rps_by_day[prev_td].get((market, code), {})
            p20=prev.get('rps_20'); p50=prev.get('rps_50')
            p120=prev.get('rps_120'); p250=prev.get('rps_250')
            if all(v is not None for v in (p20,p50,p120,p250)):
                if p20+p50+p120+p250 > 360: continue
        
        try:
            df = reader.daily(symbol=code)
        except: continue
        if df is None or df.empty: continue
        df = df.sort_index()
        closes = df['close'].astype(float).tolist()
        if len(closes) < 60: continue
        
        trend = classify_trend(closes)
        if trend not in ("bullish", "strong_bullish"): continue
        short_trend = classify_short_trend(closes)
        if short_trend not in ("bullish", "strong_bullish"): continue
        
        close_t = closes[-1]
        ma10 = sum(closes[max(0,len(closes)-10):]) / 10
        if abs(close_t - ma10) / ma10 * 100 >= 10: continue
        if close_t < max(closes[max(0,len(closes)-10):]) - 1e-9: continue
        
        signals.append({'code': code, 'market': market, 'date': td, 'rps_total': round(total, 2)})

print(f"  {len(signals)} signals", file=sys.stderr)

# ── Fetch daily + xdxr ──
unique = set((s['market'],s['code']) for s in signals)
print(f"Fetching data for {len(unique)} stocks...", file=sys.stderr)
daily = {}
for i, (m, c) in enumerate(unique):
    if (i+1) % 50 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
    try:
        df = reader.daily(f"{m}{c}")
        if df is not None and not df.empty: daily[f"{m}{c}"] = df.sort_index()
    except: pass
xdxr_cache = {}
for m, c in unique:
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

# ── Simulate 24M ──
print("Simulating 24M...", file=sys.stderr)
results = []
for s in signals:
    df = daily.get(f"{s['market']}{s['code']}")
    if df is None: continue
    if s['date'] not in df.index:
        m = df.index >= s['date']
        if m.sum() == 0: continue
        entry_date = df.index[m][0]
    else:
        idx = df.index.get_loc(s['date'])
        entry_date = df.index[idx+1] if idx+1 < len(df) else df.index[idx]
    
    m2 = df.index >= entry_date
    if m2.sum() < HOLDING_24M + 1: continue
    w = df.loc[m2]
    ep = w.iloc[0]['open']
    if ep <= 0: continue
    
    xm = xdxr_cache.get(f"{s['market']}{s['code']}", {})
    ep_adj = ep
    for i_day in range(min(HOLDING_24M, len(w))):
        ds = str(w.index[i_day])[:10]
        if ds in xm: ep_adj *= 1.0/(1.0+xm[ds]/10.0)
    
    exit_day = HOLDING_24M
    exit_px = w.iloc[exit_day+1]['open'] if exit_day+1 < len(w) else w.iloc[exit_day]['close']
    ret_24 = round((exit_px - ep_adj) / ep_adj * 100, 2) if ep_adj > 0 else None
    if ret_24 is None: continue
    
    # 12M too
    ep12 = ep
    for i_day in range(min(250, len(w))):
        ds = str(w.index[i_day])[:10]
        if ds in xm: ep12 *= 1.0/(1.0+xm[ds]/10.0)
    exit12 = w.iloc[251]['open'] if 251 < len(w) else w.iloc[250]['close']
    ret_12 = round((exit12 - ep12) / ep12 * 100, 2) if ep12 > 0 else None
    
    results.append({'code':s['code'],'date':s['date'],'rps':s['rps_total'],
                    'ret_12':ret_12,'ret_24':ret_24})

# ── Output ──
print()
print("=" * 90)
print("  RPS首次策略 — 2022年全年回测 (RPS≥360, 24月持有)")
print("=" * 90)

by_month = defaultdict(list)
for r in results: by_month[r['date'][:7]].append(r)

all_rets_12 = []; all_rets_24 = []
for m in sorted(by_month.keys()):
    mr = by_month[m]
    r12 = [r['ret_12'] for r in mr if r['ret_12'] is not None]
    r24 = [r['ret_24'] for r in mr if r['ret_24'] is not None]
    n = len(mr)
    a12 = f"{sum(r12)/len(r12):+.1f}%" if r12 else "N/A"
    a24 = f"{sum(r24)/len(r24):+.1f}%" if r24 else "N/A"
    wr12 = f"{sum(1 for r in r12 if r>0)/len(r12)*100:.0f}%" if r12 else ""
    wr24 = f"{sum(1 for r in r24 if r>0)/len(r24)*100:.0f}%" if r24 else ""
    print(f"  {m} | {n:>3}笔 | 12月 {a12:>8} ({wr12}) | 24月 {a24:>8} ({wr24})")
    all_rets_12.extend(r12); all_rets_24.extend(r24)

print(f"\n  {'─'*90}")
if all_rets_12:
    a12 = sum(all_rets_12)/len(all_rets_12)
    wr12 = sum(1 for r in all_rets_12 if r>0)/len(all_rets_12)*100
    print(f"  合计12月: {len(all_rets_12)}笔 | 均{a12:+.1f}% | 胜{wr12:.0f}%")
if all_rets_24:
    a24 = sum(all_rets_24)/len(all_rets_24)
    wr24 = sum(1 for r in all_rets_24 if r>0)/len(all_rets_24)*100
    print(f"  合计24月: {len(all_rets_24)}笔 | 均{a24:+.1f}% | 胜{wr24:.0f}%")

# Context: what market did these signals see?
print(f"\n  市场背景:")
print(f"    2022-08~12: A股熊市底部（数据从2022-08-12开始）")
print(f"    持有12月 → 覆盖到2023年（熊市持续）")
print(f"    持有24月 → 覆盖到2024年底（牛市已来）")
