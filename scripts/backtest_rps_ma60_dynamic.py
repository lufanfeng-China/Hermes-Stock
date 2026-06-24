#!/usr/bin/env python3
"""
RPS首次策略 — MA60 动态退出/再入场 vs 纯持有24月 对比回测
"""
import sys, json, resource
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# ── 内存保护 ──
try:
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 8 * 1024**3))
except Exception as e:
    print(f"  [warn] Could not set memory limit: {e}", file=sys.stderr)

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING_24M = 500  # trading days
MA_PERIOD = 60
BELOW_DAYS = 3     # consecutive days below MA60 to trigger exit

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

# ── Load RPS history ──
print("Loading RPS history (Parquet)...", file=sys.stderr)
rps_path = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"
df = pd.read_parquet(rps_path)
df['rps_total'] = df['rps_20'] + df['rps_50'] + df['rps_120'] + df['rps_250']
print(f"  {len(df):,} rows, {df['trading_day'].nunique()} trading days", file=sys.stderr)

all_td = sorted(df['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}

target_days = [d for d in all_td if d.startswith('2022-')]
print(f"  2022 (Aug-Dec): {len(target_days)} trading days", file=sys.stderr)

# Build rps_by_day for target + prev day
need_days = set(target_days)
for td in target_days:
    idx = td_to_idx[td]
    if idx > 0:
        need_days.add(all_td[idx-1])

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

# RPS>360 ever cache
print("Building RPS>360 first-occurrence index...", file=sys.stderr)
df_360 = df[df['rps_total'] > 360]
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
            daily = reader.daily(symbol=code)
        except: continue
        if daily is None or daily.empty: continue
        daily = daily.sort_index()
        closes = daily['close'].astype(float).tolist()
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
        d = reader.daily(f"{m}{c}")
        if d is not None and not d.empty: daily[f"{m}{c}"] = d.sort_index()
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

# ── Simulate both strategies ──
print("Simulating MA60 dynamic vs pure hold...", file=sys.stderr)

def compute_ma(closes, period):
    """Return list of MAs, same length as closes (None where insufficient data)."""
    mas = [None] * len(closes)
    for i in range(period-1, len(closes)):
        mas[i] = sum(closes[i-period+1:i+1]) / period
    return mas

results = []

for s in signals:
    key = f"{s['market']}{s['code']}"
    df_stock = daily.get(key)
    if df_stock is None: continue

    # Find entry date (next trading day after signal)
    if s['date'] not in df_stock.index:
        m = df_stock.index >= s['date']
        if m.sum() == 0: continue
        entry_idx = df_stock.index.get_loc(df_stock.index[m][0])
    else:
        idx = df_stock.index.get_loc(s['date'])
        entry_idx = idx + 1 if idx + 1 < len(df_stock) else idx

    if entry_idx + HOLDING_24M >= len(df_stock): continue

    # Extract window: from 60 days before entry to 500 days after
    window_start = max(0, entry_idx - MA_PERIOD)
    window_end = min(len(df_stock), entry_idx + HOLDING_24M + 1)
    w = df_stock.iloc[window_start:window_end]
    
    closes_raw = w['close'].astype(float).tolist()
    opens_raw = w['open'].astype(float).tolist()
    dates = w.index.strftime('%Y-%m-%d').tolist()

    # Entry position within window
    rel_entry = entry_idx - window_start
    
    # xdxr adjustment: build an adjustment factor for closes
    xm = xdxr_cache.get(key, {})
    xdxr_factor = 1.0
    xdxr_factors = [1.0] * len(closes_raw)
    for i in range(len(closes_raw)):
        ds = dates[i]
        if ds in xm:
            xdxr_factor *= 1.0 / (1.0 + xm[ds] / 10.0)
        xdxr_factors[i] = xdxr_factor

    # Adjust closes for xdxr (for MA calculation)
    closes_adj = [c * f for c, f in zip(closes_raw, xdxr_factors)]

    # Compute MA60 on adjusted closes
    ma60 = compute_ma(closes_adj, MA_PERIOD)

    # ── Strategy A: Pure hold 24M ──
    ep_hold = opens_raw[rel_entry]  # entry at open
    if ep_hold <= 0: continue
    
    # Adjust entry price for xdxr over holding period
    hold_factor = xdxr_factors[rel_entry]
    exit24_idx = rel_entry + HOLDING_24M
    exit24_idx = min(exit24_idx, len(closes_raw) - 1)
    
    ep_hold_adj = ep_hold * hold_factor
    exit_factor = xdxr_factors[exit24_idx]
    
    if exit24_idx + 1 < len(opens_raw):
        exit_px = opens_raw[exit24_idx + 1]
        exit_val = exit_px * exit_factor
    else:
        exit_val = closes_raw[-1] * xdxr_factors[-1]
    
    ret_hold = round((exit_val - ep_hold_adj) / ep_hold_adj * 100, 2) if ep_hold_adj > 0 else None
    # Also 12-month
    exit12_idx = min(rel_entry + 250, len(closes_raw) - 1)
    if exit12_idx + 1 < len(opens_raw):
        ep12 = ep_hold * hold_factor
        exit12_val = opens_raw[exit12_idx + 1] * xdxr_factors[exit12_idx + 1]
        ret_hold_12 = round((exit12_val - ep12) / ep12 * 100, 2) if ep12 > 0 else None
    else:
        ret_hold_12 = None

    # ── Strategy B: MA60 dynamic exit/re-entry ──
    in_position = False
    below_count = 0
    entry_val = 0.0       # xdxr-adjusted entry value
    cumulative_mult = 1.0 # cumulative return multiplier
    round_trips = []
    current_entry_idx = 0
    
    # Start: enter at signal's next day open
    in_position = True
    entry_val = opens_raw[rel_entry] * xdxr_factors[rel_entry]
    current_entry_idx = rel_entry
    
    i = rel_entry  # Start from entry day
    
    while i < len(closes_raw):
        close_adj = closes_adj[i]
        open_price = opens_raw[i]
        ma_val = ma60[i]
        
        if in_position:
            if ma_val is not None and close_adj < ma_val:
                below_count += 1
                if below_count >= BELOW_DAYS:
                    # Exit next day open
                    exit_day = i + 1
                    if exit_day < len(opens_raw):
                        exit_val = opens_raw[exit_day] * xdxr_factors[exit_day]
                        rt_ret = (exit_val - entry_val) / entry_val if entry_val > 0 else 0
                        round_trips.append(rt_ret)
                        cumulative_mult *= (1 + rt_ret)
                        in_position = False
                        below_count = 0
                        i = exit_day  # Jump to exit day
                        continue
                    else:
                        # Can't exit, just break
                        break
            else:
                below_count = 0
        else:
            # Check re-entry: close > MA60
            if ma_val is not None and close_adj > ma_val:
                # Re-enter next day open
                re_entry_day = i + 1
                if re_entry_day < len(opens_raw):
                    # Don't re-enter beyond holding period
                    if re_entry_day > rel_entry + HOLDING_24M:
                        # Close to end of window, just stay out
                        break
                    entry_val = opens_raw[re_entry_day] * xdxr_factors[re_entry_day]
                    current_entry_idx = re_entry_day
                    in_position = True
                    below_count = 0
                    i = re_entry_day
                    continue
        
        i += 1
    
    # If still in position at end, close at last available close
    if in_position:
        final_close = closes_raw[-1] * xdxr_factors[-1]
        rt_ret = (final_close - entry_val) / entry_val if entry_val > 0 else 0
        round_trips.append(rt_ret)
        cumulative_mult *= (1 + rt_ret)
    
    ret_ma60 = round((cumulative_mult - 1) * 100, 2)
    n_trips = len(round_trips)
    
    results.append({
        'code': s['code'],
        'date': s['date'],
        'rps': s['rps_total'],
        'ret_hold_12': ret_hold_12,
        'ret_hold_24': ret_hold,
        'ret_ma60': ret_ma60,
        'trips': n_trips,
        'trip_details': [round(r*100, 2) for r in round_trips],
    })

# ── Output ──
print()
print("=" * 110)
print("  RPS首次策略 — MA60动态退出/再入场 vs 纯持有24月")
print("  规则: 跌破MA60连续3日→次日开盘清仓 | 重新站上MA60→次日开盘买回 | 24月内循环")
print("=" * 110)

by_month = defaultdict(list)
for r in results:
    by_month[r['date'][:7]].append(r)

all_hold_12 = []; all_hold_24 = []; all_ma60 = []

print(f"\n  {'买入月份':<10} {'笔数':>4} {'纯持有12月':>10} {'纯持有24月':>10} {'MA60循环':>10} {'循环次数':>8}")
print(f"  {'─'*60}")

for m in sorted(by_month.keys()):
    mr = by_month[m]
    n = len(mr)
    
    r12 = [r['ret_hold_12'] for r in mr if r['ret_hold_12'] is not None]
    r24 = [r['ret_hold_24'] for r in mr if r['ret_hold_24'] is not None]
    rm60 = [r['ret_ma60'] for r in mr if r['ret_ma60'] is not None]
    
    a12 = f"{sum(r12)/len(r12):+.1f}%" if r12 else "N/A"
    a24 = f"{sum(r24)/len(r24):+.1f}%" if r24 else "N/A"
    am60 = f"{sum(rm60)/len(rm60):+.1f}%" if rm60 else "N/A"
    avg_trips = f"{sum(r['trips'] for r in mr)/n:.1f}" if n > 0 else "N/A"
    
    print(f"  {m:<10} {n:>4} {a12:>10} {a24:>10} {am60:>10} {avg_trips:>8}")
    
    all_hold_12.extend(r12)
    all_hold_24.extend(r24)
    all_ma60.extend(rm60)

print(f"  {'─'*60}")

if all_hold_12:
    a12 = sum(all_hold_12)/len(all_hold_12)
    wr12 = sum(1 for r in all_hold_12 if r>0)/len(all_hold_12)*100
    print(f"  {'合计12月':<10} {len(all_hold_12):>4} {a12:>+9.1f}% {'':>10} {'':>10}  (胜率{wr12:.0f}%)")

if all_hold_24:
    a24 = sum(all_hold_24)/len(all_hold_24)
    wr24 = sum(1 for r in all_hold_24 if r>0)/len(all_hold_24)*100
    print(f"  {'合计24月':<10} {len(all_hold_24):>4} {'':>10} {a24:>+9.1f}% {'':>10}  (胜率{wr24:.0f}%)")

if all_ma60:
    a_ma60 = sum(all_ma60)/len(all_ma60)
    wr_ma60 = sum(1 for r in all_ma60 if r>0)/len(all_ma60)*100
    total_trips = sum(r['trips'] for r in results)
    print(f"  {'MA60循环':<10} {len(all_ma60):>4} {'':>10} {'':>10} {a_ma60:>+9.1f}%  (胜率{wr_ma60:.0f}%, 共{total_trips}次)")
    print(f"  {'':>10}     {'':>10} {'':>10} {'平均每笔':>10} {total_trips/len(all_ma60):.1f}次循环" if all_ma60 else "")

# ── Distribution comparison ──
print(f"\n  {'─'*60}")
print(f"  收益分布对比:")
print(f"  {'区间':>12} {'纯持有24月':>15} {'MA60循环':>15}")
print(f"  {'─'*45}")

buckets = [(-100, -50), (-50, -25), (-25, -10), (-10, 0), (0, 10), (10, 25),
           (25, 50), (50, 100), (100, 200), (200, 9999)]

for lo, hi in buckets:
    ch = sum(1 for r in all_hold_24 if lo <= r < hi)
    cm = sum(1 for r in all_ma60 if lo <= r < hi)
    ph = ch/len(all_hold_24)*100 if all_hold_24 else 0
    pm = cm/len(all_ma60)*100 if all_ma60 else 0
    bar_h = '█' * int(ph/2)
    bar_m = '█' * int(pm/2)
    rng = f"{lo:+d}~{hi:+d}" if hi < 9999 else f">{lo:+d}"
    print(f"  {rng:>12} {ph:>4.0f}% {bar_h:<10} {pm:>4.0f}% {bar_m}")

# ── Detail: signals with most trips ──
if results:
    sorted_by_trips = sorted(results, key=lambda r: r['trips'], reverse=True)
    print(f"\n  {'─'*60}")
    print(f"  循环次数最多的信号 (top 5):")
    for r in sorted_by_trips[:5]:
        if r['trips'] == 0: break
        trips_str = ' → '.join(f"{t:+.1f}%" for t in r['trip_details'])
        print(f"  {r['code']} {r['date']} RPS{r['rps']}: "
              f"纯持24月 {r['ret_hold_24']:+.1f}% | MA60循环 {r['ret_ma60']:+.1f}% "
              f"({r['trips']}次: {trips_str})")
