#!/usr/bin/env python3
"""全市场回测 — 拉升+回调+突破 策略最终版"""
import json, time, os, sys
import numpy as np
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"

def get_stock_list():
    ds = Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_industry_current.json")
    with open(ds) as f:
        data = json.load(f)
    seen = set()
    codes = []
    for item in data:
        c = str(item["symbol"]); m = item.get("market","")
        if c in seen: continue
        seen.add(c)
        if m=="bj" or c.startswith("92"): continue
        codes.append(c)
    return codes

def backtest_stock(reader, code):
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
    v = df["volume"].values.astype(np.float64)
    
    vm = np.full(n, np.nan)
    for i in range(49, n): vm[i] = np.mean(v[i-49:i+1])
    dr = np.zeros(n); dr[1:] = (c[1:]-c[:-1])/c[:-1]
    sr = np.full(n, np.nan)
    for i in range(4, n): sr[i] = (c[i]-o[i-4])/o[i-4]
    
    trades = []
    for today in range(70, n):
        for se in range(today-9, today-5):
            if se < 50 or today-se > 20: continue
            ss = se - 4
            if ss < 50: continue
            sret = sr[se]
            if np.isnan(sret) or sret <= 0.20: continue
            m50 = vm[ss]
            if np.isnan(m50): continue
            
            vok = True
            for j in range(ss, se+1):
                if c[j] > o[j] and v[j] <= 1.5*m50: vok = False; break
                if c[j] <= o[j] and v[j] <= 0.8*m50: vok = False; break
            if not vok: continue
            
            sh = -1.0
            for j in range(ss, se+1):
                if dr[j] > 0.05 and c[j] > sh: sh = c[j]
            if sh < 0: continue
            
            mx = sh * 1.05; pl = 1e9; pi = -1
            for j in range(se+1, today):
                if c[j] > mx: pi = -2; break
                if c[j] < pl: pl = c[j]; pi = j
            if pi < 0 or pi-se < 5 or pl >= c[se]: continue
            hr = o[ss] + (sh - o[ss]) * 0.5
            if pl < hr: continue
            
            # Quality filters
            srng = sh - o[ss]
            pbpct = (sh - pl) / srng
            pbspeed = (sh - pl) / (pi - se)
            if pbpct > 0.25 or pbspeed > 0.5: continue
            
            if c[today] > sh and c[today-1] <= sh:
                bi = today + 1
                for hold_days in [10, 20, 30]:
                    he = min(bi + hold_days, n - 1)
                    if he > bi:
                        ret = (c[he]/o[bi] - 1) * 100
                        trades.append({"hold": hold_days, "ret": ret, "date": str(df.index[today].date())})
                break
    return trades

def main():
    codes = get_stock_list()
    total = len(codes)
    print(f"全市场: {total} 只")
    
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    all_t = []; t0 = time.time()
    for si, code in enumerate(codes):
        all_t.extend(backtest_stock(reader, code))
        if (si+1) % 500 == 0:
            el = time.time()-t0
            print(f"  {si+1}/{total} | {len(all_t)}笔 | {el:.0f}秒 | 剩余{(total-si-1)/(si+1)*el:.0f}秒")
    
    el = time.time()-t0
    print(f"\n完成: {el:.0f}秒 | 共 {len(all_t)} 笔")
    
    if not all_t:
        print("无交易"); return
    
    import pandas as pd
    df = pd.DataFrame(all_t)
    
    for hold in [10, 20, 30]:
        sub = df[df["hold"]==hold]["ret"]
        n_t = len(sub)
        w = (sub > 0).sum()
        m = sub.mean()
        med = sub.median()
        print(f"\n持有{hold}天: {n_t}笔 胜率{w/n_t*100:.1f}% 均值{m:+.2f}% 中位{med:+.2f}% 最大盈{sub.max():+.1f}% 最大亏{sub.min():+.1f}%")
        # yearly
        dfy = df[df["hold"]==hold].copy()
        dfy["year"] = pd.to_datetime(dfy["date"]).dt.year
        yrs = []
        for y in sorted(dfy["year"].unique()):
            sy = dfy[dfy["year"]==y]["ret"]
            yrs.append(f"{y}:{len(sy)}/{sy.mean():+.1f}%")
        print(f"  年度: {' | '.join(yrs)}")
    
    out = Path("/mnt/c/Users/Sky.Lu/Desktop/output/backtest_surge_fullmarket.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"全市场回测 {total}只 {len(all_t)}笔\n\n")
        for hold in [10, 20, 30]:
            sub = df[df["hold"]==hold]["ret"]
            f.write(f"持有{hold}天: {len(sub)}笔 胜率{(sub>0).mean()*100:.1f}% 均值{sub.mean():+.2f}%\n")
    print(f"\n保存: {out}")

if __name__ == "__main__":
    main()
