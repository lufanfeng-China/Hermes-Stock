#!/usr/bin/env python3
"""
提取每笔交易的完整形态特征：拉升幅度、回调深度、突破力度、量能等
对比正收益 vs 负收益的形态差异
"""

import json, time, os
import numpy as np
import pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"

def get_symbols():
    with open("/tmp/csi300_constituents.json") as f:
        return sorted(set(str(c) for c in json.load(f)))

def extract_features(reader, code):
    """提取每笔信号的完整特征"""
    try:
        df = reader.daily(code)
        if df is None or len(df) < 80: return []
    except: return []
    df = df.sort_index()
    df = df[df.index >= "2016-01-01"]
    n = len(df)
    if n < 80: return []
    
    c = df["close"].values.astype(np.float64)
    o = df["open"].values.astype(np.float64)
    h = df["high"].values.astype(np.float64)
    l = df["low"].values.astype(np.float64)
    v = df["volume"].values.astype(np.float64)
    dates = df.index
    
    vol_ma50 = np.full(n, np.nan)
    for i in range(49, n): vol_ma50[i] = np.mean(v[i-49:i+1])
    day_rets = np.zeros(n)
    day_rets[1:] = (c[1:] - c[:-1]) / c[:-1]
    surge_rets = np.full(n, np.nan)
    for i in range(4, n): surge_rets[i] = (c[i] - o[i-4]) / o[i-4]
    
    trades = []
    for today in range(70, n):
        for surge_end in range(today - 9, today - 5):
            if surge_end < 50 or today - surge_end > 20: continue
            surge_start = surge_end - 4
            if surge_start < 50: continue
            
            sret = surge_rets[surge_end]
            if np.isnan(sret) or sret <= 0.20: continue
            
            ma50 = vol_ma50[surge_start]
            if np.isnan(ma50): continue
            
            vol_ok = True
            vol_up_count = 0; vol_dn_count = 0
            for j in range(surge_start, surge_end+1):
                if c[j] > o[j]:
                    vol_up_count += 1
                    if v[j] <= 1.5*ma50: vol_ok = False; break
                else:
                    vol_dn_count += 1
                    if v[j] <= 0.8*ma50: vol_ok = False; break
            if not vol_ok: continue
            
            surge_high = -1.0; surge_high_day_ret = 0
            for j in range(surge_start, surge_end+1):
                if day_rets[j] > 0.05 and c[j] > surge_high:
                    surge_high = c[j]; surge_high_day_ret = day_rets[j]
            if surge_high < 0: continue
            
            # Pullback
            max_allowed = surge_high * 1.05
            pb_low = 1e9; pb_low_idx = -1; cancelled = False
            for j in range(surge_end+1, today):
                if c[j] > max_allowed: cancelled = True; break
                if c[j] < pb_low: pb_low = c[j]; pb_low_idx = j
            if cancelled or pb_low_idx < 0: continue
            if pb_low_idx - surge_end < 5: continue
            if pb_low >= c[surge_end]: continue
            
            half_ret = o[surge_start] + (surge_high - o[surge_start]) * 0.5
            if pb_low < half_ret: continue
            
            if c[today] > surge_high and c[today-1] <= surge_high:
                # Simulate trade: 30-day hold
                buy_idx = today + 1
                hold_end = min(buy_idx + 30, n - 1)
                if hold_end <= buy_idx: continue
                
                bp = o[buy_idx]
                sell_p = c[hold_end]
                ret30 = (sell_p / bp - 1) * 100
                max_ret = (np.max(h[buy_idx:hold_end+1]) / bp - 1) * 100
                
                # Feature extraction
                surge_range = surge_high - o[surge_start]
                pb_pct = (surge_high - pb_low) / surge_range * 100
                pb_days = pb_low_idx - surge_end
                
                # Breakout strength
                breakout_pct = (c[today] - surge_high) / surge_high * 100
                
                # Pre-surge trend: 20d return before surge
                pre_surge_ret = (o[surge_start] - c[max(0,surge_start-20)]) / c[max(0,surge_start-20)] * 100 if surge_start >= 20 else 0
                
                # Volume intensity during surge
                surge_vol_ratio = np.mean(v[surge_start:surge_end+1]) / ma50
                
                # Max daily gain in surge
                max_daily = max(day_rets[surge_start:surge_end+1]) * 100
                
                # Pullback volume vs surge volume
                pb_vol = np.mean(v[surge_end+1:pb_low_idx+1]) if pb_low_idx > surge_end else 0
                pb_vol_ratio = pb_vol / np.mean(v[surge_start:surge_end+1]) if pb_low_idx > surge_end else 1
                
                # Days from surge_end to breakout
                days_to_breakout = today - surge_end
                
                # 10d, 20d returns too
                h10 = min(buy_idx+10, n-1)
                ret10 = (c[h10]/bp-1)*100
                h20 = min(buy_idx+20, n-1)
                ret20 = (c[h20]/bp-1)*100
                
                trades.append({
                    "code": code,
                    "date": str(dates[today].date()),
                    "ret10": round(ret10,2), "ret20": round(ret20,2), "ret30": round(ret30,2),
                    "max_ret": round(max_ret,2),
                    "surge_ret": round(sret*100,2),
                    "surge_range": round(surge_range,2),
                    "surge_high": round(surge_high,2),
                    "pb_pct": round(pb_pct,2),
                    "pb_days": pb_days,
                    "breakout_pct": round(breakout_pct,2),
                    "pre_surge_ret": round(pre_surge_ret,2),
                    "surge_vol_ratio": round(surge_vol_ratio,2),
                    "max_daily": round(max_daily,2),
                    "pb_vol_ratio": round(pb_vol_ratio,2),
                    "days_to_breakout": days_to_breakout,
                    "vol_up_count": vol_up_count,
                    "vol_dn_count": vol_dn_count,
                })
                break
    return trades

def main():
    symbols = get_symbols()
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    all_t = []
    for si, code in enumerate(symbols):
        trades = extract_features(reader, code)
        all_t.extend(trades)
        if (si+1) % 100 == 0:
            print(f"  {si+1}/300 | {len(all_t)} trades")
    
    print(f"\n总交易: {len(all_t)}")
    df = pd.DataFrame(all_t)
    
    # Split winners vs losers (by ret30)
    wins = df[df["ret30"] > 0]
    losses = df[df["ret30"] <= 0]
    
    print(f"正收益(V7 30天): {len(wins)}笔  负收益: {len(losses)}笔")
    
    # Feature comparison
    features = [
        ("surge_ret", "拉升幅度%"),
        ("pb_pct", "回调深度%"),
        ("pb_days", "回调天数"),
        ("breakout_pct", "突破力度%"),
        ("pre_surge_ret", "拉升前20日收益%"),
        ("surge_vol_ratio", "拉升量比(vs50日均)"),
        ("max_daily", "拉升最大单日涨幅%"),
        ("pb_vol_ratio", "回调量比(vs拉升量)"),
        ("days_to_breakout", "突破距拉升终点天数"),
        ("max_ret", "持有期最大收益%"),
    ]
    
    print(f"\n{'='*80}")
    print(f"{'特征':<22} {'正收益均值':>10} {'负收益均值':>10} {'差异':>10} {'方向'}")
    print(f"{'='*80}")
    
    for col, label in features:
        wm = wins[col].mean()
        lm = losses[col].mean()
        diff = wm - lm
        direction = "正>负 ✓" if diff > 0 else "负>正 ✗"
        print(f"{label:<22} {wm:>10.2f} {lm:>10.2f} {diff:>+10.2f} {direction}")
    
    # Percentile analysis for key features
    print(f"\n{'='*80}")
    print(f"分布分析 (正收益 vs 负收益)")
    print(f"{'='*80}")
    
    for col, label in features[:7]:
        print(f"\n  {label}:")
        qs = [0, 20, 40, 60, 80, 100]
        for q in qs:
            wq = np.percentile(wins[col], q)
            lq = np.percentile(losses[col], q)
            print(f"    P{q:>3}: 正{wq:>8.2f}  负{lq:>8.2f}")
    
    # Best discriminating features: combine top 2-3
    print(f"\n{'='*80}")
    print(f"组合过滤测试 (筛选正收益占比 > 60%)")
    print(f"{'='*80}")
    
    # Try various filters
    filters_to_try = [
        ("pb_pct < 40", lambda d: d["pb_pct"] < 40),
        ("pb_pct < 30", lambda d: d["pb_pct"] < 30),
        ("pb_pct < 25", lambda d: d["pb_pct"] < 25),
        ("pb_days <= 7", lambda d: d["pb_days"] <= 7),
        ("breakout_pct > 2", lambda d: d["breakout_pct"] > 2),
        ("breakout_pct > 3", lambda d: d["breakout_pct"] > 3),
        ("surge_vol_ratio > 2", lambda d: d["surge_vol_ratio"] > 2),
        ("pre_surge_ret < 0", lambda d: d["pre_surge_ret"] < 0),
        ("pb_pct < 30 & surge_vol_ratio > 2", 
         lambda d: (d["pb_pct"] < 30) & (d["surge_vol_ratio"] > 2)),
        ("pb_pct < 35 & breakout_pct > 2",
         lambda d: (d["pb_pct"] < 35) & (d["breakout_pct"] > 2)),
        ("pb_pct < 35 & surge_vol_ratio > 1.8",
         lambda d: (d["pb_pct"] < 35) & (d["surge_vol_ratio"] > 1.8)),
        ("pb_days <= 8 & surge_vol_ratio > 1.8",
         lambda d: (d["pb_days"] <= 8) & (d["surge_vol_ratio"] > 1.8)),
        ("pb_pct < 40 & pre_surge_ret < 5",
         lambda d: (d["pb_pct"] < 40) & (d["pre_surge_ret"] < 5)),
    ]
    
    baseline_winrate = len(wins) / len(df) * 100
    print(f"  基准胜率: {baseline_winrate:.1f}% ({len(wins)}/{len(df)}) | 均值: {df['ret30'].mean():+.2f}%")
    print()
    
    best = None
    for name, fn in filters_to_try:
        filtered = df[fn(df)]
        if len(filtered) < 10: continue
        w = (filtered["ret30"] > 0).sum()
        wr = w / len(filtered) * 100
        m = filtered["ret30"].mean()
        imp = wr - baseline_winrate
        marker = "★" if imp > 8 else ("✓" if imp > 3 else "")
        print(f"  {marker} {name}: {len(filtered):>2}笔 胜率{wr:.0f}% 均值{m:+.2f}% (胜率{imp:+.0f}pp)")
        if imp > 8 and (best is None or m > best[1]):
            best = (name, m, len(filtered), wr)
    
    if best:
        print(f"\n  最佳: {best[0]} → {best[2]}笔 胜率{best[3]:.0f}% 均值{best[1]:+.2f}%")

if __name__ == "__main__":
    main()
