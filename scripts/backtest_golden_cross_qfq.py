#!/usr/bin/env python3
"""金叉确认策略回测 - 前复权版"""
import json, time, os
import numpy as np
import pandas as pd
from pathlib import Path
from mootdx.reader import Reader

CACHE_DIR = Path("/home/lufanfeng/.cache/stock_qfq")
TDX_DIR = "/mnt/c/new_tdx64"

def get_stock_list():
    ds = Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_industry_current.json")
    with open(ds) as f: data = json.load(f)
    seen = set(); codes = []
    for item in data:
        c = str(item["symbol"]); m = item.get("market","")
        if c in seen: continue; seen.add(c)
        if m == "bj" or c.startswith("92"): continue
        codes.append(c)
    return codes

def load_qfq(code):
    f = CACHE_DIR / f"{code}.parquet"
    if not f.exists(): return None
    return pd.read_parquet(f)

def backtest_stock(reader, code):
    """Return list of trade returns for this stock"""
    qfq = load_qfq(code)
    if qfq is None or len(qfq) < 100:
        return []
    
    # Load TDX volume
    try:
        df_raw = reader.daily(code)
        if df_raw is None or len(df_raw) < 100: return []
    except:
        return []
    
    df_raw = df_raw.sort_index()
    vol = df_raw["volume"]
    # Align volume with qfq dates
    common = qfq.index.intersection(vol.index)
    if len(common) < 100:
        return []
    
    qfq = qfq.loc[common]
    vol = vol.loc[common]
    
    c = qfq["close"].values.astype(np.float64)
    v = vol.values.astype(np.float64)
    dates = qfq.index
    n = len(c)
    
    # Compute MAs
    ma10 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
    for i in range(9, n): ma10[i] = np.mean(c[i-9:i+1])
    for i in range(59, n): ma60[i] = np.mean(c[i-59:i+1])
    vm = np.full(n, np.nan)
    for i in range(49, n): vm[i] = np.mean(v[i-49:i+1])
    
    trades = []
    
    for t in range(70, n - 5):  # leave room for at least 5 days of holding
        # C1: golden cross in last 10d
        cd = None
        for i in range(t, max(t-10, 0), -1):
            if i < 1 or np.isnan(ma10[i]) or np.isnan(ma60[i]) or np.isnan(ma10[i-1]) or np.isnan(ma60[i-1]): continue
            if ma10[i] > ma60[i] and ma10[i-1] <= ma60[i-1]: cd = i; break
        if cd is None: continue
        
        # C2
        if t < 5 or np.isnan(ma10[t-4:t+1]).any() or np.isnan(ma60[t-4:t+1]).any(): continue
        if not all(ma10[t-4+i] < ma10[t-3+i] for i in range(4)): continue
        if (ma60[t-4] - ma60[t]) / ma60[t] > 0.01: continue
        
        # C3
        if t < 20: continue
        if (c[t] - c[t-20]) / c[t-20] > 0.20: continue
        
        # C4+C5 volume
        if np.isnan(vm[t]) or np.isnan(vm[t-1]): continue
        if v[t] <= 1.5 * vm[t] or v[t-1] <= 1.5 * vm[t-1]: continue
        
        vol_ok = True
        for i in range(cd, t+1):
            if np.isnan(vm[i]) or v[i] <= 1.5 * vm[i]:
                vol_ok = False; break
        if not vol_ok: continue
        
        # Buy T+1 open, hold 1/3/5/10d
        buy_idx = t + 1
        if buy_idx >= n: continue
        
        # Get buy price (raw open), convert to qfq-equivalent
        try:
            buy_pos = df_raw.index.get_loc(dates[buy_idx])
            if isinstance(buy_pos, slice):
                raw_open = float(df_raw.iloc[buy_pos.start]["open"])
            else:
                raw_open = float(df_raw.iloc[buy_pos]["open"])
        except:
            continue
        
        # Adjustment factor: qfq_close / raw_close at buy_idx
        # This converts raw open to qfq-equivalent
        try:
            raw_close_pos = df_raw.index.get_loc(dates[buy_idx])
            if isinstance(raw_close_pos, slice):
                raw_close = float(df_raw.iloc[raw_close_pos.start]["close"])
            else:
                raw_close = float(df_raw.iloc[raw_close_pos]["close"])
        except:
            continue
        
        adj_factor = c[buy_idx] / raw_close if raw_close != 0 else 1.0
        buy_price = raw_open * adj_factor
        
        for hold in [1, 3, 5, 10]:
            sell_idx = buy_idx + hold - 1
            if sell_idx >= n: continue
            ret = (c[sell_idx] / buy_price - 1) * 100
            # ±5% 止盈止损: cap at +5% or -5%
            ret_capped = max(-5.0, min(5.0, ret))
            trades.append({
                "code": code,
                "date": str(dates[t].date()),
                "hold": hold,
                "ret": round(ret, 2),
                "ret_capped": round(ret_capped, 2),
            })
    
    return trades

def main():
    codes = get_stock_list()
    print(f"全市场: {len(codes)} 只")
    
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    all_trades = []; t0 = time.time()
    for i, code in enumerate(codes):
        trades = backtest_stock(reader, code)
        all_trades.extend(trades)
        if (i+1) % 500 == 0:
            el = time.time()-t0
            print(f"  {i+1}/{len(codes)} | {len(all_trades)}笔 | {el:.0f}秒")
    
    el = time.time()-t0
    print(f"\n完成: {el:.0f}秒 | 总交易: {len(all_trades)}")
    
    if not all_trades:
        print("无交易"); return
    
    df = pd.DataFrame(all_trades)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    
    print(f"\n{'='*60}")
    print(f"金叉确认策略 回测 (前复权)")
    print(f"{'='*60}")
    
    for hold in [1, 3, 5, 10]:
        sub = df[df["hold"] == hold]
        if len(sub) == 0: continue
        rets_raw = sub["ret"]
        rets = sub["ret_capped"]
        w = (rets > 0).sum()
        print(f"\n持有{hold}天: {len(sub)}笔 胜率{w/len(sub)*100:.1f}% 均值{rets.mean():+.2f}% 中位{rets.median():+.2f}% (原始均值{rets_raw.mean():+.2f}%)")
        
        # Yearly
        yrs = sub.groupby("year")["ret"]
        parts = []
        for y, g in yrs:
            parts.append(f"{y}:{len(g)}/{g.mean():+.1f}%")
        print(f"  年度: {' | '.join(parts)}")
    
    out = Path("/mnt/c/Users/Sky.Lu/Desktop/output/backtest_golden_cross_qfq.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for hold in [1, 3, 5, 10]:
            sub = df[df["hold"] == hold]
            if len(sub) == 0: continue
            rets = sub["ret"]
            f.write(f"持有{hold}天: {len(sub)}笔 胜率{(rets>0).mean()*100:.1f}% 均值{rets.mean():+.2f}%\n")
    print(f"\n保存: {out}")

if __name__ == "__main__":
    main()
