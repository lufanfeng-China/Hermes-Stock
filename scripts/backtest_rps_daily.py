#!/usr/bin/env python3
"""RPS首次 — 指定月份逐日回测 (RPS≥360, 现场趋势, 60日去重) + 持有收益
Usage: 修改下方 MONTH_START / MONTH_END 指定月份
       ~/.venvs/moontdx-china-stock-data/bin/python scripts/backtest_rps_daily.py
"""
import sys
sys.path.insert(0, '/home/lufanfeng/Project-Hermes-Stock')

import pandas as pd
from pathlib import Path

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'
PARQUET_PATH = PROJECT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"

from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

RPS_MIN = 360
MONTH_START = '2026-06-01'
MONTH_END = '2026-06-30'

# ── Load RPS ──
print("Loading RPS...", flush=True)
df_full = pd.read_parquet(PARQUET_PATH)
df_full['rps_total'] = df_full['rps_20'] + df_full['rps_50'] + df_full['rps_120'] + df_full['rps_250']
all_td = sorted(df_full['trading_day'].unique())
td_to_idx = {td: i for i, td in enumerate(all_td)}
last_td = all_td[-1]
print(f"RPS 最新日: {last_td}", flush=True)

mask = (df_full['trading_day'] >= MONTH_START) & (df_full['trading_day'] <= MONTH_END)
df_target = df_full[mask].copy()
target_days = sorted(df_target['trading_day'].unique())
print(f"目标: {target_days[0]} ~ {target_days[-1]} ({len(target_days)} 天)\n", flush=True)

# RPS>RPS_MIN index for dedup
df_gt = df_full[df_full['rps_total'] > RPS_MIN]
rps_ever = {}
for (m, s), g in df_gt.groupby(['market', 'symbol'], sort=False):
    rps_ever[(m, s)] = g['trading_day'].min()

# ── Vectorized trend helpers ──
def trend_check(closes):
    n = len(closes)
    if n < 120: return False
    ma20 = closes.rolling(20).mean(); ma50 = closes.rolling(50).mean()
    ma120 = closes.rolling(120).mean(); ma250 = closes.rolling(250).mean()
    m20, m50, m120, m250 = ma20.iloc[-1], ma50.iloc[-1], ma120.iloc[-1], ma250.iloc[-1]
    if pd.isna(m250): return False
    return m20 > m50 > m120 > m250

def short_trend_check(closes):
    n = len(closes)
    if n < 60: return False
    ma10 = closes.rolling(10).mean(); ma20 = closes.rolling(20).mean()
    ma30 = closes.rolling(30).mean(); ma60 = closes.rolling(60).mean()
    m10, m20, m30, m60 = ma10.iloc[-1], ma20.iloc[-1], ma30.iloc[-1], ma60.iloc[-1]
    if pd.isna(m60): return False
    return m10 > m20 > m30 > m60

# ── Day by day signal detection ──
print(f"{'日期':<12} {'RPS>'+str(RPS_MIN):>8} {'入围':>6}")
print("-" * 42)

prev_day_rps = {}
daily_cache = {}
signals = []  # (signal_date, market, symbol, rps_total, close)
tot_c = 0; tot_p = 0

for td in target_days:
    day_df = df_target[df_target['trading_day'] == td]
    today_rps = {}
    candidates = 0; passed = 0
    
    for _, row in day_df.iterrows():
        m = row['market']; s = row['symbol']
        total = float(row['rps_total'])
        today_rps[(m, s)] = total
        
        if total < RPS_MIN: continue
        candidates += 1
        
        # 60d dedup
        ever_date = rps_ever.get((m, s))
        if ever_date and ever_date < td:
            ever_idx = td_to_idx.get(ever_date, -1)
            td_idx_curr = td_to_idx[td]
            if ever_idx >= 0 and (td_idx_curr - ever_idx) <= 60: continue
        
        # Yesterday <= RPS_MIN
        prev = prev_day_rps.get((m, s))
        if prev is not None and prev > RPS_MIN: continue
        
        # Daily data (on-demand + cache)
        sk = f"{m}{s}"
        if sk not in daily_cache:
            try:
                d = reader.daily(symbol=s)
            except:
                daily_cache[sk] = None; continue
            if d is None or d.empty:
                daily_cache[sk] = None; continue
            d = d.sort_index()
            d = d[d.index <= td]
            daily_cache[sk] = d
        
        daily = daily_cache[sk]
        if daily is None or daily.empty: continue
        closes = daily['close'].astype(float)
        if len(closes) < 120: continue
        
        if not trend_check(closes): continue
        if not short_trend_check(closes): continue
        
        close_t = closes.iloc[-1]
        ma10 = closes.iloc[-10:].mean()
        if abs(close_t - ma10) / ma10 * 100 >= 10: continue
        if close_t < closes.iloc[-10:].max() - 1e-9: continue
        
        passed += 1
        signals.append((td, m, s, total, close_t))
    
    prev_day_rps = today_rps
    tot_c += candidates; tot_p += passed
    if candidates > 0:
        print(f"{td:<12} {candidates:>8} {passed:>6}")

print("-" * 42)
print(f"{'合计':<12} {tot_c:>8} {tot_p:>6}")

# ── Phase 2: Calculate returns ──
if signals:
    print(f"\n{'='*74}")
    print(f"信号明细 + 持有至 {last_td} 收益（T+1开盘价买入）")
    print(f"{'='*74}")
    print(f"{'信号日':<12} {'代码':<10} {'RPS总分':>7} {'收盘':>8} {'T+1买价':>9} {'现价':>8} {'收益%':>8}")
    print("-" * 74)
    
    rets = []
    # Clear caches for full data fetch
    full_cache = {}
    
    for sig_date, m, s, rps_total, close_sig in signals:
        # Get T+1 open price
        sk = f"{m}{s}"
        if sk not in full_cache:
            try:
                d = reader.daily(symbol=s)
                if d is not None and not d.empty:
                    d = d.sort_index()
                    full_cache[sk] = d
                else:
                    full_cache[sk] = None
            except:
                full_cache[sk] = None
        
        daily = full_cache[sk]
        if daily is None or daily.empty:
            continue
        
        # Find T+1 row
        mask_next = daily.index > sig_date
        if not mask_next.any():
            continue
        next_row = daily[mask_next].iloc[0]
        buy_price = float(next_row['open'])
        
        # Latest close
        latest_close = float(daily['close'].iloc[-1])
        
        ret = (latest_close - buy_price) / buy_price * 100
        
        code = f"{m}.{s}"
        if m == 0:
            code = f"sz.{s}"
        elif m == 1:
            code = f"sh.{s}"
        
        print(f"{str(sig_date)[:10]:<12} {code:<10} {rps_total:>7.0f} {close_sig:>8.2f} {buy_price:>9.2f} {latest_close:>8.2f} {ret:>7.1f}%")
        rets.append(ret)
    
    print("-" * 74)
    if rets:
        pos = sum(1 for r in rets if r > 0)
        neg = sum(1 for r in rets if r < 0)
        zero = len(rets) - pos - neg
        avg_ret = sum(rets)/len(rets)
        print(f"{'汇总':<12} {'':10} {'':>7} {'':>8} {'':>9} {'':>8} {avg_ret:>7.1f}%")
        print(f"  胜率: {pos}/{len(rets)} ({pos/len(rets)*100:.0f}%)  盈利: {pos}  亏损: {neg}  平: {zero}")
    else:
        print("  所有信号均无法获取 T+1 数据（可能信号日是最后交易日）")

print(f"\nRPS≥{RPS_MIN} | 60日去重 | 趋势多头 | 短趋势多头 | 距MA10<10% | 10日最高")
