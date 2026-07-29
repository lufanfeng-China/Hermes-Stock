#!/usr/bin/env python3
"""2560 simplified strategy: 3/6/10m, all start years, chronological T+1 MTM."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Reuse the already-validated CSI300 capture, indicator preparation and signal
# definition from the eight-signal comparison.  This script runs only s4.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from backtest_csi300_eight_signals_mtm_v4 import (  # noqa: E402
    LOT_CASH,
    TDX_DIR,
    load_constituents,
    load_data,
    make_calendar,
)

OUTPUT = Path("/mnt/c/Users/Sky.Lu/Desktop/output/2560简化版_CSI300_300万600万1000万_逐起点年度MTM_v5_20260728.txt")
CAPITALS = (3_000_000.0, 6_000_000.0, 10_000_000.0)
START_YEARS = range(2012, 2027)
SCHEME = "s4"


@dataclass
class Position:
    shares: int
    cost: float
    entry_date: pd.Timestamp
    armed: bool = False


def simulate(start_year: int, bars, next_date, end: pd.Timestamp, initial_cash: float):
    """One chronological cash-conserving 2560-simplified portfolio run."""
    start = pd.Timestamp(f"{start_year}-01-01")
    cash = initial_cash
    positions: dict[str, Position] = {}
    latest_close: dict[str, float] = {}
    pending_buy: dict[pd.Timestamp, list[tuple[str, str]]] = defaultdict(list)
    pending_sell: dict[pd.Timestamp, set[str]] = defaultdict(set)
    annual_equity: dict[int, float] = {}
    stats = Counter()
    dates = [date for date in sorted(bars) if start <= date <= end]

    for date_index, date in enumerate(dates):
        today = bars[date]

        # T+1 exits first: their proceeds are usable in the same opening auction.
        for code in sorted(pending_sell.pop(date, set())):
            position = positions.pop(code, None)
            if position is None or code not in today:
                continue
            open_price = today[code][0]
            cash += position.shares * open_price
            stats["sells"] += 1
            stats["closed_holding_days_sum"] += (date - position.entry_date).days

        # T+1 entries/adds use only actual cash available after opening exits.
        for code, action in sorted(pending_buy.pop(date, [])):
            if code not in today:
                continue
            open_price = today[code][0]
            shares = int(LOT_CASH / open_price) if open_price > 0 else 0
            cost = shares * open_price
            if shares <= 0 or cost > cash + 1e-8:
                stats["cash_rejected"] += 1
                continue
            if action == "new":
                if code in positions:
                    continue
                positions[code] = Position(shares, cost, date)
                cash -= cost
                stats["entries"] += 1
            elif action == "add":
                position = positions.get(code)
                if position is None:
                    continue
                position.shares += shares
                position.cost += cost
                cash -= cost
                stats["adds"] += 1

        # Close-time state update: +20% arms, then dead cross or <=+15% exits.
        for code, (_, close, dead, signals) in today.items():
            latest_close[code] = close
            position = positions.get(code)
            if position is not None and position.cost > 0:
                pnl = close * position.shares / position.cost - 1.0
                if not position.armed and pnl > 0.20:
                    position.armed = True
                    stats["armed"] += 1
                elif position.armed and (dead or pnl <= 0.15):
                    next_bar = next_date.get((code, date))
                    if next_bar is not None and next_bar <= end:
                        pending_sell[next_bar].add(code)
                        stats["sell_signals"] += 1

            # Signal is available after close, so it can only execute next bar.
            if not signals[SCHEME]:
                continue
            stats["raw_signals"] += 1
            next_bar = next_date.get((code, date))
            if next_bar is None or next_bar > end or code in pending_sell.get(next_bar, set()):
                continue
            if position is None:
                pending_buy[next_bar].append((code, "new"))
            elif position.cost > 0 and close * position.shares / position.cost - 1.0 <= -0.20:
                pending_buy[next_bar].append((code, "add"))

        # Calendar-year final available trade-date MTM snapshot.
        next_year = dates[date_index + 1].year if date_index + 1 < len(dates) else None
        if next_year != date.year:
            market_value = sum(
                position.shares * latest_close.get(code, 0.0)
                for code, position in positions.items()
            )
            annual_equity[date.year] = cash + market_value

    final_equity = annual_equity.get(end.year, initial_cash)
    annual_returns: dict[int, float] = {}
    previous_equity = initial_cash
    for year in range(start_year, end.year + 1):
        if year not in annual_equity:
            continue
        annual_returns[year] = (annual_equity[year] / previous_equity - 1.0) * 100.0
        previous_equity = annual_equity[year]
    stats["open_positions"] = len(positions)
    return annual_returns, annual_equity, final_equity, stats


def fmt_return(value: float | None) -> str:
    return f"{value:+6.2f}%" if value is not None else "   —   "


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    codes = load_constituents()
    stock_data = load_data(codes)
    if len(stock_data) < 250:
        raise RuntimeError(f"Only {len(stock_data)} usable CSI300 histories")
    bars, next_date = make_calendar(stock_data)
    end = max(bars)

    report = [
        "2560简化版：300万 / 600万 / 1000万，各起始年逐自然年 MTM 回测 v5",
        "=" * 88,
        f"数据：当前CSI300固定成分股（幸存者偏差）；本地TDX原始日线；截至 {end.date()}（2026为YTD）。",
        "信号（2560简化版）：MA20>MA60、收盘>MA20、MACD金叉、成交量>MA5成交量；",
        "全局过滤：近最多1200交易日收盘价分位<80%，且 MA20>=MA60；分位至少240交易日。",
        "执行：收盘确认，T+1该股下一交易日开盘成交；单次开仓/补仓目标5万元；按代码排序；不透支；无费税滑点。",
        "补仓：已有仓位且同一信号日收盘总浮亏<=-20%，T+1加一份。",
        "卖出：总浮盈>20%后武装；武装后MACD死叉或总浮盈回落至<=15%，T+1开盘全卖。",
        "年末权益=现金+所有未平仓股票在该年最后可用收盘价的MTM市值。",
        "",
        f"当前CSI300成分股: {len(codes)}；本地可用日线: {len(stock_data)}；单仓目标: {LOT_CASH/10000:.0f}万。",
    ]

    all_results = {}
    for capital in CAPITALS:
        report.extend(["", "=" * 88, f"初始资金：{capital/10000:.0f}万", "起点      " + "  ".join(map(str, range(2012, end.year + 1)))])
        capital_rows = {}
        for start_year in START_YEARS:
            annual_returns, annual_equity, final_equity, stats = simulate(start_year, bars, next_date, end, capital)
            capital_rows[start_year] = (annual_returns, annual_equity, final_equity, stats)
            cells = [fmt_return(annual_returns.get(year)) if year >= start_year else "   —   " for year in range(2012, end.year + 1)]
            report.append(f"{start_year}起始  " + "  ".join(cells))

        report.append("\n逐起点汇总（期末权益为现金+未平仓MTM）：")
        report.append("起点  首年收益  次年收益  累计收益  期末权益  平均已平仓持股天数  原始信号/开仓/补仓/卖出/期末持仓/现金拒绝")
        for start_year, (returns, _, final_equity, stats) in capital_rows.items():
            avg_days = stats["closed_holding_days_sum"] / stats["sells"] if stats["sells"] else 0.0
            report.append(
                f"{start_year}  {fmt_return(returns.get(start_year)):>8}  {fmt_return(returns.get(start_year + 1)):>8}  "
                f"{(final_equity / capital - 1) * 100:+8.2f}%  {final_equity / 10000:9.2f}万  {avg_days:9.1f}天  "
                f"{stats['raw_signals']}/{stats['entries']}/{stats['adds']}/{stats['sells']}/{stats['open_positions']}/{stats['cash_rejected']}"
            )
        all_results[capital] = capital_rows

    report.extend(["", "=" * 88, "2012起始三档资金对比（MTM）：", "资金       期末权益      累计收益   开仓/补仓/卖出/期末持仓/现金拒绝"])
    for capital in CAPITALS:
        _, _, final_equity, stats = all_results[capital][2012]
        report.append(
            f"{capital/10000:>4.0f}万  {final_equity/10000:10.2f}万  {(final_equity/capital-1)*100:+8.2f}%  "
            f"{stats['entries']}/{stats['adds']}/{stats['sells']}/{stats['open_positions']}/{stats['cash_rejected']}"
        )
    OUTPUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
