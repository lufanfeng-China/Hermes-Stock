"""Cash-conserving, T+1 portfolio simulator for MACD extreme golden-cross backtests."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd


EPSILON = 1e-8


def _as_bool(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _price(row: pd.Series, column: str) -> float:
    value = float(row.get(column, 0.0))
    return value if value > 0 else 0.0


def _position_cost(position: dict[str, Any]) -> float:
    return sum(float(entry["price"]) * int(entry["shares"]) for entry in position["entries"])


def _position_shares(position: dict[str, Any]) -> int:
    return sum(int(entry["shares"]) for entry in position["entries"])


def _position_value(position: dict[str, Any], close: float) -> float:
    return close * _position_shares(position)


def simulate_portfolio(
    bars_by_code: dict[str, pd.DataFrame],
    *,
    initial_capital: float,
    lot_cash: float,
) -> dict[str, Any]:
    """Execute precomputed daily MACD signals with actual cash and T+1 orders.

    Each bars frame must use a DatetimeIndex and contain ``open``, ``close``,
    ``buy_signal``, ``replenish_signal``, and ``dead_cross`` booleans.
    ``buy_signal`` is the normal extreme-golden-cross entry signal; a replenish
    additionally requires the portfolio position to be down more than 20%.
    """
    if initial_capital <= 0 or lot_cash <= 0:
        raise ValueError("initial_capital and lot_cash must be positive")

    frames = {
        code: frame.sort_index().copy()
        for code, frame in bars_by_code.items()
        if frame is not None and not frame.empty
    }
    if not frames:
        return {
            "cash": float(initial_capital), "positions": {}, "history": [],
            "daily_equity": [],
            "summary": {
                "cash": float(initial_capital), "market_value": 0.0,
                "realized_pnl": 0.0, "unrealized_pnl": 0.0,
                "equity": float(initial_capital),
            },
            "executed": 0, "rejected": 0,
        }

    trade_days = sorted({day for frame in frames.values() for day in frame.index})
    row_lookup = {code: {day: row for day, row in frame.iterrows()} for code, frame in frames.items()}
    day_index = {day: index for index, day in enumerate(trade_days)}

    cash = float(initial_capital)
    positions: dict[str, dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    pending: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    pending_keys: set[tuple[str, str]] = set()
    last_close: dict[str, float] = {}
    daily_equity: list[dict[str, Any]] = []
    executed = 0
    rejected = 0

    def schedule_next(day: pd.Timestamp, order: dict[str, Any]) -> bool:
        index = day_index[day] + 1
        if index >= len(trade_days):
            return False
        key = (order["kind"], order["code"])
        if key in pending_keys:
            return False
        pending[trade_days[index]].append(order)
        pending_keys.add(key)
        return True

    for day in trade_days:
        # T+1 orders execute at the next available market open. Sells first so
        # same-open sale proceeds can finance new orders without borrowing.
        orders = pending.pop(day, [])
        for order in sorted(orders, key=lambda item: 0 if item["kind"] == "exit" else 1):
            pending_keys.discard((order["kind"], order["code"]))
            code = order["code"]
            row = row_lookup[code].get(day)
            open_price = _price(row, "open") if row is not None else 0.0
            if open_price <= 0:
                rejected += 1
                if order["kind"] == "exit" and code in positions:
                    positions[code]["exit_pending"] = False
                continue

            if order["kind"] == "entry":
                if code in positions:
                    continue
                shares = int(lot_cash / open_price)
                cost = open_price * shares
                if shares <= 0 or cost > cash + EPSILON:
                    rejected += 1
                    continue
                cash -= cost
                positions[code] = {
                    "entries": [{"date": str(day.date()), "type": "开仓", "price": open_price, "shares": shares, "ndif": order.get("ndif")}],
                    "armed": False,
                    "exit_pending": False,
                }
                executed += 1

            elif order["kind"] == "replenish":
                position = positions.get(code)
                if position is None or position.get("exit_pending"):
                    continue
                shares = int(lot_cash / open_price)
                cost = open_price * shares
                if shares <= 0 or cost > cash + EPSILON:
                    rejected += 1
                    continue
                cash -= cost
                position["entries"].append({"date": str(day.date()), "type": "补仓", "price": open_price, "shares": shares, "ndif": order.get("ndif")})
                executed += 1

            elif order["kind"] == "exit":
                position = positions.get(code)
                if position is None:
                    continue
                shares = _position_shares(position)
                cost = _position_cost(position)
                revenue = open_price * shares
                cash += revenue
                history.append({
                    "date": str(day.date()),
                    "entry_date": position["entries"][0]["date"],
                    "code": code,
                    "exit_reason": order["reason"],
                    "buy_cost": round(cost, 2),
                    "sell_rev": round(revenue, 2),
                    "pnl": round(revenue - cost, 2),
                })
                del positions[code]
                executed += 1

        # Close prices are used for signal evaluation and daily MTM.
        for code, rows in row_lookup.items():
            row = rows.get(day)
            if row is not None:
                close = _price(row, "close")
                if close > 0:
                    last_close[code] = close

        for code, row in ((code, rows.get(day)) for code, rows in row_lookup.items()):
            if row is None:
                continue
            close = _price(row, "close")
            if close <= 0:
                continue
            position = positions.get(code)
            if position is not None:
                cost = _position_cost(position)
                value = _position_value(position, close)
                profit_rate = value / cost - 1 if cost > 0 else 0.0
                if profit_rate > 0.20:
                    if not position.get("armed"):
                        position["armed_date"] = str(day.date())
                    position["armed"] = True
                if position.get("armed") and not position.get("exit_pending"):
                    if _as_bool(row.get("dead_cross")) or profit_rate < 0.15:
                        reason = "死叉卖出" if _as_bool(row.get("dead_cross")) else "止盈卖出(破15%)"
                        if _as_bool(row.get("dead_cross")) and profit_rate < 0.15:
                            reason = "死叉+破15%卖出"
                        if schedule_next(day, {"kind": "exit", "code": code, "reason": reason}):
                            position["exit_pending"] = True
                elif (not position.get("exit_pending") and _as_bool(row.get("replenish_signal"))
                      and profit_rate < -0.20):
                    schedule_next(day, {"kind": "replenish", "code": code, "ndif": row.get("ndif")})
            elif _as_bool(row.get("buy_signal")):
                schedule_next(day, {"kind": "entry", "code": code, "ndif": row.get("ndif")})

        market_value = sum(
            _position_value(position, last_close.get(code, 0.0))
            for code, position in positions.items()
        )
        daily_equity.append({"date": str(day.date()), "equity": cash + market_value})

    market_value = sum(
        _position_value(position, last_close.get(code, 0.0))
        for code, position in positions.items()
    )
    realized_pnl = sum(float(item["pnl"]) for item in history)
    open_cost = sum(_position_cost(position) for position in positions.values())
    unrealized_pnl = market_value - open_cost
    equity = cash + market_value
    expected_equity = initial_capital + realized_pnl + unrealized_pnl
    if abs(equity - expected_equity) > 0.01:
        raise RuntimeError(
            f"Cash accounting invariant failed: equity={equity:.2f}, expected={expected_equity:.2f}"
        )

    return {
        "cash": cash,
        "positions": positions,
        "history": history,
        "daily_equity": daily_equity,
        "summary": {
            "cash": cash,
            "market_value": market_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity": equity,
        },
        "executed": executed,
        "rejected": rejected,
    }
