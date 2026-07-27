#!/usr/bin/env python3
"""
沪深300全量回测 — MA10金叉MA60 + MA10连升3日 + MA60连升5日
信号: MA10上穿MA60 且 MA10连升3日 且 MA60连升5日
买入: 信号次日开盘价
卖出: MA10下穿MA60 次日开盘价
回测区间: 2015-01-01 至今
"""

import os, sys, json, time
import pandas as pd
import numpy as np
from pathlib import Path
from mootdx.reader import Reader
from mootdx.quotes import Quotes

TDX_DIR = "/mnt/c/new_tdx64"

# ── Get CSI 300 constituents ──
def get_csi300_symbols():
    """从缓存文件获取沪深300成分股"""
    cache_path = "/tmp/csi300_constituents.json"
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            codes = json.load(f)
        return sorted(set(str(c) for c in codes))
    
    # Fallback: try akshare
    try:
        import akshare as ak
        df = ak.index_stock_cons_csindex(symbol='000300')
        codes = df['成分券代码'].tolist()
        codes = sorted(set(str(c) for c in codes))
        with open(cache_path, 'w') as f:
            json.dump(codes, f)
        return codes
    except Exception as e:
        print(f"akshare 获取失败: {e}")
        return None

# ── Get stock names ──
def build_name_map():
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

# ── Backtest single stock ──
def backtest_stock(reader, symbol, start_date="2015-01-01"):
    try:
        df = reader.daily(symbol)
    except:
        return None
    
    if df is None or len(df) < 70:
        return None
    
    df = df[df.index >= start_date].copy()
    if len(df) < 70:
        return None
    
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    valid = df.dropna(subset=["ma10", "ma60"]).copy()
    
    if len(valid) < 5:
        return None
    
    valid["cross_up"] = (valid["ma10"] > valid["ma60"]) & (valid["ma10"].shift(1) <= valid["ma60"].shift(1))
    valid["ma10_rising_3d"] = (
        (valid["ma10"] > valid["ma10"].shift(1)) &
        (valid["ma10"].shift(1) > valid["ma10"].shift(2)) &
        (valid["ma10"].shift(2) > valid["ma10"].shift(3))
    )
    valid["ma60_rising_5d"] = (
        (valid["ma60"] > valid["ma60"].shift(1)) &
        (valid["ma60"].shift(1) > valid["ma60"].shift(2)) &
        (valid["ma60"].shift(2) > valid["ma60"].shift(3)) &
        (valid["ma60"].shift(3) > valid["ma60"].shift(4)) &
        (valid["ma60"].shift(4) > valid["ma60"].shift(5))
    )
    valid["cross_down"] = (valid["ma10"] < valid["ma60"]) & (valid["ma10"].shift(1) >= valid["ma60"].shift(1))
    valid["signal"] = valid["cross_up"] & valid["ma10_rising_3d"] & valid["ma60_rising_5d"]
    
    trades = []
    holding = False
    buy_date = buy_price = buy_idx = None
    signal_date = None
    
    for i in range(len(valid)):
        if not holding and valid["signal"].iloc[i]:
            if i + 1 < len(valid):
                buy_date = valid.index[i + 1]
                buy_price = valid["open"].iloc[i + 1]
                buy_idx = i + 1
                holding = True
                signal_date = str(valid.index[i].date())
        
        if holding and valid["cross_down"].iloc[i]:
            if i + 1 < len(valid):
                sell_date = valid.index[i + 1]
                sell_price = valid["open"].iloc[i + 1]
                ret = (sell_price / buy_price - 1) * 100
                hold_days = i + 1 - buy_idx
                
                hold_prices = valid.iloc[buy_idx:i+1]
                max_ret = (hold_prices["high"].max() / buy_price - 1) * 100
                min_ret = (hold_prices["low"].min() / buy_price - 1) * 100
                
                trades.append({
                    "symbol": symbol,
                    "signal_date": signal_date,
                    "buy_date": str(buy_date.date()),
                    "buy_price": round(buy_price, 2),
                    "sell_date": str(sell_date.date()),
                    "sell_price": round(sell_price, 2),
                    "hold_days": hold_days,
                    "ret_pct": round(ret, 2),
                    "max_ret_pct": round(max_ret, 2),
                    "max_loss_pct": round(min_ret, 2),
                })
                holding = False
    
    # If still holding
    if holding and buy_price is not None:
        last_date = valid.index[-1]
        last_close = valid["close"].iloc[-1]
        hold_days = len(valid) - 1 - buy_idx
        ret = (last_close / buy_price - 1) * 100
        hold_prices = valid.iloc[buy_idx:]
        max_ret = (hold_prices["high"].max() / buy_price - 1) * 100
        min_ret = (hold_prices["low"].min() / buy_price - 1) * 100
        trades.append({
            "symbol": symbol,
            "signal_date": signal_date,
            "buy_date": str(buy_date.date()),
            "buy_price": round(buy_price, 2),
            "sell_date": f"持有中({str(last_date.date())})",
            "sell_price": round(last_close, 2),
            "hold_days": hold_days,
            "ret_pct": round(ret, 2),
            "max_ret_pct": round(max_ret, 2),
            "max_loss_pct": round(min_ret, 2),
        })
    
    return trades if trades else None

# ── Main ──
def main():
    print("获取沪深300成分股...")
    symbols = get_csi300_symbols()
    if not symbols:
        print("ERROR: 无法获取沪深300成分股")
        sys.exit(1)
    print(f"沪深300成分股: {len(symbols)} 只")
    
    print("构建名称映射...")
    name_map = build_name_map()
    print(f"名称映射: {len(name_map)} 条")
    
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    
    all_trades = []
    empty_stocks = 0
    start_time = time.time()
    
    for i, sym in enumerate(symbols):
        trades = backtest_stock(reader, sym)
        if trades:
            all_trades.extend(trades)
        else:
            empty_stocks += 1
        
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (len(symbols) - i - 1) / rate
            print(f"  进度: {i+1}/{len(symbols)} | 交易: {len(all_trades)} | 速度: {rate:.1f}只/秒 | 剩余: {eta:.0f}秒")
    
    elapsed = time.time() - start_time
    
    # Sort by signal date
    all_trades.sort(key=lambda t: t["signal_date"])
    
    # ==== Output ====
    print(f"\n{'='*100}")
    print(f"沪深300 — MA10金叉MA60 + MA10连升3日 + MA60连升5日 统一回测")
    print(f"{'='*100}")
    print(f"回测区间: 2015-01-01 ~ 2026-07-20")
    print(f"成分股: {len(symbols)} 只 | 有交易: {len(symbols) - empty_stocks} 只 | 无信号: {empty_stocks} 只")
    print(f"总信号: {len(all_trades)} 次 | 用时: {elapsed:.0f}秒")
    
    if not all_trades:
        print("无交易记录")
        return
    
    # ── Per-trade table ──
    print(f"\n{'代码':<8} {'名称':<10} {'信号日':<12} {'买入日':<12} {'买入价':>8} {'卖出日':<14} {'卖出价':>8} {'持天':>4} {'收益%':>8} {'最大盈%':>8} {'最大亏%':>8}")
    print("-" * 120)
    
    for t in all_trades:
        name = name_map.get(t["symbol"], t["symbol"])[:10]
        sell_date = t["sell_date"]
        if len(sell_date) > 14:
            sell_date = sell_date[:14]
        print(f"{t['symbol']:<8} {name:<10} {t['signal_date']:<12} {t['buy_date']:<12} {t['buy_price']:>8.2f} {sell_date:<14} {t['sell_price']:>8.2f} {t['hold_days']:>4} {t['ret_pct']:>8.2f} {t['max_ret_pct']:>8.2f} {t['max_loss_pct']:>8.2f}")
    
    # ── Summary stats ──
    closed = [t for t in all_trades if "持有中" not in t["sell_date"]]
    holding_now = [t for t in all_trades if "持有中" in t["sell_date"]]
    
    n_closed = len(closed)
    if n_closed > 0:
        wins = [t for t in closed if t["ret_pct"] > 0]
        losses = [t for t in closed if t["ret_pct"] <= 0]
        rets = [t["ret_pct"] for t in closed]
        
        print(f"\n{'='*100}")
        print(f"汇总统计")
        print(f"{'='*100}")
        print(f"已完成交易: {n_closed} 笔")
        print(f"盈利: {len(wins)} 笔 / 亏损: {len(losses)} 笔")
        print(f"胜率: {len(wins)/n_closed*100:.1f}%")
        print(f"总收益: {sum(rets):.2f}%")
        print(f"平均收益: {np.mean(rets):.2f}%")
        print(f"中位收益: {np.median(rets):.2f}%")
        print(f"标准差: {np.std(rets):.2f}%")
        print(f"最大盈利: {max(rets):.2f}%")
        print(f"最大亏损: {min(rets):.2f}%")
        print(f"平均持有天数: {np.mean([t['hold_days'] for t in closed]):.0f} 天")
        print(f"盈利交易平均持有: {np.mean([t['hold_days'] for t in wins]):.0f} 天")
        print(f"亏损交易平均持有: {np.mean([t['hold_days'] for t in losses]):.0f} 天")
    
    if holding_now:
        print(f"\n当前持有: {len(holding_now)} 笔")
        for t in holding_now:
            name = name_map.get(t["symbol"], t["symbol"])
            print(f"  {t['symbol']} {name}: 买入 {t['buy_date']} @ {t['buy_price']:.2f}, 现价 {t['sell_price']:.2f}, 收益 {t['ret_pct']:.2f}% ({t['hold_days']}天)")
    
    # ── Monthly breakdown ──
    print(f"\n{'='*100}")
    print(f"月度持仓分布")
    print(f"{'='*100}")
    monthly = {}
    for t in closed:
        buy_dt = pd.Timestamp(t["buy_date"])
        sell_dt = pd.Timestamp(t["sell_date"])
        # approximate months covered
        cur = pd.Timestamp(year=buy_dt.year, month=buy_dt.month, day=1)
        end = pd.Timestamp(year=sell_dt.year, month=sell_dt.month, day=1)
        while cur <= end:
            mkey = cur.strftime("%Y-%m")
            if mkey not in monthly:
                monthly[mkey] = 0
            monthly[mkey] += 1
            # next month
            if cur.month == 12:
                cur = pd.Timestamp(year=cur.year + 1, month=1, day=1)
            else:
                cur = pd.Timestamp(year=cur.year, month=cur.month + 1, day=1)
    
    for m in sorted(monthly.keys()):
        bar = "█" * min(monthly[m], 60)
        print(f"  {m}: {monthly[m]:>3} 笔 {bar}")
    
    # ── Save ──
    out_path = Path("/mnt/c/Users/Sky.Lu/Desktop/output/backtest_hs300_ma10_ma60.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"沪深300 — MA10金叉MA60 + MA10连升3日 + MA60连升5日 统一回测\n")
        f.write(f"回测区间: 2015-01-01 ~ 2026-07-20\n")
        f.write(f"成分股: {len(symbols)} 只\n")
        f.write(f"总信号: {len(all_trades)} 次\n\n")
        f.write(f"{'代码':<8} {'名称':<10} {'信号日':<12} {'买入日':<12} {'买入价':>8} {'卖出日':<14} {'卖出价':>8} {'持天':>4} {'收益%':>8}\n")
        f.write("-" * 110 + "\n")
        for t in all_trades:
            name = name_map.get(t["symbol"], t["symbol"])[:10]
            f.write(f"{t['symbol']:<8} {name:<10} {t['signal_date']:<12} {t['buy_date']:<12} {t['buy_price']:>8.2f} {t['sell_date']:<14} {t['sell_price']:>8.2f} {t['hold_days']:>4} {t['ret_pct']:>8.2f}\n")
        if n_closed > 0:
            f.write(f"\n汇总: {n_closed}笔, 胜率{len(wins)/n_closed*100:.1f}%, 均值{np.mean(rets):.2f}%, 中位{np.median(rets):.2f}%\n")
    print(f"\n结果已保存到: {out_path}")

if __name__ == "__main__":
    main()
