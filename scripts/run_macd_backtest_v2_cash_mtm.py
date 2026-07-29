#!/usr/bin/env python3
"""MACD extreme golden-cross historical backtest with strict cash-conserving MTM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from mootdx.reader import Reader

PROJECT_ROOT = Path("/home/lufanfeng/Project-Hermes-Stock")
sys.path.insert(0, str(PROJECT_ROOT))
from app.strategy.macd_backtest_engine import simulate_portfolio

args = json.loads(sys.argv[1])
START = args["start"]
INIT = float(args["capital"])
LOT = float(args["lot"])
END = "2026-07-25"
LOOKBACK = f"{int(START[:4]) - 1}-07-01" if int(START[:4]) > 2011 else "2011-12-01"
STATE_FILE = PROJECT_ROOT / "data/derived/datasets/final/macd_gc_state.json"
MTM_FILE = PROJECT_ROOT / "data/derived/datasets/final/macd_gc_equity_weekly.json"
CONSTITUENT_FILES = (
    PROJECT_ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json",
    Path("/tmp/csi300_constituents.json"),  # legacy fallback only
)


def load_codes() -> list[str]:
    constituent_file = next((path for path in CONSTITUENT_FILES if path.is_file()), None)
    if constituent_file is None:
        searched = ", ".join(str(path) for path in CONSTITUENT_FILES)
        raise FileNotFoundError(f"CSI300 constituent list is unavailable; searched: {searched}")
    with constituent_file.open(encoding="utf-8") as handle:
        codes = sorted(set(str(code).zfill(6) for code in json.load(handle)))
    if len(codes) != 300:
        raise ValueError(f"Expected 300 CSI300 constituents in {constituent_file}; got {len(codes)}")
    return codes


def build_signal_bars(df: pd.DataFrame) -> pd.DataFrame:
    bars = df[["open", "close"]].copy()
    close = bars["close"].astype(float)
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    bars["ndif"] = np.where(close != 0, dif / close * 100, 0.0)
    bars["ndea"] = np.where(close != 0, dea / close * 100, 0.0)
    ma10 = close.rolling(10).mean()
    golden = (bars["ndif"] > bars["ndea"]) & (bars["ndif"].shift(1) <= bars["ndea"].shift(1))
    dead = (bars["ndif"] < bars["ndea"]) & (bars["ndif"].shift(1) >= bars["ndea"].shift(1))
    buy = golden & (bars["ndif"] < -1.0) & (ma10 > ma10.shift(1))
    bars["buy_signal"] = buy.fillna(False)
    bars["replenish_signal"] = (buy & (bars["ndif"] < -3.0)).fillna(False)
    bars["dead_cross"] = dead.fillna(False)
    return bars


def build_weekly_mtm(daily_equity: list[dict]) -> list[dict]:
    if not daily_equity:
        return []
    frame = pd.DataFrame(daily_equity)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    weekly = frame.resample("W-FRI").last().dropna()
    if weekly.index[-1] != frame.index[-1]:
        weekly.loc[frame.index[-1]] = frame.iloc[-1]
        weekly = weekly.sort_index()
    return [
        {"week": str(index.date()), "equity": round(float(row.equity), 2)}
        for index, row in weekly.iterrows()
    ]


reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
bars_by_code: dict[str, pd.DataFrame] = {}
for code in load_codes():
    try:
        daily = reader.daily(code)
    except Exception:
        continue
    if daily is None or len(daily) < 100:
        continue
    daily = daily.sort_index()
    daily = daily[(daily.index >= LOOKBACK) & (daily.index <= END)]
    if len(daily) < 100:
        continue
    bars = build_signal_bars(daily)
    bars = bars[bars.index >= pd.Timestamp(START)]
    if len(bars) >= 2:
        bars_by_code[code] = bars

result = simulate_portfolio(bars_by_code, initial_capital=INIT, lot_cash=LOT)

from app.search.index import _stock_name_lookup
name_lookup = _stock_name_lookup()


def stock_name(code: str) -> str:
    market = "sh" if code.startswith(("6", "9")) else "sz"
    return str(name_lookup.get((market, code), code))

positions = {}
for code, position in result["positions"].items():
    entries = []
    for entry in position["entries"]:
        value = dict(entry)
        value["price"] = round(float(value["price"]), 2)
        if value.get("ndif") is None:
            value.pop("ndif", None)
        entries.append(value)
    positions[code] = {
        "name": stock_name(code),
        "entries": entries,
        "profit_triggered": bool(position.get("armed")),
        "trigger_date": position.get("armed_date", ""),
    }

state = {
    "config": {"capital": int(INIT), "lot": int(LOT)},
    "cash": round(float(result["cash"]), 2),
    "positions": positions,
    "history": result["history"],
}
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
weekly = build_weekly_mtm(result["daily_equity"])
MTM_FILE.write_text(json.dumps(weekly, ensure_ascii=False), encoding="utf-8")

summary = result["summary"]
print(
    f"OK|{len(positions)}|{len(result['history'])}|{result['executed']}|"
    f"{result['rejected']}|{summary['equity']:.0f}"
)
print(
    "MTM: "
    f"{len(weekly)} weeks, {INIT:,.0f} -> {summary['equity']:,.2f} "
    f"({(summary['equity'] / INIT - 1) * 100:+.2f}%)",
    file=sys.stderr,
)
