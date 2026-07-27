#!/usr/bin/env python3
"""
金叉确认策略:
1. 最近10个交易日内发生过MA10上穿MA60
2. 最近5日MA10和MA60均单调向上
3. 今日和昨日成交量 > 1.5×50日均量
"""

import json, time
import numpy as np
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"

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
        if df is None or len(df) < 70: return None
    except: return None
    df = df.sort_index().tail(80).copy()
    n = len(df)
    if n < 70: return None
    
    c = df["close"].values.astype(np.float64)
    o = df["open"].values.astype(np.float64)
    v = df["volume"].values.astype(np.float64)
    dates = df.index
    
    ma10 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
    for i in range(9, n): ma10[i] = np.mean(c[i-9:i+1])
    for i in range(59, n): ma60[i] = np.mean(c[i-59:i+1])
    
    vol_ma50 = np.full(n, np.nan)
    for i in range(49, n): vol_ma50[i] = np.mean(v[i-49:i+1])
    
    today = n - 1
    if today < 60: return None
    
    # Condition 1: 最近10个交易日内发生过金叉
    cross_day = None
    for i in range(today, max(today-10, 0), -1):
        if i < 1: break
        if np.isnan(ma10[i]) or np.isnan(ma60[i]) or np.isnan(ma10[i-1]) or np.isnan(ma60[i-1]):
            continue
        if ma10[i] > ma60[i] and ma10[i-1] <= ma60[i-1]:
            cross_day = i
            break
    if cross_day is None:
        return None
    days_since = today - cross_day
    
    # Condition 2: MA10 严格单调上升, MA60 不下降超过1%
    if today < 5: return None
    if np.isnan(ma10[today-4:today+1]).any() or np.isnan(ma60[today-4:today+1]).any():
        return None
    ma10_rising = all(ma10[today-4+i] < ma10[today-3+i] for i in range(4))
    if not ma10_rising:
        return None
    ma60_drop = (ma60[today-4] - ma60[today]) / ma60[today]
    if ma60_drop > 0.01:
        return None
    
    # Condition 3: 最近20日股价涨幅不超过20%
    if today < 20: return None
    ret_20d = (c[today] - c[today-20]) / c[today-20]
    if ret_20d > 0.20:
        return None
    
    # Condition 4: 今日和昨日成交量 > 1.5x 50日均量
    if np.isnan(vol_ma50[today]) or np.isnan(vol_ma50[today-1]):
        return None
    if v[today] <= 1.5 * vol_ma50[today] or v[today-1] <= 1.5 * vol_ma50[today-1]:
        return None
    
    # 放量检查: 从金叉日起到今天，必须每天连续 >1.5x（金叉日之前不管）
    vol_ok = True
    for i in range(cross_day, today + 1):
        if np.isnan(vol_ma50[i]) or v[i] <= 1.5 * vol_ma50[i]:
            vol_ok = False
            break
    if not vol_ok:
        return None
    
    return {
        "code": code,
        "date": str(dates[today].date()),
        "ma10": round(ma10[today], 2),
        "ma60": round(ma60[today], 2),
        "close": round(c[today], 2),
        "vol_today": round(v[today]/vol_ma50[today], 2),
        "vol_yest": round(v[today-1]/vol_ma50[today-1], 2),
        "cross_date": str(dates[cross_day].date()),
        "days_since": days_since,
    }

def main():
    codes = get_stock_list()
    total = len(codes)
    print(f"全市场: {total} 只")
    
    name_map = build_name_map()
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    results = []; t0 = time.time()
    for i, code in enumerate(codes):
        r = check_stock(reader, code)
        if r:
            r["name"] = name_map.get(code, code)
            results.append(r)
        if (i+1) % 500 == 0:
            el = time.time()-t0
            print(f"  {i+1}/{total} | 找到:{len(results)} | {el:.0f}秒")
    
    el = time.time()-t0
    print(f"\n{'='*85}")
    print(f"金叉确认策略 扫描 ({el:.0f}秒)")
    print(f"{'='*85}")
    print(f"总: {total} | 满足: {len(results)}")
    
    if not results:
        print("无结果"); return
    
    print(f"\n{'代码':<8} {'名称':<12} {'日期':<12} {'收盘':>8} {'MA10':>8} {'MA60':>8} {'量(今)':>6} {'量(昨)':>6} {'金叉日':<12} {'距':>3}")
    print("-"*95)
    for r in results:
        print(f"{r['code']:<8} {r['name']:<12} {r['date']:<12} {r['close']:>8.2f} {r['ma10']:>8.2f} {r['ma60']:>8.2f} {r['vol_today']:>6.2f} {r['vol_yest']:>6.2f} {r['cross_date']:<12} {r['days_since']:>2}天")
    
    out = Path("/mnt/c/Users/Sky.Lu/Desktop/output/golden_cross_confirm_scan.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"金叉确认策略扫描\n\n")
        for r in results:
            f.write(f"{r['code']} {r['name']}: {r['date']} MA10={r['ma10']} MA60={r['ma60']} 金叉{r['cross_date']} 距{r['days_since']}天\n")
    print(f"\n保存: {out}")

if __name__ == "__main__":
    main()
