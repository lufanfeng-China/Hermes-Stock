#!/usr/bin/env python3
"""CSI300 seven-signal portfolio backtest with chronological T+1 execution and MTM annual returns.

Research defaults (explicit because the request did not quantify them):
- Current CSI300 constituents (survivorship bias; not historical constituent membership).
- Raw local TDX daily bars, no fees/slippage.
- Global "non-high": trailing 1,200-trading-day close percentile < 80%.
- Global "non-bear": MA20 >= MA60.
- Scheme 2 overrides the percentile condition with the requested < 40%.
- Each initial entry/add is one 50,000 CNY target lot; initial cash is 3,000,000 CNY.
- Add only when a close-generated repeat signal finds aggregate position P&L <= -20%.
- Arm exits only when aggregate position P&L > +20%; after arming, sell all T+1 open
  on a MACD dead cross or a close P&L <= +15%.

A signal is known at the close and entered at the symbol's next available daily open.
Year-end equity is cash plus every still-open holding marked at its latest close.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
from mootdx.reader import Reader

TDX_DIR = "/mnt/c/new_tdx64"
INITIAL_CASH = 3_000_000.0
LOT_CASH = 50_000.0
OUTPUT = Path("/mnt/c/Users/Sky.Lu/Desktop/output/CSI300_八方案_含极值金叉_逐起点年度MTM_含平均持股天数_v4_20260728.txt")
START_YEARS = range(2012, 2027)
PERCENTILE_WINDOW = 1200
# Local TDX histories begin around 2011 for many stocks.  Require one trading
# year before the percentile filter is usable, then extend the lookback toward
# five years as bars accumulate so 2012-start tests can actually trade.
PERCENTILE_MIN_PERIODS = 240
GLOBAL_HIGH_PERCENTILE_MAX = 0.80

SCHEME_NAMES = {
    "s1": "方案1_MACD零轴附近金叉",
    "s2": "方案2_20日新高突破",
    "s3": "方案3_20日均线首次反弹",
    "s4": "方案4_2560简化版",
    "s5": "方案5_MACD二次金叉",
    "s6": "方案6_缩量回踩20日线",
    "s7": "方案7_均线多头排列首次金叉",
    "s8": "方案8_MACD极值金叉",
}


@dataclass
class Position:
    shares: int
    cost: float
    entry_date: pd.Timestamp
    armed: bool = False


def load_constituents() -> list[str]:
    """Load the captured current official CSI300 list, with a network fallback."""
    cache = Path("data/derived/datasets/final/csi300_constituents_current_20260728.json")
    if cache.exists():
        codes = sorted({str(v).zfill(6) for v in json.loads(cache.read_text(encoding="utf-8"))})
    else:
        data = ak.index_stock_cons_csindex(symbol="000300")
        codes = sorted({str(v).zfill(6) for v in data["成分券代码"].tolist()})
    if len(codes) != 300:
        raise RuntimeError(f"Expected 300 CSI300 constituents; got {len(codes)}")
    return codes


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    ma20 = close.rolling(20).mean()
    ma10 = close.rolling(10).mean()
    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()
    vma5 = volume.rolling(5).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    dead = (dif < dea) & (dif.shift(1) >= dea.shift(1))

    # Trailing close percentile: 0=window low, 1=window high.  It deliberately
    # includes today's close because it is a close-time signal filter.
    pct5y = close.rolling(PERCENTILE_WINDOW, min_periods=PERCENTILE_MIN_PERIODS).rank(pct=True)
    global_ok = (pct5y < GLOBAL_HIGH_PERCENTILE_MAX) & (ma20 >= ma60)
    no_golden_prev5 = golden.shift(1).rolling(5, min_periods=5).max().fillna(0).eq(0)
    no_golden_prev60 = golden.shift(1).rolling(60, min_periods=60).max().fillna(0).eq(0)
    hhv20_prior = high.shift(1).rolling(20, min_periods=20).max()

    # Scheme 5: locate the most recent previous golden cross within 30 bars and
    # require DIF to remain above zero from that cross through the current bar.
    g = golden.to_numpy(dtype=bool)
    dv = dif.to_numpy(dtype=float)
    second_cross = np.zeros(len(frame), dtype=bool)
    previous_cross = -1
    for i in range(len(frame)):
        if g[i] and previous_cross >= 0 and i - previous_cross <= 30:
            if np.all(dv[previous_cross : i + 1] > 0):
                second_cross[i] = True
        if g[i]:
            previous_cross = i

    frame["dead"] = dead.fillna(False)
    frame["sig_s1"] = golden & (dif > 0) & ((dif / close * 100) < 2.0) & no_golden_prev5 & global_ok
    frame["sig_s2"] = (close > hhv20_prior) & (volume > vma5) & (pct5y < 0.40) & (ma20 >= ma60)
    frame["sig_s3"] = (close > ma20) & (close.shift(1) <= ma20.shift(1)) & (dif > dea) & global_ok
    frame["sig_s4"] = (ma20 > ma60) & (close > ma20) & golden & (volume > vma5) & global_ok
    frame["sig_s5"] = pd.Series(second_cross, index=frame.index) & global_ok
    frame["sig_s6"] = (close > ma20) & (low <= ma20 * 1.01) & (volume < vma5) & (dif > dea) & global_ok
    frame["sig_s7"] = (ma20 > ma60) & (ma60 > ma120) & golden & no_golden_prev60 & global_ok
    # Existing extreme-GC entry signal, but run under this comparison's shared
    # non-high/non-bear filter and shared add/exit/capital rules.
    normalized_dif = dif / close * 100
    frame["sig_s8"] = golden & (normalized_dif < -1.0) & (ma10 > ma10.shift(1)) & global_ok
    for scheme in SCHEME_NAMES:
        frame[f"sig_{scheme}"] = frame[f"sig_{scheme}"].fillna(False).astype(bool)
    return frame


def load_data(codes: list[str]) -> dict[str, pd.DataFrame]:
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    result: dict[str, pd.DataFrame] = {}
    for n, code in enumerate(codes, 1):
        try:
            frame = reader.daily(code)
        except Exception as exc:
            print(f"SKIP {code}: {exc}", file=sys.stderr)
            continue
        if frame is None or len(frame) < PERCENTILE_MIN_PERIODS + 121:
            continue
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(frame.columns):
            continue
        result[code] = prepare_frame(frame)
        if n % 50 == 0:
            print(f"Loaded and prepared {n}/{len(codes)}")
    return result


def make_calendar(stock_data: dict[str, pd.DataFrame]):
    bars: dict[pd.Timestamp, dict[str, tuple[float, float, bool, dict[str, bool]]]] = defaultdict(dict)
    next_date: dict[tuple[str, pd.Timestamp], pd.Timestamp] = {}
    for code, frame in stock_data.items():
        dates = frame.index
        for i, date in enumerate(dates):
            signals = {scheme: bool(frame[f"sig_{scheme}"].iloc[i]) for scheme in SCHEME_NAMES}
            bars[date][code] = (
                float(frame["open"].iloc[i]), float(frame["close"].iloc[i]), bool(frame["dead"].iloc[i]), signals
            )
            if i + 1 < len(dates):
                next_date[(code, date)] = dates[i + 1]
    return bars, next_date


def simulate(scheme: str, start_year: int, bars, next_date, end: pd.Timestamp):
    start = pd.Timestamp(f"{start_year}-01-01")
    cash = INITIAL_CASH
    positions: dict[str, Position] = {}
    latest_close: dict[str, float] = {}
    pending_buy: dict[pd.Timestamp, list[tuple[str, str]]] = defaultdict(list)
    pending_sell: dict[pd.Timestamp, set[str]] = defaultdict(set)
    stats = Counter()
    annual_equity: dict[int, float] = {}
    dates = [d for d in sorted(bars) if start <= d <= end]

    for date_index, date in enumerate(dates):
        today = bars[date]
        # T+1 exits get first access to the opening auction and cash proceeds.
        for code in sorted(pending_sell.pop(date, set())):
            position = positions.pop(code, None)
            if position is not None and code in today:
                open_price = today[code][0]
                cash += position.shares * open_price
                stats["sells"] += 1
                stats["closed_holding_days_sum"] += (date - position.entry_date).days

        # Process repeat-signal adds and new entries deterministically by code.
        for code, action in sorted(pending_buy.pop(date, [])):
            if code not in today:
                continue
            open_price = today[code][0]
            shares = int(LOT_CASH / open_price) if open_price > 0 else 0
            cost = shares * open_price
            if shares <= 0 or cost > cash:
                stats["cash_rejected"] += 1
                continue
            if action == "new":
                if code in positions:
                    continue
                positions[code] = Position(shares=shares, cost=cost, entry_date=date)
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

        # Close-time pricing / exit-state update.  Any stock with no bar keeps
        # its last available close, thereby avoiding an artificial cost-basis mark.
        for code, (_, close, dead, _) in today.items():
            latest_close[code] = close
            position = positions.get(code)
            if position is None or position.cost <= 0:
                continue
            pnl = close * position.shares / position.cost - 1.0
            if not position.armed and pnl > 0.20:
                position.armed = True
                stats["armed"] += 1
            elif position.armed and (dead or pnl <= 0.15):
                nxt = next_date.get((code, date))
                if nxt is not None and nxt <= end:
                    pending_sell[nxt].add(code)
                    stats["sell_signals"] += 1

        # Signals form after today's close; only the next bar may execute.
        for code, (_, close, _, signals) in today.items():
            if not signals[scheme]:
                continue
            stats["raw_signals"] += 1
            nxt = next_date.get((code, date))
            if nxt is None or nxt > end or code in pending_sell.get(nxt, set()):
                continue
            position = positions.get(code)
            if position is None:
                pending_buy[nxt].append((code, "new"))
            elif position.cost > 0 and close * position.shares / position.cost - 1.0 <= -0.20:
                pending_buy[nxt].append((code, "add"))

        # Snapshot at the final available trading date of each calendar year.
        next_year = dates[date_index + 1].year if date_index + 1 < len(dates) else None
        if next_year != date.year:
            mtm = sum(pos.shares * latest_close.get(code, 0.0) for code, pos in positions.items())
            annual_equity[date.year] = cash + mtm

    final_equity = annual_equity.get(end.year, INITIAL_CASH)
    returns = {}
    previous = INITIAL_CASH
    for year in range(start_year, end.year + 1):
        equity = annual_equity.get(year)
        if equity is None:
            continue
        returns[year] = (equity / previous - 1.0) * 100.0
        previous = equity
    stats["open_positions"] = len(positions)
    return returns, final_equity, stats


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    codes = load_constituents()
    stock_data = load_data(codes)
    # Some current constituents listed after 2012 lack the full 1,200-bar
    # percentile lookback.  Keep the usable historical subset and disclose it
    # rather than silently replacing it with a different universe.
    if len(stock_data) < 250:
        raise RuntimeError(f"Only {len(stock_data)} usable constituents loaded")
    bars, next_date = make_calendar(stock_data)
    end = max(date for date in bars if date.year == max(d.year for d in bars))
    print(f"Universe: current CSI300 {len(codes)} codes; usable local TDX files: {len(stock_data)}; end: {end.date()}")

    report = []
    report.append("CSI300 八方案：逐起点、逐自然年 MTM 回测 v4（含极值金叉、已平仓平均持股天数）")
    report.append("=" * 78)
    report.append(f"数据：当前CSI300成分股（固定当前名单，存在幸存者偏差）；本地TDX原始日线；截至 {end.date()}。")
    report.append("资金：初始300万元；每次初始买入/补仓目标5万元；无手续费、无滑点；不得透支，按代码顺序处理同日订单。")
    report.append("执行：收盘生成信号，T+1该股下一交易日开盘买入；触发卖出后T+1开盘全卖。")
    report.append("全局过滤（本次明确假设）：非高位=收盘价最多近1200交易日分位<80%；非空头=MA20>=MA60。")
    report.append("分位至少需要240个交易日，并随历史累积扩展至1200日；方案2使用用户指定的<40%，替代全局<80%条件。")
    report.append("补仓：已有仓位且本次收盘总浮亏<=-20%时，T+1再加一份；不设止损。")
    report.append("卖出：总浮盈>20%后才武装；武装后MACD死叉或总浮盈回落至<=15%，T+1开盘卖出。")
    report.append("方案8极值金叉信号：DIF上穿DEA、归一化DIF/收盘价<−1%、MA10上升；同样套用上述全局过滤与统一资金/补仓/卖出规则。")
    report.append("年末权益=现金+所有未平仓股票按年末最后可用收盘价的市值（MTM）；2026为YTD。")
    report.append("平均持股天数仅统计已平仓仓位，按实际开仓日到T+1开盘卖出日的自然日差计算；补仓不重置首次开仓日。")
    report.append("")

    all_results = {}
    for scheme, name in SCHEME_NAMES.items():
        print(f"Running {name}")
        report.append("\n" + "=" * 78)
        report.append(name)
        report.append("起点      " + "  ".join(str(y) for y in range(2012, end.year + 1)))
        scheme_rows = {}
        for start_year in START_YEARS:
            returns, final_equity, stats = simulate(scheme, start_year, bars, next_date, end)
            scheme_rows[start_year] = (returns, final_equity, stats)
            columns = []
            for calendar_year in range(2012, end.year + 1):
                if calendar_year < start_year:
                    columns.append("   —   ")
                elif calendar_year in returns:
                    columns.append(f"{returns[calendar_year]:+6.2f}%")
                else:
                    columns.append("   —   ")
            report.append(f"{start_year}起始  " + "  ".join(columns))
        report.append("\n逐起点汇总（最终权益均为现金+未平仓MTM）：")
        report.append("起点  首年收益  次年收益  累计收益  期末权益  已平仓平均持股天数  原始信号/开仓/补仓/卖出/期末持仓")
        for start_year, (returns, final_equity, stats) in scheme_rows.items():
            first = returns.get(start_year)
            second = returns.get(start_year + 1)
            total = (final_equity / INITIAL_CASH - 1.0) * 100.0
            f1 = f"{first:+.2f}%" if first is not None else "—"
            f2 = f"{second:+.2f}%" if second is not None else "—"
            report.append(
                f"{start_year}  {f1:>8}  {f2:>8}  {total:+8.2f}%  {final_equity/10000:9.2f}万  "
                f"{(stats['closed_holding_days_sum'] / stats['sells'] if stats['sells'] else 0.0):10.1f}天  "
                f"{stats['raw_signals']}/{stats['entries']}/{stats['adds']}/{stats['sells']}/{stats['open_positions']}"
            )
        all_results[scheme] = scheme_rows

    report.append("\n" + "=" * 78)
    report.append("2012起始横向比较（用于初筛；不是未来收益承诺）")
    report.append("方案  2012首年  2013次年  期末权益  累计收益  已平仓平均持股天数  开仓  补仓  卖出  期末持仓")
    for scheme, name in SCHEME_NAMES.items():
        returns, final_equity, stats = all_results[scheme][2012]
        report.append(
            f"{name}  {returns.get(2012, float('nan')):+.2f}%  {returns.get(2013, float('nan')):+.2f}%  "
            f"{final_equity/10000:.2f}万  {(final_equity/INITIAL_CASH-1)*100:+.2f}%  "
            f"{(stats['closed_holding_days_sum'] / stats['sells'] if stats['sells'] else 0.0):.1f}天  "
            f"{stats['entries']}  {stats['adds']}  {stats['sells']}  {stats['open_positions']}"
        )

    OUTPUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"WROTE {OUTPUT}")


if __name__ == "__main__":
    main()
