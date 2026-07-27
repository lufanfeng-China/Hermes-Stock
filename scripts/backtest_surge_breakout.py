#!/usr/bin/env python3
"""
拉升+回调+突破 回测 — 多版本止损对比
V1: -5%硬止损  V2: -8%硬止损  V3: 跌破回调低点止损
"""

import json, time, os
import numpy as np
import pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"

def get_symbols():
    cache = "/tmp/csi300_constituents.json"
    if os.path.exists(cache):
        with open(cache) as f:
            return sorted(set(str(c) for c in json.load(f)))
    return None

def build_name_map():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")
    names = {}
    for mkt in [0, 1]:
        df = client.stocks(market=mkt)
        for _, row in df.iterrows():
            names[str(row["code"])] = str(row["name"]).strip().replace("\x00", "")
    return names

def find_signals_np(closes, opens, volumes, n):
    """numpy-based signal detection. Returns list of signal dicts."""
    vol_ma50 = np.full(n, np.nan)
    for i in range(49, n):
        vol_ma50[i] = np.mean(volumes[i-49:i+1])
    
    day_rets = np.zeros(n)
    day_rets[1:] = (closes[1:] - closes[:-1]) / closes[:-1]
    
    surge_rets = np.full(n, np.nan)
    for i in range(4, n):
        surge_rets[i] = (closes[i] - opens[i-4]) / opens[i-4]
    
    signals = []
    for today in range(70, n):
        for surge_end in range(today - 9, today - 5):
            if surge_end < 50 or today - surge_end > 20:
                continue
            surge_start = surge_end - 4
            if surge_start < 50:
                continue
            
            ret = surge_rets[surge_end]
            if np.isnan(ret) or ret <= 0.20:
                continue
            
            ma50 = vol_ma50[surge_start]
            if np.isnan(ma50):
                continue
            
            vol_ok = True
            for j in range(surge_start, surge_end + 1):
                if closes[j] > opens[j]:
                    if volumes[j] <= 1.5 * ma50:
                        vol_ok = False; break
                else:
                    if volumes[j] <= 0.8 * ma50:
                        vol_ok = False; break
            if not vol_ok:
                continue
            
            surge_high = -1.0
            for j in range(surge_start, surge_end + 1):
                if day_rets[j] > 0.05 and closes[j] > surge_high:
                    surge_high = closes[j]
            if surge_high < 0:
                continue
            
            max_allowed = surge_high * 1.05
            pullback_low = 1e9
            pullback_low_idx = -1
            cancelled = False
            for j in range(surge_end + 1, today):
                if closes[j] > max_allowed:
                    cancelled = True; break
                if closes[j] < pullback_low:
                    pullback_low = closes[j]
                    pullback_low_idx = j
            if cancelled or pullback_low_idx < 0:
                continue
            if pullback_low_idx - surge_end < 5:
                continue
            if pullback_low >= closes[surge_end]:
                continue
            half_ret = opens[surge_start] + (surge_high - opens[surge_start]) * 0.5
            if pullback_low < half_ret:
                continue
            if closes[today] > surge_high and closes[today-1] <= surge_high:
                signals.append({
                    "today": today,
                    "surge_high": surge_high,
                    "surge_open": opens[surge_start],
                    "pullback_low": pullback_low,
                })
                break
    return signals

def sim_trade_v1(closes, opens, highs, today):
    """V1: -5% 硬止损 (baseline)"""
    buy_idx = today + 1
    if buy_idx + 1 >= len(closes):
        return None
    bp = opens[buy_idx]
    highest = bp
    for i in range(buy_idx+1, min(buy_idx+11, len(closes))):
        c = closes[i]
        if c > highest: highest = c
        pnl = c/bp - 1
        if pnl <= -0.05:
            return ("止损", i-buy_idx, pnl, highest/bp-1)
        if i-buy_idx >= 10 and highest/bp-1 < 0.20:
            return ("到期", i-buy_idx, pnl, highest/bp-1)
        if highest/bp-1 >= 0.20 and c <= highest*0.90:
            return ("止盈", i-buy_idx, pnl, highest/bp-1)
    last = min(buy_idx+10, len(closes)-1)
    return ("期末", last-buy_idx, closes[last]/bp-1, highest/bp-1)

def sim_trade_v2(closes, opens, highs, today):
    """V2: -8% 硬止损"""
    buy_idx = today + 1
    if buy_idx + 1 >= len(closes):
        return None
    bp = opens[buy_idx]
    highest = bp
    for i in range(buy_idx+1, min(buy_idx+11, len(closes))):
        c = closes[i]
        if c > highest: highest = c
        pnl = c/bp - 1
        if pnl <= -0.08:
            return ("止损", i-buy_idx, pnl, highest/bp-1)
        if i-buy_idx >= 10 and highest/bp-1 < 0.20:
            return ("到期", i-buy_idx, pnl, highest/bp-1)
        if highest/bp-1 >= 0.20 and c <= highest*0.90:
            return ("止盈", i-buy_idx, pnl, highest/bp-1)
    last = min(buy_idx+10, len(closes)-1)
    return ("期末", last-buy_idx, closes[last]/bp-1, highest/bp-1)

def sim_trade_v3(closes, opens, highs, today, pb_low):
    """V3: 跌破回调低点止损"""
    buy_idx = today + 1
    if buy_idx + 1 >= len(closes):
        return None
    bp = opens[buy_idx]
    highest = bp
    for i in range(buy_idx+1, min(buy_idx+11, len(closes))):
        c = closes[i]
        l = highs[i] if False else closes[i]  # use close for simplicity
        if c > highest: highest = c
        pnl = c/bp - 1
        
        # V3 stop: close below pullback low
        if c < pb_low:
            return ("止损", i-buy_idx, pnl, highest/bp-1)
        if i-buy_idx >= 10 and highest/bp-1 < 0.20:
            return ("到期", i-buy_idx, pnl, highest/bp-1)
        if highest/bp-1 >= 0.20 and c <= highest*0.90:
            return ("止盈", i-buy_idx, pnl, highest/bp-1)
    last = min(buy_idx+10, len(closes)-1)
    return ("期末", last-buy_idx, closes[last]/bp-1, highest/bp-1)

def run_version(name, symbols, reader, sim_fn, name_map):
    all_trades = []
    total_sigs = 0
    t0 = time.time()
    
    for si, code in enumerate(symbols):
        try:
            df = reader.daily(code)
            if df is None or len(df) < 80: continue
        except: continue
        df = df.sort_index()
        df = df[df.index >= "2016-01-01"]
        if len(df) < 80: continue
        
        c = df["close"].values.astype(np.float64)
        o = df["open"].values.astype(np.float64)
        h = df["high"].values.astype(np.float64)
        v = df["volume"].values.astype(np.float64)
        dates = df.index
        
        signals = find_signals_np(c, o, v, len(c))
        for sig in signals:
            total_sigs += 1
            if sim_fn == sim_trade_v3:
                result = sim_fn(c, o, h, sig["today"], sig["pullback_low"])
            else:
                result = sim_fn(c, o, h, sig["today"])
            if result:
                ext, days, ret, maxr = result
                all_trades.append({
                    "code": code,
                    "signal_date": str(dates[sig["today"]].date()),
                    "buy_date": str(dates[sig["today"]+1].date()),
                    "buy_price": round(o[sig["today"]+1], 2),
                    "exit": ext,
                    "hold_days": days,
                    "ret_pct": round(ret*100, 2),
                    "max_ret": round(maxr*100, 2),
                })
    
    if not all_trades:
        return None
    
    df_t = pd.DataFrame(all_trades)
    n = len(df_t)
    rets = df_t["ret_pct"]
    wins = (rets > 0).sum()
    
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    print(f"  交易:{n} | 胜率:{wins/n*100:.1f}% | 均值:{rets.mean():+.2f}% | 中位:{rets.median():+.2f}%")
    print(f"  最大盈:{rets.max():+.2f}% | 最大亏:{rets.min():+.2f}% | 标准差:{rets.std():.2f}%")
    
    print(f"  退出方式:")
    for ext in ["止盈","止损","到期","期末"]:
        sub = df_t[df_t["exit"]==ext]
        if len(sub)>0:
            w = (sub["ret_pct"]>0).sum()
            print(f"    {ext}: {len(sub)}笔 胜率{w/len(sub)*100:.1f}% 均值{sub['ret_pct'].mean():+.2f}%")
    
    # Yearly totals
    df_t["year"] = pd.to_datetime(df_t["buy_date"]).dt.year
    yearly = []
    for y in sorted(df_t["year"].unique()):
        s = df_t[df_t["year"]==y]
        yearly.append(f"{y}:{len(s)}笔/{s['ret_pct'].mean():+.1f}%")
    print(f"  年度: {' | '.join(yearly)}")
    
    return df_t, rets

def main():
    symbols = get_symbols()
    if not symbols:
        print("CSI300列表获取失败"); return
    print(f"CSI 300: {len(symbols)} 只\n")
    
    name_map = build_name_map()
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    results = {}
    
    # V1: -5% baseline
    r1, _ = run_version("V1: -5%硬止损", symbols, reader, sim_trade_v1, name_map)
    results["V1"] = r1
    
    # V2: -8%
    r2, _ = run_version("V2: -8%硬止损", symbols, reader, sim_trade_v2, name_map)
    results["V2"] = r2
    
    # V3: 跌破回调低点
    r3, _ = run_version("V3: 跌破回调低点止损", symbols, reader, sim_trade_v3, name_map)
    results["V3"] = r3
    
    # V4: 无止损
    def sim_trade_v4(closes, opens, highs, today):
        """V4: 无硬止损，仅止盈+到期"""
        buy_idx = today + 1
        if buy_idx + 1 >= len(closes): return None
        bp = opens[buy_idx]
        highest = bp
        for i in range(buy_idx+1, min(buy_idx+11, len(closes))):
            c = closes[i]
            if c > highest: highest = c
            pnl = c/bp - 1
            if highest/bp-1 >= 0.20 and c <= highest*0.90:
                return ("止盈", i-buy_idx, pnl, highest/bp-1)
        last = min(buy_idx+10, len(closes)-1)
        pnl = closes[last]/bp - 1
        if pnl >= 0.20:
            return ("止盈", last-buy_idx, pnl, highest/bp-1)
        return ("到期", last-buy_idx, pnl, highest/bp-1)
    
    r4, _ = run_version("V4: 无止损(仅止盈+到期)", symbols, reader, sim_trade_v4, name_map)
    results["V4"] = r4
    
    # V5: 无止损无止盈，纯持有10天
    def sim_trade_v5(closes, opens, highs, today):
        """V5: 买入后持有10天，第10天收盘卖出"""
        buy_idx = today + 1
        hold_end = min(buy_idx + 10, len(closes) - 1)
        if hold_end <= buy_idx:
            return None
        bp = opens[buy_idx]
        highest = np.max(highs[buy_idx:hold_end+1])
        last = closes[hold_end]
        pnl = last / bp - 1
        return ("持有", hold_end - buy_idx, pnl, highest / bp - 1)
    
    r5, _ = run_version("V5: 纯持有10天(无止损无止盈)", symbols, reader, sim_trade_v5, name_map)
    results["V5"] = r5
    
    # V6: 纯持有20天
    def sim_trade_v6(closes, opens, highs, today):
        buy_idx = today + 1
        hold_end = min(buy_idx + 20, len(closes) - 1)
        if hold_end <= buy_idx: return None
        bp = opens[buy_idx]
        highest = np.max(highs[buy_idx:hold_end+1])
        pnl = closes[hold_end] / bp - 1
        return ("持有", hold_end - buy_idx, pnl, highest / bp - 1)
    
    r6, _ = run_version("V6: 纯持有20天", symbols, reader, sim_trade_v6, name_map)
    results["V6"] = r6
    
    # V7: 纯持有30天
    def sim_trade_v7(closes, opens, highs, today):
        buy_idx = today + 1
        hold_end = min(buy_idx + 30, len(closes) - 1)
        if hold_end <= buy_idx: return None
        bp = opens[buy_idx]
        highest = np.max(highs[buy_idx:hold_end+1])
        pnl = closes[hold_end] / bp - 1
        return ("持有", hold_end - buy_idx, pnl, highest / bp - 1)
    
    r7, _ = run_version("V7: 纯持有30天", symbols, reader, sim_trade_v7, name_map)
    results["V7"] = r7
    
    # Comparison table
    print(f"\n{'='*70}")
    print(f"  三版本对比")
    print(f"{'='*70}")
    print(f"  {'版本':<18} {'交易':>4} {'胜率':>6} {'均值':>8} {'最大盈':>8} {'最大亏':>8}")
    print(f"  {'-'*54}")
    for name, df in results.items():
        if df is not None:
            rets = df["ret_pct"]
            print(f"  {name:<18} {len(df):>4} {(rets>0).mean()*100:>5.1f}% {rets.mean():>+7.2f}% {rets.max():>+7.2f}% {rets.min():>+7.2f}%")
    
    # Save
    out = Path("/mnt/c/Users/Sky.Lu/Desktop/output/backtest_surge_breakout_compare.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("拉升+回调+突破 CSI300 多版本止损对比\n\n")
        for name, df in results.items():
            if df is not None:
                rets = df["ret_pct"]
                f.write(f"{name}: {len(df)}笔 胜率{(rets>0).mean()*100:.1f}% 均值{rets.mean():+.2f}% 最大盈{rets.max():+.1f}% 最大亏{rets.min():+.1f}%\n")
    print(f"\n保存到: {out}")

if __name__ == "__main__":
    main()
