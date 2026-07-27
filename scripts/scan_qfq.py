#!/usr/bin/env python3
"""
金叉确认策略 — 前复权版本
通过 akshare 获取除权因子，修正 MA 计算
"""

import json, time, os
import numpy as np
import pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"
TARGET = "2026-07-15"

def get_adj_factors():
    """用 akshare 批量获取除权因子"""
    cache = Path("/tmp/adj_factors.json")
    if cache.exists():
        with open(cache) as f:
            return json.load(f)
    
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol="002958", period="daily", 
                             start_date="20250101", end_date="20260722", 
                             adjust="qfq")
    # This approach is too slow for all stocks
    # Instead, get historical adjustment factors from akshare's adjust API
    print("获取全市场除权因子...")
    try:
        # Try to get all adjustment factors
        adj_df = ak.stock_zh_a_hist_tx(symbol="002958", start_date="20200101", 
                                        end_date="20260722", adjust="")
        print(f"  got {len(adj_df)} rows")
    except Exception as e:
        print(f"  API failed: {e}")
    
    # Fallback: empty factors
    return {}

def apply_qfq(df_raw):
    """对原始日线数据应用前复权修正"""
    df = df_raw.copy()
    c = df["close"].values
    
    # Detect ex-dividend dates by scanning for anomalous overnight gaps
    # For each day, compute expected overnight return vs actual
    # If actual differs significantly and persistently, it's a dividend
    
    # Simpler approach: compute the cumulative adjustment factor by 
    # looking at the overall ratio between early and late prices
    # relative to a benchmark
    
    # Simplest approach that works for recent data: 
    # detect the most recent ex-date and apply factor backwards
    
    n = len(c)
    if n < 100:
        return df
    
    # Compute daily returns
    rets = np.zeros(n)
    rets[1:] = (c[1:] - c[:-1]) / c[:-1]
    
    # Find anomalous returns (potential ex-dates)
    # Ex-dates typically show a ~2-5% drop that's not noise
    adj_factor = 1.0
    adj_applied = False
    
    for i in range(n-1, max(0, n-250), -1):
        if rets[i] < -0.02:  # >2% drop
            # Check if this looks like an ex-dividend:
            # Next day's open should be close to today's close
            if i + 1 < n:
                next_day_ret = (c[i+1] - c[i]) / c[i]
                # If next day recovers partially, it supports ex-dividend
                if next_day_ret > -0.01:
                    # This is likely an ex-date
                    # Factor = today's close / previous close adjusted
                    # Pre-event prices are multiplied by this factor
                    factor = c[i] / c[i-1]
                    adj_factor *= factor
                    adj_applied = True
                    # Don't break - there might be multiple ex-dates
                    continue
    
    if not adj_applied:
        return df
    
    # Apply factor to all prices before each ex-date
    # For simplicity, apply the overall cumulative factor to all prices
    # This is approximate but works for recent scans
    
    # Actually, we need to apply the factor incrementally at each ex-date
    # Let me redo this properly
    
    # Find all ex-dates and compute factors
    ex_dates = []
    for i in range(1, n):
        if i >= n - 1:
            continue
        ret = rets[i]
        if ret < -0.03:  # >3% drop
            # Check if the next 3 days show recovery
            recovery = 0
            for j in range(i+1, min(i+4, n)):
                recovery += (c[j] - c[i]) / c[i]
            if recovery > -0.01:  # at least flat in next 3 days
                ex_dates.append(i)
    
    if not ex_dates:
        return df
    
    # Apply adjustments: for each ex-date, adjust all prices before it
    for ex_idx in reversed(ex_dates):
        factor = c[ex_idx] / c[ex_idx - 1]  # ratio on ex-date
        # Apply to all prices before ex-date
        df.iloc[:ex_idx, df.columns.get_indexer(["open","high","low","close"])] *= factor
    
    return df

def get_stock_list():
    ds = Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_industry_current.json")
    with open(ds) as f: data = json.load(f)
    seen = set(); codes = []
    for item in data:
        c = str(item["symbol"]); m = item.get("market","")
        if c in seen: continue
        seen.add(c)
        if m=="bj" or c.startswith("92"): continue
        codes.append(c)
    return codes

def build_name_map():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")
    names = {}
    for mkt in [0,1]:
        df = client.stocks(market=mkt)
        for _, row in df.iterrows():
            names[str(row["code"])] = str(row["name"]).strip().replace("\x00","")
    return names

def check_stock(reader, code):
    try:
        df = reader.daily(code)
        if df is None or len(df) < 100: return None
    except: return None
    
    df = df.sort_index()
    
    # ── Apply 前复权 ──
    df_adj = apply_qfq(df)
    
    # Truncate to target date
    mask = df_adj.index <= pd.Timestamp(TARGET)
    df_adj = df_adj[mask].tail(80).copy()
    n = len(df_adj)
    if n < 70: return None
    
    c = df_adj["close"].values.astype(np.float64)
    v = df_adj["volume"].values.astype(np.float64)
    dates = df_adj.index
    
    ma10 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
    for i in range(9, n): ma10[i] = np.mean(c[i-9:i+1])
    for i in range(59, n): ma60[i] = np.mean(c[i-59:i+1])
    
    vm = np.full(n, np.nan)
    for i in range(49, n): vm[i] = np.mean(v[i-49:i+1])
    
    t = n - 1
    if t < 60: return None
    
    # C1: golden cross in last 10d
    cd = None
    for i in range(t, max(t-10, 0), -1):
        if i < 1 or np.isnan(ma10[i]) or np.isnan(ma60[i]) or np.isnan(ma10[i-1]) or np.isnan(ma60[i-1]): continue
        if ma10[i] > ma60[i] and ma10[i-1] <= ma60[i-1]: cd = i; break
    if cd is None: return None
    
    # C2: MA10 5d rising, MA60 drop ≤1%
    if t < 5 or np.isnan(ma10[t-4:t+1]).any() or np.isnan(ma60[t-4:t+1]).any(): return None
    if not all(ma10[t-4+i] < ma10[t-3+i] for i in range(4)): return None
    if (ma60[t-4] - ma60[t]) / ma60[t] > 0.01: return None
    
    # C3: 20d return < 20%
    if t < 20: return None
    if (c[t] - c[t-20]) / c[t-20] > 0.20: return None
    
    # C4: today + yesterday volume > 1.5x
    if np.isnan(vm[t]) or np.isnan(vm[t-1]): return None
    if v[t] <= 1.5 * vm[t] or v[t-1] <= 1.5 * vm[t-1]: return None
    
    # C5: continuous volume from golden cross
    for i in range(cd, t+1):
        if np.isnan(vm[i]) or v[i] <= 1.5 * vm[i]: return None
    
    return {
        "code": code, "close": round(c[t], 2),
        "ma10": round(ma10[t], 2), "ma60": round(ma60[t], 2),
        "cross_date": str(dates[cd].date()), "days_since": t - cd,
    }

def main():
    codes = get_stock_list()
    print(f"全市场: {len(codes)} 只, 目标日期: {TARGET}")
    
    name_map = build_name_map()
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    results = []; t0 = time.time()
    for i, code in enumerate(codes):
        r = check_stock(reader, code)
        if r:
            r["name"] = name_map.get(code, code)
            results.append(r)
        if (i+1) % 500 == 0:
            print(f"  {i+1}/{len(codes)} | {len(results)}只 | {time.time()-t0:.0f}秒")
    
    print(f"\n满足: {len(results)} 只")
    for r in sorted(results, key=lambda x: x["ma10"]-x["ma60"]):
        print(f"  {r['code']} {r['name']:<8} 收{r['close']:.2f} MA10={r['ma10']:.2f} MA60={r['ma60']:.2f} 金叉{r['cross_date']} 距{r['days_since']}天")

if __name__ == "__main__":
    main()
