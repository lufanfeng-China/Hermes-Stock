#!/usr/bin/env python3
"""
回测 002250 — MA10上穿MA60 + MA10连续3日上升 策略
信号: MA10上穿MA60 且 最近3日MA10单调上升
买入: 信号次日开盘价
卖出: MA10下穿MA60 次日开盘价
回测区间: 2015-01-01 至今
"""

import pandas as pd
import numpy as np
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"
SYMBOL = "603288"
NAME = "海天味业"

reader = Reader.factory(market="std", tdxdir=TDX_DIR)
df = reader.daily(SYMBOL)

if df is None or len(df) < 70:
    print("数据不足")
    exit(1)

# Filter from 2015-01-01
df = df[df.index >= "2015-01-01"].copy()

if len(df) < 70:
    print("2015年后数据不足")
    exit(1)

# Calculate MAs
df["ma10"] = df["close"].rolling(10).mean()
df["ma60"] = df["close"].rolling(60).mean()

# Drop NaN rows (first 59 days)
valid = df.dropna(subset=["ma10", "ma60"]).copy()
print(f"数据区间: {valid.index[0].date()} ~ {valid.index[-1].date()}，共 {len(valid)} 个交易日")

# Signal: MA10上穿MA60 (today ma10 > ma60, yesterday ma10 <= ma60)
valid["cross_up"] = (valid["ma10"] > valid["ma60"]) & (valid["ma10"].shift(1) <= valid["ma60"].shift(1))

# MA10 rising for 3 consecutive days
valid["ma10_rising_3d"] = (
    (valid["ma10"] > valid["ma10"].shift(1)) &
    (valid["ma10"].shift(1) > valid["ma10"].shift(2)) &
    (valid["ma10"].shift(2) > valid["ma10"].shift(3))
)

# MA60 rising for 5 consecutive days
valid["ma60_rising_5d"] = (
    (valid["ma60"] > valid["ma60"].shift(1)) &
    (valid["ma60"].shift(1) > valid["ma60"].shift(2)) &
    (valid["ma60"].shift(2) > valid["ma60"].shift(3)) &
    (valid["ma60"].shift(3) > valid["ma60"].shift(4)) &
    (valid["ma60"].shift(4) > valid["ma60"].shift(5))
)

# Death cross: MA10下穿MA60
valid["cross_down"] = (valid["ma10"] < valid["ma60"]) & (valid["ma10"].shift(1) >= valid["ma60"].shift(1))

# Combined signal
valid["signal"] = valid["cross_up"] & valid["ma10_rising_3d"] & valid["ma60_rising_5d"]

# Find signal dates
signal_dates = valid[valid["signal"]].index

# Find death cross dates
death_dates = valid[valid["cross_down"]].index

# Simulate trades
trades = []
holding = False
buy_date = None
buy_price = None
buy_date_str = None
buy_idx = None

for i in range(len(valid)):
    date = valid.index[i]
    
    if not holding and valid["signal"].iloc[i]:
        # Buy next day
        if i + 1 < len(valid):
            buy_date = valid.index[i + 1]
            buy_price = valid["open"].iloc[i + 1]
            buy_date_str = str(buy_date.date())
            buy_idx = i + 1
            holding = True
            signal_date = str(date.date())
    
    if holding and valid["cross_down"].iloc[i]:
        # Sell next day
        if i + 1 < len(valid):
            sell_date = valid.index[i + 1]
            sell_price = valid["open"].iloc[i + 1]
            
            ret = (sell_price / buy_price - 1) * 100
            hold_days = i + 1 - buy_idx
            
            # Also calculate max profit and max loss during hold
            hold_prices = valid.iloc[buy_idx:i+1]
            max_price = hold_prices["high"].max()
            min_price = hold_prices["low"].min()
            max_ret = (max_price / buy_price - 1) * 100
            max_loss = (min_price / buy_price - 1) * 100
            
            trades.append({
                "signal_date": signal_date,
                "buy_date": buy_date_str,
                "buy_price": round(buy_price, 2),
                "sell_date": str(sell_date.date()),
                "sell_price": round(sell_price, 2),
                "hold_days": hold_days,
                "ret_pct": round(ret, 2),
                "max_ret_pct": round(max_ret, 2),
                "max_loss_pct": round(max_loss, 2),
            })
            holding = False
            buy_date = None
            buy_price = None
            buy_idx = None

# If still holding at end
if holding and buy_price is not None:
    last_date = valid.index[-1]
    last_close = valid["close"].iloc[-1]
    hold_days = len(valid) - 1 - buy_idx
    ret = (last_close / buy_price - 1) * 100

    hold_prices = valid.iloc[buy_idx:]
    max_price = hold_prices["high"].max()
    min_price = hold_prices["low"].min()
    max_ret = (max_price / buy_price - 1) * 100
    max_loss = (min_price / buy_price - 1) * 100

    trades.append({
        "signal_date": signal_date,
        "buy_date": buy_date_str,
        "buy_price": round(buy_price, 2),
        "sell_date": f"持有中({str(last_date.date())})",
        "sell_price": round(last_close, 2),
        "hold_days": hold_days,
        "ret_pct": round(ret, 2),
        "max_ret_pct": round(max_ret, 2),
        "max_loss_pct": round(max_loss, 2),
    })

# ==== Results ====
print(f"\n{'='*90}")
print(f"{SYMBOL} {NAME} — MA10金叉MA60 + MA10连升3日 + MA60连升5日 回测结果")
print(f"{'='*90}")
print(f"回测区间: {valid.index[0].date()} ~ {valid.index[-1].date()}")
print(f"总交易天数: {len(valid)}")
print(f"买入信号次数: {len(signal_dates)}")
print(f"完成交易: {len(trades)}")

if not trades:
    print("无交易记录")
    exit()

print(f"\n{'序号':>4} {'信号日':<12} {'买入日':<12} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'持有天':>6} {'收益%':>8} {'最大盈%':>8} {'最大亏%':>8}")
print("-" * 100)

win_count = 0
total_ret = 0
for idx, t in enumerate(trades, 1):
    print(f"{idx:>4} {t['signal_date']:<12} {t['buy_date']:<12} {t['buy_price']:>8.2f} {t['sell_date']:<12} {t['sell_price']:>8.2f} {t['hold_days']:>6} {t['ret_pct']:>8.2f} {t['max_ret_pct']:>8.2f} {t['max_loss_pct']:>8.2f}")
    if "持有中" not in t["sell_date"]:
        total_ret += t["ret_pct"]
        if t["ret_pct"] > 0:
            win_count += 1

closed_trades = [t for t in trades if "持有中" not in t["sell_date"]]
n_closed = len(closed_trades)

# Monthly breakdown
print(f"\n{'='*90}")
print(f"月度持仓分布 (持有期间每月统计)")
print(f"{'='*90}")
print(f"{'年月':<8} {'笔数':>4} {'持有日期列表'}")
all_months = {}
for t in trades:
    for i in range(t["hold_days"]):
        # approximate month from buy_date + i days
        buy_dt = pd.Timestamp(t["buy_date"])
        dt = buy_dt + pd.Timedelta(days=i)
        # skip weekends roughly
        month_key = dt.strftime("%Y-%m")
        if month_key not in all_months:
            all_months[month_key] = []
        all_months[month_key].append(t["buy_date"])

for m in sorted(all_months.keys()):
    dates_list = sorted(set(all_months[m]))
    if len(dates_list) <= 3:
        dates_str = ", ".join(dates_list)
    else:
        dates_str = ", ".join(dates_list[:3]) + f" ...({len(dates_list)}笔)"
    print(f"{m:<8} {len(all_months[m]):>4}  {dates_str}")

print(f"\n{'='*90}")
print(f"汇总统计")
print(f"{'='*90}")
print(f"已完成交易: {n_closed} 笔")
if n_closed > 0:
    print(f"盈利交易: {win_count} 笔 (胜率 {win_count/n_closed*100:.1f}%)")
    print(f"平均收益: {total_ret/n_closed:.2f}%")
    all_rets = [t["ret_pct"] for t in closed_trades]
    print(f"最大盈利: {max(all_rets):.2f}%")
    print(f"最大亏损: {min(all_rets):.2f}%")
    print(f"中位收益: {np.median(all_rets):.2f}%")

holding_trades = [t for t in trades if "持有中" in t["sell_date"]]
for t in holding_trades:
    print(f"\n当前持有: 买入 {t['buy_date']} @ {t['buy_price']:.2f}, 现价 {t['sell_price']:.2f}, 收益 {t['ret_pct']:.2f}% (持有 {t['hold_days']} 天)")

# Save to file
out_path = f"/mnt/c/Users/Sky.Lu/Desktop/output/backtest_{SYMBOL}_ma10_ma60.txt"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"{SYMBOL} {NAME} — MA10金叉MA60 + MA10连升3日 + MA60连升5日 回测结果\n")
    f.write(f"回测区间: {valid.index[0].date()} ~ {valid.index[-1].date()}\n")
    f.write(f"买入信号次数: {len(signal_dates)}\n")
    f.write(f"完成交易: {len(trades)}\n\n")
    f.write(f"{'序号':>4} {'信号日':<12} {'买入日':<12} {'买入价':>8} {'卖出日':<12} {'卖出价':>8} {'持有天':>6} {'收益%':>8} {'最大盈%':>8} {'最大亏%':>8}\n")
    f.write("-" * 100 + "\n")
    for idx, t in enumerate(trades, 1):
        f.write(f"{idx:>4} {t['signal_date']:<12} {t['buy_date']:<12} {t['buy_price']:>8.2f} {t['sell_date']:<12} {t['sell_price']:>8.2f} {t['hold_days']:>6} {t['ret_pct']:>8.2f} {t['max_ret_pct']:>8.2f} {t['max_loss_pct']:>8.2f}\n")
    if n_closed > 0:
        f.write(f"\n汇总: {n_closed}笔完成, 胜率{win_count/n_closed*100:.1f}%, 均值{total_ret/n_closed:.2f}%\n")
    for t in holding_trades:
        f.write(f"\n当前持有: 买入 {t['buy_date']} @ {t['buy_price']:.2f}, 现价 {t['sell_price']:.2f}, 收益 {t['ret_pct']:.2f}%\n")
print(f"\n结果已保存到: {out_path}")
