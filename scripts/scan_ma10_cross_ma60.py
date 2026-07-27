#!/usr/bin/env python3
"""
扫描全市场 A 股，找同时满足以下条件的股票：
1. MA10 今日上穿 MA60（金叉）
2. 最近 5 个交易日 MA10 单调上涨
"""

import json, time
import pandas as pd
import numpy as np
from pathlib import Path
from mootdx.reader import Reader
from mootdx.quotes import Quotes

TDX_DIR = "/mnt/c/new_tdx64"

def build_name_map():
    """用 mootdx client.stocks() 构建 code->name 映射"""
    client = Quotes.factory(market="std")
    names = {}
    # SZ 深圳个股: 000-004, 300-301
    df_sz = client.stocks(market=0)
    mask = df_sz["code"].astype(str).str.match(r'^(00[0-4]|30[01])\d{3}$')
    for _, row in df_sz[mask].iterrows():
        names[str(row["code"])] = str(row["name"]).strip().replace("\x00", "")
    # SH 上海个股: 600-609, 688-689
    df_sh = client.stocks(market=1)
    mask = df_sh["code"].astype(str).str.match(r'^(6[0-9]{2}|68[89])\d{3}$')
    for _, row in df_sh[mask].iterrows():
        code = str(row["code"])
        if code not in names:
            names[code] = str(row["name"]).strip().replace("\x00", "")
    return names

def get_stock_list():
    """从项目数据集获取股票列表（沪深北A股，排除ST/指数/ETF）"""
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
        rows.append((code, market))
    return rows

def check_stock(reader, code, market):
    try:
        df = reader.daily(code)
        if df is None or len(df) < 65:
            return None
    except Exception:
        return None

    df = df.tail(65).copy()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    if len(df) < 61:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    today_date = df.index[-1]

    if pd.isna(today["ma10"]) or pd.isna(today["ma60"]):
        return None
    if pd.isna(yesterday["ma10"]) or pd.isna(yesterday["ma60"]):
        return None

    # 条件1: MA10 上穿 MA60
    cross_up = (today["ma10"] > today["ma60"]) and (yesterday["ma10"] <= yesterday["ma60"])
    if not cross_up:
        return None

    # 条件2: 最近5天 MA10 单调上涨
    ma10_last5 = df["ma10"].iloc[-5:].values
    if len(ma10_last5) < 5 or pd.isna(ma10_last5).any():
        return None
    if not all(ma10_last5[i] < ma10_last5[i+1] for i in range(len(ma10_last5)-1)):
        return None

    return {
        "code": code,
        "date": str(today_date.date()),
        "close": round(today["close"], 2),
        "ma10": round(today["ma10"], 2),
        "ma60": round(today["ma60"], 2),
        "ma10_5d": [round(x, 2) for x in ma10_last5],
    }

def main():
    print("构建股票名称映射...")
    name_map = build_name_map()
    print(f"名称映射: {len(name_map)} 条")

    print("加载股票列表...")
    stocks = get_stock_list()
    total = len(stocks)
    print(f"共 {total} 只股票待扫描")

    reader = Reader.factory(market="std", tdxdir=TDX_DIR)

    results = []
    start_time = time.time()

    for i, (code, market) in enumerate(stocks):
        res = check_stock(reader, code, market)
        if res:
            name = name_map.get(code, code)
            res["name"] = name
            results.append(res)
            print(f"  [{i+1}/{total}] ✓ {code} {name} 满足条件")

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate
            print(f"  进度: {i+1}/{total} | 已找到: {len(results)} | 速度: {rate:.0f}只/秒 | 预计剩余: {eta:.0f}秒")

    elapsed = time.time() - start_time
    print(f"\n====== 扫描完成 ======")
    print(f"总用时: {elapsed:.0f}秒 | 总股票: {total} | 满足条件: {len(results)}")
    print(f"\n满足条件的股票 ({len(results)}只):")
    print(f"{'代码':<8} {'名称':<14} {'日期':<12} {'收盘价':>8} {'MA10':>8} {'MA60':>8}")
    print("-" * 70)
    for r in results:
        print(f"{r['code']:<8} {r['name']:<14} {r['date']:<12} {r['close']:>8.2f} {r['ma10']:>8.2f} {r['ma60']:>8.2f}")

    # 保存到文件
    out_path = Path("/mnt/c/Users/Sky.Lu/Desktop/output/ma10_cross_ma60_scan.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"MA10金叉MA60 + MA10连续5日上涨 扫描结果\n")
        f.write(f"扫描日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"总股票: {total} | 满足条件: {len(results)}\n")
        f.write(f"\n{'代码':<8} {'名称':<14} {'日期':<12} {'收盘价':>8} {'MA10':>8} {'MA60':>8} {'MA10近5日'}\n")
        f.write("-" * 110 + "\n")
        for r in results:
            ma10_str = " → ".join(f"{x:.2f}" for x in r["ma10_5d"])
            f.write(f"{r['code']:<8} {r['name']:<14} {r['date']:<12} {r['close']:>8.2f} {r['ma10']:>8.2f} {r['ma60']:>8.2f} {ma10_str}\n")
    print(f"\n结果已保存到: {out_path}")

if __name__ == "__main__":
    main()
