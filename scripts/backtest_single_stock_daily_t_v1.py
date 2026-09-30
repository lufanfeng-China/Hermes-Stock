#!/usr/bin/env python3
"""Daily T+1, strict-MTM backtest for 10 current CSI500 constituents.

Technical conditions are computed on TDX QFQ closes at T close.  Orders execute
only on the next available raw daily open.  This is a single-stock, inventory
based daily-T simulator: 60% core shares, 40% floating shares, and 20% of the
initial shares per T operation.  The raw buy-and-hold comparator deliberately
uses the same unadjusted raw data and ignores dividends/rights, so it is a
fairer implementation comparator than mixing it with QFQ P&L.  QFQ price
return is reported separately as the stock's adjusted price movement.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import TDX_QFQ_EXPORT_DIR, TONGDAXIN_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

# Official CSI Index page for 000905, updated 2026-09-29: the first 10 by
# displayed constituent weight.  This is a reproducible, current-constituent
# sample, not a historical-membership universe.
CSI500_TOP10 = [
    ("688498", "源杰科技"), ("300604", "长川科技"), ("688120", "华海清科"),
    ("688347", "华虹宏力"), ("688361", "中科飞测"), ("300857", "协创数据"),
    ("002281", "光迅科技"), ("002436", "兴森科技"), ("002008", "大族激光"),
    ("688002", "睿创微纳"),
]

INITIAL_CASH = 1_000_000.0
BUY_SLIPPAGE = 0.001
SELL_SLIPPAGE = 0.001
COMMISSION = 0.0003
SELL_STAMP_TAX = 0.0005


def buy_cost(price: float, shares: int) -> float:
    return price * shares * (1.0 + BUY_SLIPPAGE) * (1.0 + COMMISSION)


def sell_proceeds(price: float, shares: int) -> float:
    return price * shares * (1.0 - SELL_SLIPPAGE) * (1.0 - COMMISSION - SELL_STAMP_TAX)


def t_cycle_net_return(sell_price: float, rebuy_price: float) -> float:
    """Net cash saving from a completed sell-high/rebuy-lower T cycle."""
    return sell_proceeds(sell_price, 1) / buy_cost(rebuy_price, 1) - 1.0


def cancel_high_sell_on_gap(open_price: float, previous_close: float) -> bool:
    return previous_close > 0 and open_price / previous_close - 1.0 < -0.0300001


def cancel_rebuy_on_gap(open_price: float, previous_close: float) -> bool:
    return previous_close > 0 and open_price / previous_close - 1.0 > 0.0500001


def _rsi(close: pd.Series, period: int = 6) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    avg_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_down = down.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_down.where(avg_down > 0.0)
    return 100.0 - 100.0 / (1.0 + rs)


def enrich_qfq(qfq: pd.DataFrame) -> pd.DataFrame:
    out = qfq.sort_index().copy()
    out.index = pd.to_datetime(out.index)
    out["ma5"] = out.close.rolling(5, min_periods=5).mean()
    out["ma10"] = out.close.rolling(10, min_periods=10).mean()
    out["ma20"] = out.close.rolling(20, min_periods=20).mean()
    out["ma60"] = out.close.rolling(60, min_periods=60).mean()
    out["rsi6"] = _rsi(out.close, 6)
    out["hhv10"] = out.high.rolling(10, min_periods=10).max()
    out["trend"] = (out.close > out.ma20) & (out.ma20 > out.ma60) & (out.ma20 > out.ma20.shift(5))
    out["bias20"] = out.close / out.ma20 - 1.0
    out["high_sell_signal"] = out.trend & (out.bias20 >= 0.08) & (out.close >= out.hhv10 * 0.98) & (out.rsi6 >= 80.0)
    out["rebuy_signal"] = (
        out.trend & (out.low <= out.ma10 * 1.02) & (out.close >= out.ma10) & (out.close > out.open)
        & (out.rsi6.shift(1) <= 50.0) & (out.rsi6 > 50.0) & (out.bias20 <= 0.04)
    )
    out["float_risk_signal"] = ((out.close < out.ma20) & (out.close.shift(1) < out.ma20.shift(1)))
    out["core_exit_signal"] = ((out.close < out.ma60) & (out.close.shift(1) < out.ma60.shift(1)) & (out.close.shift(2) < out.ma60.shift(2)))
    return out


def _common_frame(raw: pd.DataFrame, qfq: pd.DataFrame, start: str) -> pd.DataFrame:
    raw = raw.sort_index().copy()
    raw.index = pd.to_datetime(raw.index)
    qfq = enrich_qfq(qfq)
    common = raw.index.intersection(qfq.index)
    frame = raw.loc[common, ["open", "high", "low", "close", "volume"]].join(
        qfq.loc[common, ["close", "trend", "high_sell_signal", "rebuy_signal", "float_risk_signal", "core_exit_signal"]].rename(columns={"close": "qfq_close"})
    )
    return frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.volume > 0) & (frame.open > 0)].copy()


def simulate_single(raw: pd.DataFrame, qfq: pd.DataFrame, start: str) -> dict[str, Any]:
    frame = _common_frame(raw, qfq, start)
    if len(frame) < 90:
        raise ValueError(f"need >=90 aligned live bars after {start}; got {len(frame)}")
    start_open = float(frame.iloc[0].open)
    initial_shares = int(INITIAL_CASH / (start_open * (1.0 + BUY_SLIPPAGE) * (1.0 + COMMISSION)) // 500) * 500
    if initial_shares < 500:
        raise ValueError("initial cash cannot fund 500 shares")
    core_shares = initial_shares * 3 // 5
    floating_shares = initial_shares - core_shares
    unit = initial_shares // 5
    cash = INITIAL_CASH - buy_cost(start_open, initial_shares)
    sold_slots: list[dict[str, Any]] = []
    pending: str | None = None
    last_float_buy_raw: float | None = None
    orders: list[dict[str, Any]] = [{"date": frame.index[0].date().isoformat(), "action": "initial_buy", "shares": initial_shares, "raw_price": start_open}]
    completed_t: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    cancelled = {"sell_gap_down": 0, "rebuy_gap_up": 0, "unfilled_no_cash": 0}

    dates = list(frame.index)
    for i, date in enumerate(dates):
        row = frame.iloc[i]
        open_price, close = float(row.open), float(row.close)
        previous_close = float(frame.iloc[i - 1].close) if i else start_open
        if pending == "core_exit":
            shares = core_shares + floating_shares
            if shares:
                cash += sell_proceeds(open_price, shares)
                orders.append({"date": date.date().isoformat(), "action": "core_exit", "shares": shares, "raw_price": open_price})
            core_shares = floating_shares = 0
            sold_slots.clear()
        elif pending == "float_exit":
            if floating_shares:
                cash += sell_proceeds(open_price, floating_shares)
                orders.append({"date": date.date().isoformat(), "action": "float_exit", "shares": floating_shares, "raw_price": open_price})
                floating_shares = 0
                sold_slots.clear()
        elif pending == "high_sell":
            if cancel_high_sell_on_gap(open_price, previous_close):
                cancelled["sell_gap_down"] += 1
            elif floating_shares >= unit:
                cash += sell_proceeds(open_price, unit)
                floating_shares -= unit
                sold_slots.append({"date": date.date().isoformat(), "price": open_price, "shares": unit})
                orders.append({"date": date.date().isoformat(), "action": "t_sell", "shares": unit, "raw_price": open_price})
        elif pending == "rebuy":
            if cancel_rebuy_on_gap(open_price, previous_close):
                cancelled["rebuy_gap_up"] += 1
            elif sold_slots:
                slot = sold_slots[0]
                shares = int(slot["shares"])
                cost = buy_cost(open_price, shares)
                if cost <= cash + 1e-6:
                    cash -= cost
                    floating_shares += shares
                    sold_slots.pop(0)
                    last_float_buy_raw = open_price
                    cycle = {"sell_date": slot["date"], "rebuy_date": date.date().isoformat(), "shares": shares, "sell_raw": slot["price"], "rebuy_raw": open_price, "net_return": t_cycle_net_return(float(slot["price"]), open_price)}
                    completed_t.append(cycle)
                    orders.append({"date": date.date().isoformat(), "action": "t_rebuy", "shares": shares, "raw_price": open_price, "t_cycle_net_return": cycle["net_return"]})
                else:
                    cancelled["unfilled_no_cash"] += 1
        pending = None

        next_exists = i + 1 < len(frame)
        if next_exists and (core_shares + floating_shares) > 0:
            # This study measures the T sleeve against a continuously held base
            # position.  A full-core trend exit is deliberately excluded here:
            # otherwise a single early MA60 break turns the test into a timing
            # strategy and leaves no inventory to evaluate daily T operations.
            if floating_shares and last_float_buy_raw is not None and (bool(row.float_risk_signal) or close / last_float_buy_raw - 1.0 <= -0.08):
                pending = "float_exit"
            elif bool(row.high_sell_signal) and floating_shares >= unit:
                pending = "high_sell"
            elif bool(row.rebuy_signal) and sold_slots:
                pending = "rebuy"
        market_value = (core_shares + floating_shares) * close
        daily.append({"date": date.date().isoformat(), "cash": cash, "market_value": market_value, "equity": cash + market_value, "core_shares": core_shares, "floating_shares": floating_shares, "sold_slots": len(sold_slots), "pending": pending})

    daily_df = pd.DataFrame(daily)
    end_close = float(frame.iloc[-1].close)
    final_equity = float(daily_df.iloc[-1].equity)
    raw_bh_equity = INITIAL_CASH - buy_cost(start_open, initial_shares) + initial_shares * end_close
    qfq_return = float(frame.iloc[-1].qfq_close / frame.iloc[0].qfq_close - 1.0)
    cycle_returns = pd.Series([item["net_return"] for item in completed_t], dtype=float)
    max_dd = float((daily_df.equity / daily_df.equity.cummax() - 1.0).min())
    return {
        "summary": {
            "start": frame.index[0].date().isoformat(), "end": frame.index[-1].date().isoformat(), "trading_days": len(frame),
            "qfq_stock_price_return": qfq_return,
            "raw_buy_hold_return": float(raw_bh_equity / INITIAL_CASH - 1.0),
            "daily_t_strict_mtm_return": float(final_equity / INITIAL_CASH - 1.0),
            "daily_t_minus_raw_buy_hold": float(final_equity / raw_bh_equity - 1.0),
            "daily_t_max_drawdown": max_dd,
            "completed_t_cycles": len(completed_t),
            "t_success_rate": None if cycle_returns.empty else float((cycle_returns > 0).mean()),
            "t_cycle_mean_net_return": None if cycle_returns.empty else float(cycle_returns.mean()),
            "t_cycle_median_net_return": None if cycle_returns.empty else float(cycle_returns.median()),
            "unclosed_sold_slots": len(sold_slots), "cancelled_orders": cancelled,
            "mtm_invariant": bool((daily_df.equity - daily_df.cash - daily_df.market_value).abs().max() < 0.01),
            "raw_buy_hold_note": "Uses unadjusted raw price and excludes dividends/rights; QFQ stock price return is separately reported.",
        },
        "orders": orders, "completed_t_cycles": completed_t, "daily_equity": daily,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--qfq-export-dir", type=Path, default=TDX_QFQ_EXPORT_DIR)
    parser.add_argument("--tdxdir", default=TONGDAXIN_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("/mnt/c/Users/Sky.Lu/Desktop/output"))
    args = parser.parse_args()
    reader = Reader.factory(market="std", tdxdir=args.tdxdir)
    results: list[dict[str, Any]] = []
    for code, name in CSI500_TOP10:
        raw = reader.daily(code)
        if raw is None or raw.empty:
            raise RuntimeError(f"raw data absent for {code}{name}")
        qfq = load_tdx_qfq_daily(code, args.qfq_export_dir)
        result = simulate_single(raw, qfq, args.start)
        results.append({"code": code, "name": name, **result})
    table = [{"code": item["code"], "name": item["name"], **item["summary"]} for item in results]
    output = {"universe": "Official CSI500 (000905) displayed top-10 constituent weights, page updated 2026-09-29", "signals": "QFQ T-close; raw next-open execution", "costs": {"buy_slippage": BUY_SLIPPAGE, "sell_slippage": SELL_SLIPPAGE, "commission": COMMISSION, "sell_stamp_tax": SELL_STAMP_TAX}, "table": table, "stocks": results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"CSI500官方前10成分股_单股日线做T验证_{args.start}_至raw最新"
    json_path = args.output_dir / f"{stem}_20260930_v1.json"
    csv_path = args.output_dir / f"{stem}_20260930_v1.csv"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(table).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "table": table}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
