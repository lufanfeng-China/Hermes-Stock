#!/usr/bin/env python3
"""构建全市场前复权价格缓存，然后运行扫描/回测"""

import json, time, os
import numpy as np
import pandas as pd
from pathlib import Path

CACHE_DIR = Path("/home/lufanfeng/.cache/stock_qfq")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

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

def fetch_qfq(code):
    """Fetch qfq close prices for one stock, cache to parquet"""
    cache_file = CACHE_DIR / f"{code}.parquet"
    # Return cached if fresh (<1 day old)
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 86400:  # 24h
            return pd.read_parquet(cache_file)
    
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                 start_date="20250101", end_date="20260723",
                                 adjust="qfq")
        if df is None or len(df) == 0:
            return None
        # Keep only date and close
        result = df[["日期", "收盘"]].copy()
        result.columns = ["date", "close"]
        result["date"] = pd.to_datetime(result["date"])
        result = result.set_index("date").sort_index()
        result.to_parquet(cache_file)
        return result
    except Exception as e:
        return None

def build_cache(codes, force=False):
    """Build cache for all stocks"""
    missing = []
    for code in codes:
        cache_file = CACHE_DIR / f"{code}.parquet"
        if not force and cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < 86400:
                continue
        missing.append(code)
    
    if not missing:
        print("缓存完整，无需更新")
        return
    
    print(f"需更新 {len(missing)} 只...")
    import akshare as ak
    
    t0 = time.time()
    for i, code in enumerate(missing):
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                     start_date="20250101", end_date="20260723",
                                     adjust="qfq")
            if df is not None and len(df) > 0:
                result = df[["日期", "收盘"]].copy()
                result.columns = ["date", "close"]
                result["date"] = pd.to_datetime(result["date"])
                result = result.set_index("date").sort_index()
                result.to_parquet(CACHE_DIR / f"{code}.parquet")
        except:
            pass
        
        if (i+1) % 200 == 0:
            el = time.time() - t0
            rate = (i+1) / el
            eta = (len(missing) - i - 1) / rate
            print(f"  {i+1}/{len(missing)} {rate:.1f}只/秒 剩余{eta/60:.0f}分钟")
    
    print(f"缓存完成: {time.time()-t0:.0f}秒")

def load_qfq_close(code):
    """Load qfq close prices for one stock"""
    cache_file = CACHE_DIR / f"{code}.parquet"
    if not cache_file.exists():
        return None
    try:
        return pd.read_parquet(cache_file)
    except:
        return None

def load_tdx_volume(reader, code):
    """Load volume data from TDX"""
    try:
        df = reader.daily(code)
        if df is None: return None
        df = df.sort_index()
        return df["volume"]
    except:
        return None

# ── Scan logic (uses qfq close + TDX volume) ──

from mootdx.reader import Reader

def scan_date(codes, target_date, reader, name_map):
    """Scan all stocks for a specific target date"""
    target = pd.Timestamp(target_date)
    results = []
    
    t0 = time.time()
    for i, code in enumerate(codes):
        # Load qfq close prices
        qfq = load_qfq_close(code)
        if qfq is None or len(qfq) < 70:
            continue
        
        # Truncate to target date
        mask = qfq.index <= target
        qfq = qfq[mask].tail(80)
        n = len(qfq)
        if n < 70:
            continue
        
        c = qfq["close"].values.astype(np.float64)
        
        # Load TDX volume
        vol = load_tdx_volume(reader, code)
        if vol is None or len(vol) < 70:
            continue
        vol = vol.sort_index()
        vol = vol[vol.index <= target].tail(80)
        if len(vol) < 70:
            continue
        v = vol.values.astype(np.float64)
        dates = qfq.index
        
        # Compute MAs
        ma10 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
        for j in range(9, n): ma10[j] = np.mean(c[j-9:j+1])
        for j in range(59, n): ma60[j] = np.mean(c[j-59:j+1])
        
        vm = np.full(n, np.nan)
        for j in range(49, n): vm[j] = np.mean(v[j-49:j+1])
        
        t = n - 1
        if t < 60: continue
        
        # C1: golden cross in last 10d
        cd = None
        for j in range(t, max(t-10, 0), -1):
            if j < 1 or np.isnan(ma10[j]) or np.isnan(ma60[j]) or np.isnan(ma10[j-1]) or np.isnan(ma60[j-1]): continue
            if ma10[j] > ma60[j] and ma10[j-1] <= ma60[j-1]: cd = j; break
        if cd is None: continue
        
        # C2: MA10 5d rising, MA60 drop ≤1%
        if t < 5 or np.isnan(ma10[t-4:t+1]).any() or np.isnan(ma60[t-4:t+1]).any(): continue
        if not all(ma10[t-4+j] < ma10[t-3+j] for j in range(4)): continue
        if (ma60[t-4] - ma60[t]) / ma60[t] > 0.01: continue
        
        # C3: 20d return < 20%
        if t < 20: continue
        if (c[t] - c[t-20]) / c[t-20] > 0.20: continue
        
        # C4: today + yesterday volume > 1.5x
        if np.isnan(vm[t]) or np.isnan(vm[t-1]): continue
        if v[t] <= 1.5 * vm[t] or v[t-1] <= 1.5 * vm[t-1]: continue
        
        # C5: continuous volume from golden cross
        vol_ok = True
        for j in range(cd, t+1):
            if np.isnan(vm[j]) or v[j] <= 1.5 * vm[j]:
                vol_ok = False; break
        if not vol_ok: continue
        
        results.append({
            "code": code, "name": name_map.get(code, code),
            "close": round(c[t], 2), "ma10": round(ma10[t], 2), "ma60": round(ma60[t], 2),
            "cross": str(dates[cd].date())[-5:], "days": t - cd,
        })
        
        if (i+1) % 1000 == 0:
            print(f"  {i+1}/{len(codes)} | {len(results)}只 | {time.time()-t0:.0f}秒")
    
    return results

def main():
    codes = get_stock_list()
    print(f"全市场: {len(codes)} 只")
    
    # Build cache
    build_cache(codes)
    
    # Build name map
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")
    name_map = {}
    for mkt in [0, 1]:
        df = client.stocks(market=mkt)
        for _, row in df.iterrows():
            name_map[str(row["code"])] = str(row["name"]).strip().replace("\x00", "")
    
    reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
    
    # Scan
    target = "2026-07-22"
    print(f"\n扫描日期: {target}")
    t0 = time.time()
    results = scan_date(codes, target, reader, name_map)
    print(f"\n完成: {time.time()-t0:.0f}秒 | 满足: {len(results)} 只")
    
    results.sort(key=lambda r: r["ma10"] - r["ma60"])
    print(f"\n{'代码':<8} {'名称':<8} {'收盘':>7} {'MA10':>8} {'MA60':>8} {'金叉':>6} {'距':>3}")
    print("-"*65)
    for r in results:
        print(f"{r['code']:<8} {r['name']:<8} {r['close']:>7.2f} {r['ma10']:>8.2f} {r['ma60']:>8.2f} {r['cross']:>6} {r['days']:>2}天")
    print(f"\n共 {len(results)} 只")

if __name__ == "__main__":
    main()
