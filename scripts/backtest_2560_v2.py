#!/usr/bin/env python3
"""Chronological CSI300 backtest for the 2560 entry and armed-exit strategy.

Signals are formed at a daily close.  A qualifying signal buys at its trigger
price only when the following trading bar's high reaches that price.  Cash and
slot availability are evaluated at that time; exits are evaluated later at the
same day's close.  This deliberately avoids looking ahead to an exit when an
entry signal is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from mootdx.reader import Reader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.strategy_2560_exit import exit_reason


DEFAULT_TDX_DIR = "/mnt/c/new_tdx64"
DEFAULT_CONSTITUENTS = "/tmp/csi300_constituents.json"
LOT_CASH = 50_000


@dataclass
class Position:
    code: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    signal_date: pd.Timestamp
    armed: bool = False

    @property
    def cost(self) -> float:
        return self.shares * self.entry_price


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chronological CSI300 2560 backtest")
    parser.add_argument("--start", default="2012-01-01", help="first signal date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="last trading date to include (YYYY-MM-DD)")
    parser.add_argument("--initial-cash", type=float, default=3_000_000, help="initial cash")
    parser.add_argument("--tdx-dir", default=DEFAULT_TDX_DIR, help="TDX data directory")
    parser.add_argument("--constituents", default=DEFAULT_CONSTITUENTS, help="CSI300 JSON code list")
    return parser.parse_args()


def load_stock_data(reader: Reader, codes: list[str]) -> dict[str, pd.DataFrame]:
    """Load sufficiently long, sorted daily histories once for all constituents."""
    result: dict[str, pd.DataFrame] = {}
    for number, code in enumerate(codes, start=1):
        if number == 1 or number % 100 == 0:
            print(f"Loading {number}/{len(codes)}")
        try:
            frame = reader.daily(code)
        except Exception as exc:  # A missing/corrupt local .day file is skipped.
            print(f"Skipping {code}: {exc}", file=sys.stderr)
            continue
        if frame is None or len(frame) < 102:
            continue
        frame = frame.sort_index().copy()
        required = {"close", "high", "low", "volume"}
        if not required.issubset(frame.columns):
            continue
        frame.index = pd.DatetimeIndex(frame.index).normalize()
        result[code] = frame
    return result


def prepare_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate the exploration script's 2560 entry criteria and MACD crosses."""
    prepared = frame.copy()
    close = prepared["close"].astype(float)
    high = prepared["high"].astype(float)
    low = prepared["low"].astype(float)
    volume = prepared["volume"].astype(float)

    ma25 = close.rolling(25).mean()
    volume_ma5 = volume.rolling(5).mean()
    volume_ma60 = volume.rolling(60).mean()
    ma_trend = ma25 / ma25.shift(5) - 1
    volume_ratio = volume_ma5 / volume_ma60
    daily_range = high - low

    # These predicates exactly reproduce /tmp/backtest_2560_yearly.py lines 47-59.
    prepared["entry_signal"] = (
        (ma_trend >= 0.005)
        & (volume_ratio >= 1.15)
        & (volume_ratio <= 2.5)
        & (low <= ma25 * 1.03)
        & (low >= ma25 * 0.97)
        & (close >= ma25)
        & ((close / ma25 - 1) <= 0.05)
        & (daily_range > 0)
        & (close >= low + 0.5 * daily_range)
    )
    # The exploration loop starts at index 100, even though the rolling inputs
    # are available sooner.
    prepared.loc[prepared.index[:100], "entry_signal"] = False
    prepared["trigger_price"] = high * 1.005

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    normalized_dif = np.where(close != 0, dif / close * 100, 0.0)
    normalized_dea = np.where(close != 0, dea / close * 100, 0.0)
    prepared["macd_dead_cross"] = (
        (normalized_dif < normalized_dea)
        & (pd.Series(normalized_dif, index=prepared.index).shift(1) >= pd.Series(normalized_dea, index=prepared.index).shift(1))
    )
    return prepared


def run_backtest(
    stock_data: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp, initial_cash: float
) -> tuple[list[dict[str, object]], list[Position], float, dict[str, float], int]:
    """Process entries and exits bar by bar, returning closed trades and final MTM inputs."""
    if initial_cash <= 0:
        raise ValueError("initial cash must be positive")
    max_slots = int(initial_cash // LOT_CASH)
    if max_slots == 0:
        raise ValueError(f"initial cash must be at least {LOT_CASH:,} for one slot")

    prepared = {code: prepare_indicators(frame) for code, frame in stock_data.items()}
    bars_by_date: dict[pd.Timestamp, list[tuple[str, int]]] = defaultdict(list)
    pending_entries: dict[pd.Timestamp, list[tuple[str, pd.Timestamp, float]]] = defaultdict(list)
    for code, frame in prepared.items():
        for index, date in enumerate(frame.index):
            if start <= date <= end:
                bars_by_date[date].append((code, index))

    cash = initial_cash
    positions: list[Position] = []
    closed_trades: list[dict[str, object]] = []
    last_close: dict[str, float] = {}

    for date in sorted(bars_by_date):
        # A breakout happens intraday.  Exit proceeds are not available until
        # this day's close, so entries are intentionally processed first.
        for code, signal_date, trigger_price in sorted(pending_entries.pop(date, [])):
            frame = prepared[code]
            bar = frame.loc[date]
            shares = int(LOT_CASH / trigger_price)
            cost = shares * trigger_price
            if (
                shares > 0
                and float(bar["high"]) >= trigger_price
                and len(positions) < max_slots
                and cash >= cost
            ):
                cash -= cost
                positions.append(Position(code, shares, trigger_price, date, signal_date))

        # Closing prices update P&L/exit state.  Only a stock with a bar today
        # can generate a closing trigger or an exit today.
        for code, index in bars_by_date[date]:
            frame = prepared[code]
            bar = frame.iloc[index]
            close = float(bar["close"])
            last_close[code] = close
            dead_cross = bool(bar["macd_dead_cross"])
            for position in positions[:]:
                if position.code != code:
                    continue
                pnl_pct = (close / position.entry_price - 1.0) * 100.0
                reason = exit_reason(armed=position.armed, pnl_pct=pnl_pct, macd_dead_cross=dead_cross)
                if reason == "armed":
                    position.armed = True
                elif reason is not None:
                    proceeds = position.shares * close
                    cash += proceeds
                    closed_trades.append(
                        {
                            "code": code,
                            "signal_date": position.signal_date,
                            "entry_date": position.entry_date,
                            "entry_price": position.entry_price,
                            "exit_date": date,
                            "exit_price": close,
                            "shares": position.shares,
                            "pnl": proceeds - position.cost,
                            "return_pct": pnl_pct,
                            "exit_reason": reason,
                        }
                    )
                    positions.remove(position)

        # Signals are known only after today's close.  Queue the exact next bar
        # for each code; it will be evaluated when that bar is processed.
        for code, index in bars_by_date[date]:
            frame = prepared[code]
            if bool(frame["entry_signal"].iloc[index]) and index + 1 < len(frame):
                next_date = frame.index[index + 1]
                if next_date <= end:
                    pending_entries[next_date].append(
                        (code, date, float(frame["trigger_price"].iloc[index]))
                    )

    # All remaining positions are marked with their most recent close at or
    # before end, never at cost basis.
    return closed_trades, positions, cash, last_close, max_slots


def main() -> None:
    args = parse_args()
    start = pd.Timestamp(args.start).normalize()
    if args.end is not None:
        end = pd.Timestamp(args.end).normalize()
    else:
        end = pd.Timestamp.today().normalize()
    if end < start:
        raise SystemExit("--end must not be before --start")

    constituents_path = Path(args.constituents)
    with constituents_path.open(encoding="utf-8") as source:
        codes = sorted(set(str(code) for code in json.load(source)))
    reader = Reader.factory(market="std", tdxdir=args.tdx_dir)
    stock_data = load_stock_data(reader, codes)
    if not stock_data:
        raise SystemExit("No usable CSI300 daily data was loaded")

    available_end = min(end, max(frame.index.max() for frame in stock_data.values()))
    if available_end < start:
        raise SystemExit("No loaded data exists in the requested period")
    closed, open_positions, cash, last_close, max_slots = run_backtest(
        stock_data, start, available_end, args.initial_cash
    )
    market_value = sum(position.shares * last_close[position.code] for position in open_positions)
    equity = cash + market_value
    total_return = (equity / args.initial_cash - 1.0) * 100.0

    print("\nCSI300 2560 chronological backtest")
    print(f"Period: {start.date()} to {available_end.date()} | constituents loaded: {len(stock_data)}")
    print(f"Initial cash: {args.initial_cash:,.2f} | max slots: {max_slots}")
    print(f"Closed trades: {len(closed)} | open positions: {len(open_positions)}")
    print(f"Cash: {cash:,.2f} | open-position MTM: {market_value:,.2f}")
    print(f"Final equity (cash + MTM): {equity:,.2f} | return: {total_return:+.2f}%")
    if closed:
        exit_counts = pd.Series([trade["exit_reason"] for trade in closed]).value_counts().to_dict()
        print(f"Exit reasons: {exit_counts}")


if __name__ == "__main__":
    main()
