#!/usr/bin/env python3
"""688019 EMA(6, EMA6-18, 108) strategy v2, chronological strict-MTM backtest.

Signal is known only after the daily close; orders fill at the next available
trading-day open.  This is deliberately a single-stock, cash-conserving test.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from mootdx.reader import Reader

CODE = "688019"
TDX_DIR = "/home/lufanfeng/tdx_data"
OUT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
STEM = "688019_EMA6_EMA18_EMA108_H3跌破止损_H3乖离40pct止盈_严格MTM_2012起_20260731_v2"
START = pd.Timestamp("2012-01-01")
INITIAL_CASH = 1_000_000.0
LOT_CASH = 50_000.0
EMA_WARMUP_BARS = 108


@dataclass
class Position:
    shares: int = 0
    cost: float = 0.0
    entry_date: pd.Timestamp | None = None
    entries: list[dict] = field(default_factory=list)



def load_frame() -> pd.DataFrame:
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    frame = reader.daily(CODE)
    if frame is None or frame.empty:
        raise RuntimeError(f"No TDX daily bars for {CODE}")
    frame = frame.sort_index().copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.loc[frame.index >= START, ["open", "close"]].astype(float)
    if len(frame) < EMA_WARMUP_BARS + 2:
        raise RuntimeError(f"Need at least {EMA_WARMUP_BARS + 2} daily bars; got {len(frame)}")
    return frame


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["h1"] = out.close.ewm(span=6, adjust=False).mean()
    out["h2"] = out.h1.ewm(span=18, adjust=False).mean()
    out["h3"] = out.close.ewm(span=108, adjust=False).mean()
    dif = out.close.ewm(span=12, adjust=False).mean() - out.close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    out["macd_dead_cross"] = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    out["h1_cross_h2"] = (out.h1 > out.h2) & (out.h1.shift(1) <= out.h2.shift(1))
    out["h3_slope_positive"] = out.h3 > out.h3.shift(1)
    out["h1_h3_distance"] = out.h1 / out.h3 - 1.0
    out["entry_signal"] = (
        out.h1_cross_h2
        & (out.h1 > out.h3)
        & (out.h2 > out.h3)
        & (out.h1_h3_distance < 0.10)
        & out.h3_slope_positive
    )
    # Avoid treating EMA values formed before a full 108-bar history as tradable.
    out.iloc[: EMA_WARMUP_BARS - 1, out.columns.get_loc("entry_signal")] = False
    return out


def lot_shares(open_price: float) -> int:
    # Exact cash-constrained amount, no fractional shares.  688019 stayed below
    # the 50,000-CNY one-lot budget even at the first valid signal.
    return int(LOT_CASH // open_price) if open_price > 0 else 0


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min()) if not equity.empty else 0.0


def simulate(frame: pd.DataFrame) -> tuple[dict, list[dict], list[dict], list[dict]]:
    cash = INITIAL_CASH
    position: Position | None = None
    pending: dict[pd.Timestamp, list[str]] = {}
    cycles: list[dict] = []
    daily: list[dict] = []
    orders: list[dict] = []
    signal_counts = {"raw_entry_signals": 0, "new_entry_orders_scheduled": 0, "add_orders_scheduled": 0,
                     "sell_orders_scheduled_h3_break": 0, "sell_orders_scheduled_h3_distance_gt_40pct": 0,
                     "cash_rejected": 0}

    dates = list(frame.index)
    for i, date in enumerate(dates):
        row = frame.loc[date]
        open_price, close = float(row.open), float(row.close)

        # T+1 orders execute before that day's close-based decisions.
        for action in pending.pop(date, []):
            if action == "sell":
                if position is None:
                    continue
                proceeds = position.shares * open_price
                cash += proceeds
                pnl_pct = proceeds / position.cost - 1.0
                cycles.append({
                    "entry_date": str(position.entry_date.date()), "exit_date": str(date.date()),
                    "entry_cost": round(position.cost, 2), "exit_proceeds": round(proceeds, 2),
                    "shares": position.shares, "entry_lots": len(position.entries),
                    "return_pct": round(pnl_pct * 100, 4),
                    "holding_trading_days": int(i - dates.index(position.entry_date)),
                    "exit_reason": position.entries[-1].get("scheduled_exit_reason", "unknown"),
                })
                orders.append({"date": str(date.date()), "action": "sell", "price": open_price,
                               "shares": position.shares, "proceeds": round(proceeds, 2), "pnl_pct": round(pnl_pct * 100, 4)})
                position = None
            else:
                shares = lot_shares(open_price)
                cost = shares * open_price
                if shares <= 0 or cost > cash + 1e-8:
                    signal_counts["cash_rejected"] += 1
                    continue
                if action == "new":
                    if position is not None:
                        continue
                    position = Position(shares=shares, cost=cost, entry_date=date,
                                        entries=[{"date": str(date.date()), "price": open_price, "shares": shares}])
                elif action == "add":
                    if position is None:
                        continue
                    position.shares += shares
                    position.cost += cost
                    position.entries.append({"date": str(date.date()), "price": open_price, "shares": shares})
                cash -= cost
                orders.append({"date": str(date.date()), "action": action, "price": open_price,
                               "shares": shares, "cost": round(cost, 2)})

        next_date = dates[i + 1] if i + 1 < len(dates) else None
        if position is not None:
            # Both conditions are known at the close and execute only at T+1 open.
            # "跌破" uses strict close < H3; the 40% profit trigger is close/H3-1 > 40%.
            exit_reason = None
            if close < float(row.h3):
                exit_reason = "close_broke_below_h3"
                signal_counts["sell_orders_scheduled_h3_break"] += 1
            elif close / float(row.h3) - 1.0 > 0.40:
                exit_reason = "close_h3_distance_strictly_gt_40pct"
                signal_counts["sell_orders_scheduled_h3_distance_gt_40pct"] += 1
            if exit_reason and next_date is not None and "sell" not in pending.get(next_date, []):
                position.entries[-1]["scheduled_exit_reason"] = exit_reason
                pending.setdefault(next_date, []).append("sell")

        # Entry/add decision is after all close-based exit decisions.  A pending
        # next-open sell prevents a contradictory next-open buy/add.
        if bool(row.entry_signal):
            signal_counts["raw_entry_signals"] += 1
            if next_date is not None and "sell" not in pending.get(next_date, []):
                if position is None:
                    pending.setdefault(next_date, []).append("new")
                    signal_counts["new_entry_orders_scheduled"] += 1
                else:
                    pnl = close * position.shares / position.cost - 1.0
                    if pnl < -0.30:
                        pending.setdefault(next_date, []).append("add")
                        signal_counts["add_orders_scheduled"] += 1

        market_value = 0.0 if position is None else position.shares * close
        equity = cash + market_value
        daily.append({"date": str(date.date()), "cash": round(cash, 2), "market_value": round(market_value, 2),
                      "equity": round(equity, 2), "equity_equals_cash_plus_market_value": True,
                      "position_shares": 0 if position is None else position.shares,
                      "close": close, "h1": float(row.h1), "h2": float(row.h2), "h3": float(row.h3),
                      "entry_signal": bool(row.entry_signal)})

    daily_frame = pd.DataFrame(daily)
    closed_returns = pd.Series([x["return_pct"] / 100.0 for x in cycles], dtype=float)
    winner_returns = closed_returns[closed_returns > 0]
    loser_returns = closed_returns[closed_returns <= 0]
    holding = pd.Series([x["holding_trading_days"] for x in cycles], dtype=float)
    final = daily_frame.iloc[-1]
    summary = {
        "initial_cash": INITIAL_CASH, "lot_cash_target": LOT_CASH,
        "period_requested_start": str(START.date()), "first_available_bar": daily[0]["date"], "last_bar": daily[-1]["date"],
        "closed_cycles": len(cycles), "open_position": position is not None,
        "open_position_shares": 0 if position is None else position.shares,
        "open_position_cost": 0.0 if position is None else round(position.cost, 2),
        "open_position_mtm_pnl_pct": None if position is None else round((float(final.market_value) / position.cost - 1.0) * 100, 4),
        "final_cash": float(final.cash), "final_market_value": float(final.market_value), "final_equity": float(final.equity),
        "total_return_pct": round((float(final.equity) / INITIAL_CASH - 1.0) * 100, 4),
        "max_drawdown_pct": round(max_drawdown(daily_frame.equity) * 100, 4),
        "win_rate_pct_closed": None if closed_returns.empty else round((closed_returns > 0).mean() * 100, 4),
        "average_closed_return_pct": None if closed_returns.empty else round(closed_returns.mean() * 100, 4),
        "median_closed_return_pct": None if closed_returns.empty else round(closed_returns.median() * 100, 4),
        "average_profit_pct_winners": None if winner_returns.empty else round(winner_returns.mean() * 100, 4),
        "average_loss_pct_losers": None if loser_returns.empty else round(loser_returns.mean() * 100, 4),
        "average_holding_trading_days_closed": None if holding.empty else round(holding.mean(), 4),
        "median_holding_trading_days_closed": None if holding.empty else round(holding.median(), 4),
        "strict_mtm_daily_invariant_passed": bool(np.allclose(daily_frame.equity, daily_frame.cash + daily_frame.market_value, atol=0.01)),
        "signal_counts": signal_counts,
    }
    return summary, cycles, daily, orders


def report_text(payload: dict) -> str:
    s = payload["summary"]
    lines = [
        "688019（澜起科技）EMA(6)-EMA(EMA6,18)-EMA(108) 策略：H3跌破止损/H3乖离40%止盈，严格 MTM 回测 v2",
        "=" * 88,
        f"请求区间：2012-01-01 起；688019 本地日线实际首日 {s['first_available_bar']}（科创板上市后），末日 {s['last_bar']}。",
        "数据：/home/lufanfeng/tdx_data 本地 TDX 原始/未复权日线；无费税、滑点、涨跌停/停牌成交限制。",
        "EMA采用通达信同口径递推（adjust=False）。前108根日线仅预热、不产生交易信号。",
        "入场：收盘后同时满足 H1上穿H2、H1>H3、H2>H3、(H1/H3-1)<10%、H3>昨日H3；下一可用交易日开盘买入。",
        "补仓：已有持仓且该收盘总浮亏严格<-30%，并再次出现上述入场信号，则下一交易日开盘按一份补仓。",
        "止损：收盘价严格跌破H3（close<H3），下一可用交易日开盘全卖。",
        "止盈：收盘价相对H3的乖离严格大于40%〔close/H3-1>40%〕，下一可用交易日开盘全卖。若同日亦跌破H3，优先记录为H3跌破止损。",
        f"组合假设：初始现金 {s['initial_cash']:,.0f} 元；每份目标 {s['lot_cash_target']:,.0f} 元；严格现金约束；逐日权益=现金+收盘市值。",
        "",
        "核心结果（已平仓指标不把期末未平仓伪装成已实现）：",
        f"  期末权益：{s['final_equity']:,.2f} = 现金 {s['final_cash']:,.2f} + MTM市值 {s['final_market_value']:,.2f}",
        f"  总收益（含期末MTM）：{s['total_return_pct']:+.2f}%",
        f"  最大回撤（逐日严格MTM权益）：{s['max_drawdown_pct']:.2f}%",
        f"  已平仓轮次 / 胜率：{s['closed_cycles']} / {s['win_rate_pct_closed'] if s['win_rate_pct_closed'] is not None else '—'}%",
        f"  已平仓平均收益 / 中位收益：{s['average_closed_return_pct'] if s['average_closed_return_pct'] is not None else '—'}% / {s['median_closed_return_pct'] if s['median_closed_return_pct'] is not None else '—'}%",
        f"  平均盈利 / 平均亏损（已平仓）：{s['average_profit_pct_winners'] if s['average_profit_pct_winners'] is not None else '—'}% / {s['average_loss_pct_losers'] if s['average_loss_pct_losers'] is not None else '—'}%",
        f"  已平仓平均 / 中位持股天数：{s['average_holding_trading_days_closed'] if s['average_holding_trading_days_closed'] is not None else '—'} / {s['median_holding_trading_days_closed'] if s['median_holding_trading_days_closed'] is not None else '—'} 个交易日",
        f"  期末是否持仓：{s['open_position']}；期末持仓MTM收益：{s['open_position_mtm_pnl_pct'] if s['open_position_mtm_pnl_pct'] is not None else '—'}%",
        f"  日度权益恒等式（权益=现金+市值）：{s['strict_mtm_daily_invariant_passed']}",
        "", "执行/信号统计：",
    ]
    lines.extend(f"  {key}: {value}" for key, value in s["signal_counts"].items())
    lines.append("\n已平仓轮次明细：")
    if payload["closed_cycles"]:
        for t in payload["closed_cycles"]:
            lines.append(f"  {t['entry_date']} → {t['exit_date']} | {t['entry_lots']}份/{t['shares']}股 | {t['return_pct']:+.2f}% | {t['holding_trading_days']}交易日 | {t['exit_reason']}")
    else:
        lines.append("  无")
    return "\n".join(lines) + "\n"


def main() -> None:
    frame = enrich(load_frame())
    summary, cycles, daily, orders = simulate(frame)
    payload = {
        "version": "v2", "code": CODE, "name": "澜起科技", "summary": summary,
        "contracts": {"signal": "H1 crosses above H2; H1>H3; H2>H3; H1/H3-1<10%; H3>REF(H3,1)",
                      "entry_execution": "signal close -> next available stock trading day open",
                      "replenishment": "held total close PnL < -30% and a new entry signal -> next open one lot",
                      "h3_stop": "close < H3 -> next open sell",
                      "h3_distance_take_profit": "close/H3-1 > 40% -> next open sell",
                      "accounting": "cash-conserving strict daily MTM: equity=cash+close market value"},
        "closed_cycles": cycles, "orders": orders, "daily_equity": daily,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"{STEM}.json"
    text_path = OUT_DIR / f"{STEM}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(report_text(payload), encoding="utf-8")
    print(json.dumps({"script": str(Path(__file__).resolve()), "json": str(json_path), "text": str(text_path), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
