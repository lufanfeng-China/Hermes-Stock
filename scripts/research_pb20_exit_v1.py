#!/usr/bin/env python3
"""Evaluate executable PB20 exits on raw Tongdaxin daily OHLC data.

Signal formation is out of scope: this consumes the frozen extreme Compact PB20
candidate file.  Entry is the recorded raw T+1 open.  Stops/targets use raw
OHLC only.  If a bar touches both barriers, daily data cannot order the touches,
so the simulator applies the conservative stop-first result.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from mootdx.reader import Reader

DEFAULT_CANDIDATES = Path("/mnt/c/Users/Sky.Lu/Desktop/output/PB20极致压缩候选池历史样本_20260930_v1.csv")
DEFAULT_OUTPUT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")


@dataclass(frozen=True)
class ExitConfig:
    hold_days: int = 20
    stop_pct: float = 0.08
    target_pct: float | None = 0.20
    buy_slippage_pct: float = 0.001
    sell_slippage_pct: float = 0.001
    commission_pct: float = 0.0003
    sell_stamp_tax_pct: float = 0.0005


def _net_return(entry_raw: float, exit_raw: float, config: ExitConfig) -> float:
    entry_cost = entry_raw * (1.0 + config.buy_slippage_pct) * (1.0 + config.commission_pct)
    exit_proceeds = exit_raw * (1.0 - config.sell_slippage_pct) * (1.0 - config.commission_pct - config.sell_stamp_tax_pct)
    return exit_proceeds / entry_cost - 1.0


def _result(
    bars: pd.DataFrame, entry_index: int, exit_index: int, entry_raw: float, exit_raw: float, reason: str, config: ExitConfig
) -> dict[str, Any]:
    return {
        "entry_date": pd.Timestamp(bars.index[entry_index]).date().isoformat(),
        "entry_price_raw": float(entry_raw),
        "exit_date": pd.Timestamp(bars.index[exit_index]).date().isoformat(),
        "exit_price_raw": float(exit_raw),
        "reason": reason,
        "hold_trading_days": int(exit_index - entry_index),
        "gross_return": float(exit_raw / entry_raw - 1.0),
        "net_return": _net_return(entry_raw, exit_raw, config),
    }


def simulate_trade(
    bars: pd.DataFrame, entry_index: int, hold_days: int = 20, stop_pct: float = 0.08, target_pct: float | None = 0.20,
    config: ExitConfig | None = None,
) -> dict[str, Any] | None:
    """Simulate an entry-at-open bracket trade with next-open time exit.

    A hold_days=20 trade observes raw OHLC from entry day through entry+19.
    With no barrier hit, it exits at the next raw open (entry+20), which is
    executable without using that day's closing price.  A downward gap through
    the stop exits at that open.  Ambiguous daily bars touching both barriers
    use stop-first, deliberately understating target performance.
    """
    if config is None:
        config = ExitConfig(hold_days=hold_days, stop_pct=stop_pct, target_pct=target_pct)
    required = {"open", "high", "low", "close"}
    if required.difference(bars.columns):
        raise ValueError("bars require open/high/low/close")
    frame = bars.sort_index()
    if entry_index < 0 or entry_index + config.hold_days >= len(frame):
        return None
    entry_raw = float(frame.iloc[entry_index].open)
    if entry_raw <= 0:
        return None
    stop_price = entry_raw * (1.0 - config.stop_pct)
    target_price = None if config.target_pct is None else entry_raw * (1.0 + config.target_pct)
    for index in range(entry_index, entry_index + config.hold_days):
        row = frame.iloc[index]
        open_price, high, low = float(row.open), float(row.high), float(row.low)
        if open_price <= stop_price:
            return _result(frame, entry_index, index, entry_raw, open_price, "hard_stop_gap_open", config)
        if target_price is not None and open_price >= target_price:
            return _result(frame, entry_index, index, entry_raw, open_price, "take_profit_gap_open", config)
        stop_hit = low <= stop_price
        target_hit = target_price is not None and high >= target_price
        if stop_hit and target_hit:
            return _result(frame, entry_index, index, entry_raw, stop_price, "ambiguous_stop_first", config)
        if stop_hit:
            return _result(frame, entry_index, index, entry_raw, stop_price, "hard_stop", config)
        if target_hit:
            return _result(frame, entry_index, index, entry_raw, target_price, "take_profit", config)
    time_exit_index = entry_index + config.hold_days
    return _result(frame, entry_index, time_exit_index, entry_raw, float(frame.iloc[time_exit_index].open), "time_exit_next_open", config)


def load_raw_bars(reader: Reader, symbol: str) -> pd.DataFrame:
    bars = reader.daily(str(symbol).zfill(6))
    if bars is None or bars.empty:
        raise ValueError("raw daily data absent")
    bars = bars.sort_index().copy()
    bars.index = pd.to_datetime(bars.index)
    return bars[["open", "high", "low", "close", "volume"]].astype(float)


def evaluate_events(events: pd.DataFrame, reader: Reader, config: ExitConfig) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, Any]] = []
    skipped = {"missing_raw": 0, "missing_entry": 0, "insufficient_future": 0}
    cache: dict[str, pd.DataFrame] = {}
    for event in events.itertuples(index=False):
        symbol = str(event.symbol).zfill(6)
        try:
            raw = cache.setdefault(symbol, load_raw_bars(reader, symbol))
        except Exception:
            skipped["missing_raw"] += 1
            continue
        entry_date = pd.Timestamp(event.entry_date)
        matches = raw.index.get_indexer([entry_date])
        entry_index = int(matches[0])
        if entry_index < 0:
            skipped["missing_entry"] += 1
            continue
        trade = simulate_trade(raw, entry_index, config=config)
        if trade is None:
            skipped["insufficient_future"] += 1
            continue
        rows.append({"symbol": symbol, "signal_date": str(event.trading_day), **trade})
    return pd.DataFrame(rows), skipped


def summarize(trades: pd.DataFrame, skipped: dict[str, int], config: ExitConfig) -> dict[str, Any]:
    if trades.empty:
        return {"config": asdict(config), "closed_trades": 0, "skipped": skipped}
    net = trades.net_return
    by_reason = {
        reason: {"count": int(len(part)), "mean_net_return": round(float(part.net_return.mean()), 6), "median_net_return": round(float(part.net_return.median()), 6)}
        for reason, part in trades.groupby("reason")
    }
    return {
        "config": asdict(config),
        "closed_trades": int(len(trades)),
        "win_rate": round(float((net > 0).mean()), 6),
        "mean_net_return": round(float(net.mean()), 6),
        "median_net_return": round(float(net.median()), 6),
        "p25_net_return": round(float(net.quantile(0.25)), 6),
        "p75_net_return": round(float(net.quantile(0.75)), 6),
        "worst_net_return": round(float(net.min()), 6),
        "best_net_return": round(float(net.max()), 6),
        "average_holding_days": round(float(trades.hold_trading_days.mean()), 4),
        "median_holding_days": round(float(trades.hold_trading_days.median()), 4),
        "exit_reasons": by_reason,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--tdxdir", default="/home/lufanfeng/tdx_data")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stop", type=float, default=0.08)
    parser.add_argument("--target", type=float, default=0.20)
    parser.add_argument("--hold-days", type=int, default=20)
    args = parser.parse_args()
    config = ExitConfig(hold_days=args.hold_days, stop_pct=args.stop, target_pct=args.target)
    events = pd.read_csv(args.candidates, dtype={"symbol": str})
    reader = Reader.factory(market="std", tdxdir=args.tdxdir)
    trades, skipped = evaluate_events(events, reader, config)
    summary = summarize(trades, skipped, config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"PB20极致候选_止盈止损研究_stop{args.stop:.0%}_target{args.target:.0%}_hold{args.hold_days}"
    json_path = args.output_dir / f"{stem}_20260930_v1.json"
    csv_path = args.output_dir / f"{stem}_20260930_v1.csv"
    trades.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps({"summary": summary, "trades": trades.to_dict("records")}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "csv": str(csv_path), "json": str(json_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
