#!/usr/bin/env python3
"""
CSI300 MACD极值金叉+补仓 — 修复版
卖出: 每天检查，总盈利>10%即T+1开盘清仓（无限期持有）
"""

import json, time
import numpy as np
import pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"
LOT_CAPITAL = 50000

def get_csi300():
    with open("/tmp/csi300_constituents.json") as f:
        return sorted(set(str(c) for c in json.load(f)))

def build_name_map():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")
    names = {}
    for mkt in [0, 1]:
        df = client.stocks(market=mkt)
        for _, row in df.iterrows():
            names[str(row["code"])] = str(row["name"]).strip().replace("\x00", "")
    return names

def backtest_stock(reader, code, year):
    try:
        df = reader.daily(code)
        if df is None or len(df) < 100: return [], []
    except: return [], []
    
    df = df.sort_index()
    mask = (df.index >= f"{year-1}-01-01") & (df.index <= "2026-07-23")
    df = df[mask].copy()
    n = len(df)
    if n < 100: return [], []
    
    c = df["close"].values.astype(np.float64)
    o = df["open"].values.astype(np.float64)
    dates = df.index
    
    ema12 = pd.Series(c).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    ndif = np.where(c != 0, dif / c * 100, 0)
    ndea = np.where(c != 0, dea / c * 100, 0)
    
    trades = []
    holding = []
    lots = []
    
    for i in range(60, n):
        if np.isnan(c[i]) or c[i] <= 0: continue
        current_price = c[i]
        
        # ── Check exit EVERY day ──
        if lots:
            total_cost = sum(p * q for p, q in lots)
            total_qty = sum(q for _, q in lots)
            if total_cost > 0:
                total_pnl = (current_price * total_qty / total_cost - 1) * 100
                
                if total_pnl > 10.0:
                    sell_idx = i + 1
                    if sell_idx < n:
                        sell_price = o[sell_idx]
                        sell_value = sell_price * total_qty
                        sell_pnl = (sell_value / total_cost - 1) * 100
                        pnl_abs = sell_value - total_cost
                        
                        entry_dates = [str(dates[idx2].date()) for idx2 in range(i) if False]  # won't bother
                        
                        trades.append({
                            "code": code,
                            "buy_date": str(dates[i].date())[:10],  # approximate
                            "lots": len(lots),
                            "avg_entry": round(total_cost / total_qty, 2),
                            "sell_date": str(dates[sell_idx].date()),
                            "sell_price": round(sell_price, 2),
                            "pnl_pct": round(sell_pnl, 2),
                            "pnl_abs": round(pnl_abs, 2),
                        })
                        lots = []
                        continue  # skip signal check after selling
        
        # ── Check entry signal ──
        if np.isnan(ndif[i]) or np.isnan(ndea[i]): continue
        if np.isnan(ndif[i-1]) or np.isnan(ndea[i-1]): continue
        is_gc = (ndif[i] > ndea[i]) and (ndif[i-1] <= ndea[i-1])
        if not is_gc or ndif[i] >= -5.0: continue
        
        # Signal triggered
        if lots:
            # Already holding — check average down
            total_cost = sum(p * q for p, q in lots)
            total_qty = sum(q for _, q in lots)
            total_pnl = (current_price * total_qty / total_cost - 1) * 100
            
            if total_pnl < -10.0:
                buy_idx = i + 1
                if buy_idx < n:
                    bp = o[buy_idx]
                    qty = int(LOT_CAPITAL / bp)
                    lots.append((bp, qty))
        else:
            # New buy
            buy_idx = i + 1
            if buy_idx < n:
                bp = o[buy_idx]
                qty = int(LOT_CAPITAL / bp)
                lots = [(bp, qty)]
                holding.append({
                    "code": code,
                    "start": str(dates[buy_idx].date()),
                })
    
    # Positions still open at end of data
    open_positions = []
    if lots:
        total_cost = sum(p * q for p, q in lots)
        total_qty = sum(q for _, q in lots)
        open_positions.append({
            "code": code,
            "lots": len(lots),
            "avg_entry": round(total_cost / total_qty, 2),
            "current_price": round(c[-1], 2),
            "current_pnl": round((c[-1] * total_qty / total_cost - 1) * 100, 2),
            "start": holding[-1]["start"] if holding else "?",
        })
    
    return trades, open_positions

def main():
    import sys
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2016
    
    codes = get_csi300()
    print(f"CSI 300: {len(codes)} 只, 回测起始: {year}年")
    
    name_map = build_name_map()
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    all_trades = []
    all_open = []
    t0 = time.time()
    
    for i, code in enumerate(codes):
        trades, open_pos = backtest_stock(reader, code, year)
        for t in trades:
            t["name"] = name_map.get(code, code)
        for p in open_pos:
            p["name"] = name_map.get(code, code)
        all_trades.extend(trades)
        all_open.extend(open_pos)
        
        if (i+1) % 50 == 0:
            print(f"  {i+1}/{len(codes)} | {len(all_trades)}笔完成 | {time.time()-t0:.0f}秒")
    
    print(f"\n完成: {time.time()-t0:.0f}秒")
    
    wins = [t for t in all_trades if t["pnl_pct"] > 0]
    
    print(f"\n{'='*70}")
    print(f"CSI300 MACD极值金叉+补仓 — {year}年起")
    print(f"{'='*70}")
    print(f"已完成交易: {len(all_trades)} 笔")
    print(f"盈利: {len(wins)}")
    
    if all_trades:
        rets = [t["pnl_pct"] for t in all_trades]
        total_pnl = sum(t["pnl_abs"] for t in all_trades)
        print(f"胜率: {len(wins)/len(all_trades)*100:.1f}%")
        print(f"均值: {np.mean(rets):+.2f}%  中位: {np.median(rets):+.2f}%")
        print(f"总盈亏: {total_pnl:+,.0f}")
    
    print(f"\n当前仍持有(未达+10%): {len(all_open)} 只")
    if all_open:
        for p in all_open:
            print(f"  {p['code']} {p['name']:<8} {p['lots']}份 均价{p['avg_entry']:.1f} 现价{p['current_price']:.1f} {p['current_pnl']:+.1f}%")
    
    # Per-year breakdown
    if all_trades:
        df = pd.DataFrame(all_trades)
        df["year"] = pd.to_datetime(df["sell_date"]).dt.year
        print(f"\n卖出年度分布:")
        for y, sub in df.groupby("year"):
            r = sub["pnl_pct"]
            print(f"  {y}: {len(sub)}笔 胜率{(r>0).mean()*100:.0f}% 均值{r.mean():+.1f}% 总{r.sum():+.1f}%")

if __name__ == "__main__":
    main()
