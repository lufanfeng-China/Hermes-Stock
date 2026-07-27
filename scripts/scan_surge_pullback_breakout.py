#!/usr/bin/env python3
"""
新策略扫描 — 拉升+回调+突破 形态
条件:
1. 过去20交易日内，存在连续5日涨超20%，且收涨日成交量>1.5倍50日均量
2. 拉升后连续≥5日整体回调，回调不破拉升幅度的50%
3. 今日收盘站上拉升高点
"""

import json, time
import pandas as pd
import numpy as np
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"

def get_stock_list():
    ds_path = Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_industry_current.json")
    with open(ds_path) as f:
        data = json.load(f)
    rows = []
    seen = set()
    for item in data:
        code = str(item["symbol"])
        market = item.get("market", "")
        if code in seen:
            continue
        seen.add(code)
        if market == "bj" or code.startswith("92"):
            continue
        rows.append(code)
    return rows

def build_name_map():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")
    names = {}
    df_sz = client.stocks(market=0)
    mask = df_sz["code"].astype(str).str.match(r'^(00[0-4]|30[01])\d{3}$')
    for _, row in df_sz[mask].iterrows():
        names[str(row["code"])] = str(row["name"]).strip().replace("\x00", "")
    df_sh = client.stocks(market=1)
    mask = df_sh["code"].astype(str).str.match(r'^(6[0-9]{2}|68[89])\d{3}$')
    for _, row in df_sh[mask].iterrows():
        code = str(row["code"])
        if code not in names:
            names[code] = str(row["name"]).strip().replace("\x00", "")
    return names

def check_stock(reader, code):
    try:
        df = reader.daily(code)
        if df is None or len(df) < 70:
            return None
    except:
        return None

    df = df.sort_index().tail(80).copy()  # enough for 20d lookback + 50d MA + buffer
    if len(df) < 70:
        return None

    # Compute volume MA50
    df["vol_ma50"] = df["volume"].rolling(50).mean()

    # Today is last row
    today_idx = len(df) - 1
    today_close = df["close"].iloc[today_idx]

    # Lookback: surge peak must be within last 20 trading days
    # So search for surge starting at most from today-25 (5d surge + some pullback),
    # and surge ending at most from today-5 (need room for 5+ days pullback)
    # Simplification: scan all possible 5-day windows in the last 25 days

    # For each possible 5-day window ending between today-5 and today-25
    #   (need at least 5d pullback after surge end, so surge end <= today-5)
    #   (surge end >= today-20, so surge peak within 20 days)
    #   (need vol_ma50 which needs 50 data points before the window start)

    for surge_start in range(today_idx - 25, today_idx - 9):
        surge_end = surge_start + 4  # 5-day window inclusive: start..start+4

        # Condition 6: surge end (peak) must be within last 20 trading days
        if today_idx - surge_end > 20:
            continue

        # Check volume ma50 is available at surge_start
        if pd.isna(df["vol_ma50"].iloc[surge_start]):
            continue

        ma50_vol = df["vol_ma50"].iloc[surge_start]

        # Check 5-day return > 20%
        surge_open = df["open"].iloc[surge_start]
        surge_ret = (df["close"].iloc[surge_end] - surge_open) / surge_open

        if surge_ret <= 0.20:
            continue

        # Surge high: only consider days with daily gain > 5%,
        # take the highest close among those days
        surge_high_close = None
        for j in range(surge_start, surge_end + 1):
            if j > surge_start:
                day_ret = (df["close"].iloc[j] - df["close"].iloc[j-1]) / df["close"].iloc[j-1]
            else:
                # First day: compare with previous close
                day_ret = (df["close"].iloc[j] - df["close"].iloc[j-1]) / df["close"].iloc[j-1]
            if day_ret > 0.05:
                if surge_high_close is None or df["close"].iloc[j] > surge_high_close:
                    surge_high_close = df["close"].iloc[j]
        
        if surge_high_close is None:
            continue

        # Condition 2: volume check
        # Up days (close > open): volume > 1.5x MA50
        # Down days (close < open): volume > 0.8x MA50
        vol_ok = True
        for j in range(surge_start, surge_end + 1):
            if df["close"].iloc[j] > df["open"].iloc[j]:
                if df["volume"].iloc[j] <= 1.5 * ma50_vol:
                    vol_ok = False
                    break
            else:
                if df["volume"].iloc[j] <= 0.8 * ma50_vol:
                    vol_ok = False
                    break
        if not vol_ok:
            continue

        # ── Condition 3+4: Pullback phase ──
        # Pullback starts immediately after surge_end.
        # New constraint: during pullback period, NO close can exceed surge_high * 1.05
        # (the stock can't "run away" before pulling back)
        # At least 5 days from surge_end to pullback low
        # Pullback low must stay above 50% retracement of surge range
        
        surge_range = surge_high_close - surge_open
        max_allowed_close = surge_high_close * 1.05
        half_retrace = surge_open + surge_range * 0.5

        # Scan from surge_end+1 to today-1
        pullback_low = None
        pullback_low_idx = None
        
        for j in range(surge_end + 1, today_idx):
            close_j = df["close"].iloc[j]
            # Check: no close exceeds surge_high * 1.05
            if close_j > max_allowed_close:
                # Price ran away too far — disqualify this surge window
                break
            if pullback_low is None or close_j < pullback_low:
                pullback_low = close_j
                pullback_low_idx = j
        
        # If the loop broke early, pullback_low_idx won't reach min required
        if pullback_low_idx is None:
            continue
        
        pullback_days = pullback_low_idx - surge_end
        if pullback_days < 5:
            continue
        
        # Verify pullback overall trend is down (low < surge_end close)
        if pullback_low >= df["close"].iloc[surge_end]:
            continue
        
        # Check 50% retracement holds
        if pullback_low < half_retrace:
            continue

        # ── Quality filters (from backtest analysis) ──
        # Shallow pullback: < 25% of surge range
        pullback_pct_val = (surge_high_close - pullback_low) / surge_range
        if pullback_pct_val > 0.25:
            continue

        # Slow pullback: average daily decline < 0.5 (absolute price)
        pb_speed = (surge_high_close - pullback_low) / pullback_days
        if pb_speed > 0.5:
            continue

        # Condition 5: today's close > surge high close
        # AND yesterday's close <= surge high (today is the FIRST breakout day)
        yesterday_close = df["close"].iloc[today_idx - 1]
        if today_close > surge_high_close and yesterday_close <= surge_high_close:
            return {
                "code": code,
                "surge_start": str(df.index[surge_start].date()),
                "surge_end": str(df.index[surge_end].date()),
                "surge_ret": round(surge_ret * 100, 2),
                "surge_high": round(surge_high_close, 2),
                "surge_low": round(surge_open, 2),
                "pullback_low": round(pullback_low, 2),
                "pullback_date": str(df.index[pullback_low_idx].date()),
                "pullback_days": pullback_days,
                "pullback_pct": round((surge_high_close - pullback_low) / surge_range * 100, 2),
                "today_close": round(today_close, 2),
                "today_date": str(df.index[today_idx].date()),
            }

    return None

def main():
    print("加载股票列表...")
    stocks_list = get_stock_list()
    total = len(stocks_list)
    print(f"共 {total} 只股票待扫描")

    print("构建名称映射...")
    name_map = build_name_map()
    print(f"名称映射: {len(name_map)} 条")

    reader = Reader.factory(market="std", tdxdir=TDX_DIR)

    results = []
    start_time = time.time()

    for i, code in enumerate(stocks_list):
        res = check_stock(reader, code)
        if res:
            name = name_map.get(code, code)
            res["name"] = name
            results.append(res)
            print(f"  [{i+1}/{total}] ✓ {code} {name}")

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate
            print(f"  进度: {i+1}/{total} | 已找到: {len(results)} | 速度: {rate:.0f}只/秒 | 剩余: {eta:.0f}秒")

    elapsed = time.time() - start_time

    print(f"\n{'='*100}")
    print(f"拉升+回调+突破 形态扫描结果")
    print(f"{'='*100}")
    print(f"总股票: {total} | 满足条件: {len(results)} | 用时: {elapsed:.0f}秒")
    print()

    if not results:
        print("无满足条件的股票")
        return

    print(f"{'代码':<8} {'名称':<12} {'拉升起点':<12} {'拉升终点':<12} {'涨幅%':>8} {'拉升低':>8} {'拉升高':>8} {'回调低':>8} {'回调%':>8} {'今收':>8}")
    print("-" * 120)
    for r in results:
        print(f"{r['code']:<8} {r['name']:<12} {r['surge_start']:<12} {r['surge_end']:<12} {r['surge_ret']:>8.2f} {r['surge_low']:>8.2f} {r['surge_high']:>8.2f} {r['pullback_low']:>8.2f} {r['pullback_pct']:>8.2f} {r['today_close']:>8.2f}")

    print(f"\n详细:")
    for r in results:
        print(f"  {r['code']} {r['name']}:")
        print(f"    拉升: {r['surge_start']}~{r['surge_end']} 涨{r['surge_ret']}% ({r['surge_low']}→{r['surge_high']})")
        print(f"    回调: 至{r['pullback_date']} 低点{r['pullback_low']} (回调{r['pullback_pct']}% 未破半)")
        print(f"    突破: 今日{r['today_date']}收盘{r['today_close']} 站上拉升高点{r['surge_high']}")

    # Save
    out_path = Path("/mnt/c/Users/Sky.Lu/Desktop/output/surge_pullback_breakout_scan.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"拉升+回调+突破 形态扫描结果\n")
        f.write(f"扫描日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"总股票: {total} | 满足: {len(results)}\n\n")
        for r in results:
            f.write(f"{r['code']} {r['name']}: 拉升{r['surge_start']}~{r['surge_end']} +{r['surge_ret']}%, "
                    f"回调至{r['pullback_date']} 低{r['pullback_low']}(-{r['pullback_pct']}%), "
                    f"今收{r['today_close']} 突破高{r['surge_high']}\n")
    print(f"\n结果已保存到: {out_path}")

if __name__ == "__main__":
    main()
