#!/usr/bin/env python3
"""Compare canonical CSI300 MACD extreme-GC cash/MTM with a primary-temp==3 gate.

Signal contract (both variants): QFQ daily bars form MACD, MA10 and concept
10-day temperature; raw TDX bars execute all orders at the next open and mark
all open positions at raw closes.  The ``temp3`` variant permits BOTH the
initial entry and every replenish order only when the stock's dynamically
selected primary current-mapping concept has temperature exactly 3.

This is research, not an investable point-in-time test: the supplied TDX
concept membership mapping is current and is applied retrospectively.  Its
historical use has survivorship and lookahead bias; the JSON artifact records
that limitation prominently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from mootdx.reader import Reader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.concept_temperature import build_temperature_rows, parse_tdx_concept_mapping
from app.strategy.macd_backtest_engine import simulate_portfolio
from app.tdx.qfq_kline import align_qfq_signal_with_raw_execution, load_tdx_qfq_daily

DEFAULT_CONSTITUENTS = ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"
DEFAULT_MAPPING = Path("/mnt/c/new_tdx64/T0002/export/概念板块.txt")
DEFAULT_RAW_TDX = Path("/mnt/c/new_tdx64")
DEFAULT_OUTPUT = ROOT / "data/derived/research/macd_extreme_gc_csi300_primary_temp3_mtm_2015_onward.json"
END = pd.Timestamp("2026-07-25")  # Same canonical as-of date as run_macd_backtest_v2_cash_mtm.py.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=str(END.date()), help="Inclusive signal/MTM end date")
    parser.add_argument("--capital", type=float, default=3_000_000)
    parser.add_argument("--lot", type=float, default=50_000)
    parser.add_argument("--temperature-window", type=int, default=10)
    parser.add_argument("--min-members", type=int, default=10)
    parser.add_argument("--constituents", type=Path, default=DEFAULT_CONSTITUENTS)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--raw-tdx", type=Path, default=DEFAULT_RAW_TDX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_codes(path: Path) -> list[str]:
    codes = sorted({str(code).zfill(6) for code in json.loads(path.read_text(encoding="utf-8"))})
    if len(codes) != 300:
        raise ValueError(f"Expected exactly 300 current CSI300 constituents in {path}; got {len(codes)}")
    return codes


def build_signal_bars(raw_daily: pd.DataFrame, qfq_daily: pd.DataFrame) -> pd.DataFrame:
    """Match the canonical v2 runner exactly: QFQ signal features / raw execution."""
    aligned = align_qfq_signal_with_raw_execution(raw_daily, qfq_daily)
    bars = aligned[["raw_open", "raw_close", "signal_close"]].rename(
        columns={"raw_open": "open", "raw_close": "close"}
    ).copy()
    signal_close = bars["signal_close"].astype(float)
    dif = signal_close.ewm(span=12, adjust=False).mean() - signal_close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    bars["ndif"] = np.divide(dif, signal_close, out=np.zeros(len(bars)), where=signal_close != 0) * 100.0
    bars["ndea"] = np.divide(dea, signal_close, out=np.zeros(len(bars)), where=signal_close != 0) * 100.0
    ma10 = signal_close.rolling(10).mean()
    golden = (bars["ndif"] > bars["ndea"]) & (bars["ndif"].shift(1) <= bars["ndea"].shift(1))
    dead = (bars["ndif"] < bars["ndea"]) & (bars["ndif"].shift(1) >= bars["ndea"].shift(1))
    buy = golden & (bars["ndif"] < -1.0) & (ma10 > ma10.shift(1))
    bars["buy_signal"] = buy.fillna(False)
    bars["replenish_signal"] = (buy & (bars["ndif"] < -3.0)).fillna(False)
    bars["dead_cross"] = dead.fillna(False)
    return bars


def qfq_frames_for_temperature(mapping: list[dict[str, str]], *, start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Load only mapped QFQ series once, preserving enough pre-start history.

    Temperature is later calculated *only* for dates at which the canonical
    CSI300 strategy has a buy or replenish candidate.  ``build_temperature_rows``
    receives clipped frames, so its return/volume window never observes a
    future bar.
    """
    symbols = sorted({row["symbol"] for row in mapping})
    frames: dict[str, pd.DataFrame] = {}
    missing = invalid = 0
    # 25 bars is the longest temperature feature lookback; calendar cushion
    # allows holiday gaps without needlessly parsing the entire output file.
    preload = start - pd.Timedelta(days=70)
    for symbol in symbols:
        try:
            frame = load_tdx_qfq_daily(symbol)
        except FileNotFoundError:
            missing += 1
            continue
        except ValueError:
            invalid += 1
            continue
        clipped = frame[(frame.index >= preload) & (frame.index <= end)]
        if len(clipped) >= 25:
            frames[symbol] = clipped
    return frames, {"mapping_symbols": len(symbols), "loaded_qfq_symbols": len(frames), "missing_qfq_symbols": missing, "invalid_qfq_symbols": invalid}


def primary_temp_by_symbol(
    *, mapping: list[dict[str, str]], qfq_frames: dict[str, pd.DataFrame], dates: list[pd.Timestamp], window: int, min_members: int
) -> tuple[dict[pd.Timestamp, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    """Compute primary-concept state only at canonical candidate signal dates.

    Primary concept selection is deterministic and exact: highest numerical
    temperature, then heat score, then breadth, then global concept rank.  The
    rank is rebuilt on each date from that same four-key ordering, so it is not
    a future/static field. Concepts with insufficient data (temperature=None)
    cannot pass the exact temp==3 gate.
    """
    mapping_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in mapping:
        mapping_by_symbol[row["symbol"]].append(row)
    out: dict[pd.Timestamp, dict[str, dict[str, Any]]] = {}
    diagnostics: list[dict[str, Any]] = []
    for as_of in dates:
        # Supply only the 25-bar trailing slice per stock.  This is mathematically
        # sufficient for the 10-day return plus 5d/20d volume feature, avoids
        # copying full multi-year frames for every candidate signal date, and
        # excludes any bar after ``as_of`` by construction.
        trailing: dict[str, pd.DataFrame] = {}
        for symbol, frame in qfq_frames.items():
            position = frame.index.searchsorted(as_of, side="right") - 1
            if position < 24 or frame.index[position] != as_of:
                continue
            trailing[symbol] = frame.iloc[position - 24:position + 1]
        rows, _ = build_temperature_rows(mapping, trailing, window=window, min_members=min_members, include_members=False)
        ranked = sorted(
            rows,
            key=lambda row: (
                -(int(row["temperature"]) if row["temperature"] is not None else -1),
                -float(row["heat_score"]),
                -float(row["breadth_pct"]),
                str(row["concept_code"]),
            ),
        )
        by_concept = {row["concept_code"]: {**row, "rank": rank} for rank, row in enumerate(ranked, start=1)}
        selected: dict[str, dict[str, Any]] = {}
        for symbol, memberships in mapping_by_symbol.items():
            candidates = [by_concept[row["concept_code"]] for row in memberships if row["concept_code"] in by_concept]
            if not candidates:
                continue
            primary = min(
                candidates,
                key=lambda row: (
                    -(int(row["temperature"]) if row["temperature"] is not None else -1),
                    -float(row["heat_score"]),
                    -float(row["breadth_pct"]),
                    int(row["rank"]),
                ),
            )
            selected[symbol] = primary
        out[as_of] = selected
        diagnostics.append({
            "date": str(as_of.date()), "concepts_calculated": len(rows), "ranked_concepts": len(ranked),
            "symbols_with_primary": len(selected), "temp3_concepts": sum(row["temperature"] == 3 for row in rows),
        })
    return out, diagnostics


def validate_result(result: dict[str, Any], initial_capital: float) -> None:
    for point in result["daily_equity"]:
        if abs(float(point["equity"]) - float(point["cash"]) - float(point["market_value"])) > 0.01:
            raise RuntimeError(f"Daily MTM invariant failed on {point['date']}")
    summary = result["summary"]
    expected = initial_capital + float(summary["realized_pnl"]) + float(summary["unrealized_pnl"])
    if abs(float(summary["equity"]) - expected) > 0.01:
        raise RuntimeError("Terminal cash/MTM accounting invariant failed")


def compact_result(result: dict[str, Any], initial_capital: float) -> dict[str, Any]:
    validate_result(result, initial_capital)
    summary = result["summary"]
    return {
        "executed_orders": int(result["executed"]), "rejected_orders": int(result["rejected"]),
        "closed_positions": len(result["history"]), "open_positions": len(result["positions"]),
        "cash": round(float(summary["cash"]), 2), "market_value": round(float(summary["market_value"]), 2),
        "realized_pnl": round(float(summary["realized_pnl"]), 2), "unrealized_pnl": round(float(summary["unrealized_pnl"]), 2),
        "equity": round(float(summary["equity"]), 2),
        "return_pct": round((float(summary["equity"]) / initial_capital - 1) * 100, 4),
        "daily_mtm_points": len(result["daily_equity"]),
        "accounting_invariant": "passed: daily equity=cash+market_value; terminal equity=initial+realized+unrealized",
    }


def main() -> None:
    args = parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if end > END:
        raise ValueError(f"End must not exceed canonical available as-of {END.date()}")
    if args.temperature_window <= 0 or args.min_members <= 0:
        raise ValueError("temperature-window and min-members must be positive")
    lookback = pd.Timestamp(year=start.year - 1, month=7, day=1)
    codes = load_codes(args.constituents)

    reader = Reader.factory(market="std", tdxdir=str(args.raw_tdx))
    baseline_bars: dict[str, pd.DataFrame] = {}
    raw_loaded = qfq_loaded = 0
    for code in codes:
        try:
            raw = reader.daily(code)
        except Exception:
            continue
        if raw is None or len(raw) < 100:
            continue
        raw_loaded += 1
        try:
            qfq = load_tdx_qfq_daily(code)
        except (FileNotFoundError, ValueError):
            continue
        qfq_loaded += 1
        raw = raw.sort_index()[(raw.index >= lookback) & (raw.index <= end)]
        qfq = qfq[(qfq.index >= lookback) & (qfq.index <= end)]
        if len(raw) < 100 or len(qfq) < 100:
            continue
        bars = build_signal_bars(raw, qfq)
        bars = bars[bars.index >= start]
        if len(bars) >= 2:
            baseline_bars[code] = bars
    if not baseline_bars:
        raise RuntimeError("No CSI300 raw/QFQ bars loaded")

    candidate_dates = sorted({date for frame in baseline_bars.values() for date, row in frame.iterrows() if bool(row["buy_signal"]) or bool(row["replenish_signal"])})
    raw_mapping = args.mapping.read_bytes()
    mapping = parse_tdx_concept_mapping(raw_mapping.decode("gb18030"))
    if not mapping:
        raise RuntimeError(f"No mappings parsed from {args.mapping}")
    temperature_frames, temp_load = qfq_frames_for_temperature(mapping, start=start, end=end)
    primary_by_date, temperature_diagnostics = primary_temp_by_symbol(
        mapping=mapping, qfq_frames=temperature_frames, dates=candidate_dates,
        window=args.temperature_window, min_members=args.min_members,
    )

    gated_bars: dict[str, pd.DataFrame] = {}
    entry_candidates = replenishment_candidates = entry_temp3 = replenishment_temp3 = 0
    for code, bars in baseline_bars.items():
        gated = bars.copy()
        entry_gate: list[bool] = []
        replenish_gate: list[bool] = []
        for date, row in gated.iterrows():
            primary = primary_by_date.get(date, {}).get(code)
            gate = bool(primary and primary.get("temperature") == 3)
            is_entry = bool(row["buy_signal"])
            is_replenish = bool(row["replenish_signal"])
            entry_candidates += int(is_entry)
            replenishment_candidates += int(is_replenish)
            entry_temp3 += int(is_entry and gate)
            replenishment_temp3 += int(is_replenish and gate)
            entry_gate.append(is_entry and gate)
            replenish_gate.append(is_replenish and gate)
        gated["buy_signal"] = entry_gate
        gated["replenish_signal"] = replenish_gate
        gated_bars[code] = gated

    baseline = simulate_portfolio(baseline_bars, initial_capital=args.capital, lot_cash=args.lot)
    temp3 = simulate_portfolio(gated_bars, initial_capital=args.capital, lot_cash=args.lot)
    payload = {
        "research_title": "CSI300 MACD extreme golden-cross: canonical baseline vs primary-concept temperature exactly 3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reproducibility": {
            "script": str(Path(__file__).resolve()), "command": " ".join(sys.argv),
            "constituents": str(args.constituents), "constituents_count": len(codes),
            "mapping": str(args.mapping), "mapping_sha256": hashlib.sha256(raw_mapping).hexdigest(), "mapping_rows": len(mapping),
        },
        "contract": {
            "period": [str(start.date()), str(end.date())], "universe": "current CSI300 constituents (300)",
            "macd_and_temperature_signal_prices": "Tongdaxin QFQ daily", "execution": "raw TDX next available open (T+1)",
            "mark_to_market": "raw TDX close daily; equity=cash+market_value", "capital": args.capital, "lot_cash": args.lot,
            "canonical_macd": "golden cross, ndif < -1%, MA10 rising; replenish candidate additionally ndif < -3% and held PnL < -20%; arm above +20%, exit T+1 on dead cross or below +15%",
            "temperature": {"window_trading_days": args.temperature_window, "min_members": args.min_members, "calculated_only_on_canonical_candidate_signal_dates": len(candidate_dates)},
            "primary_concept": "highest temperature, then heat_score, then breadth_pct, then same-day global rank; gate requires temperature == 3 for entries AND replenishments",
        },
        "critical_limitation": "SURVIVORSHIP/LOOKAHEAD LIMITATION: mapping is the current TDX concept-board file and is retrospectively applied to 2015 onward. It is not a point-in-time historical membership dataset; results must not be interpreted as bias-free historical performance.",
        "load_coverage": {"csi300_raw_loaded": raw_loaded, "csi300_qfq_loaded": qfq_loaded, "csi300_bars_used": len(baseline_bars), **temp_load},
        "signal_funnel": {"canonical_entry_candidates": entry_candidates, "entry_candidates_primary_temp_exactly_3": entry_temp3, "canonical_replenishment_candidates": replenishment_candidates, "replenishment_candidates_primary_temp_exactly_3": replenishment_temp3},
        "temperature_dates": temperature_diagnostics,
        "results": {"baseline": compact_result(baseline, args.capital), "primary_temp_exactly_3_gate": compact_result(temp3, args.capital)},
    }
    payload["comparison"] = {
        "equity_delta_temp3_minus_baseline": round(payload["results"]["primary_temp_exactly_3_gate"]["equity"] - payload["results"]["baseline"]["equity"], 2),
        "return_pct_delta_temp3_minus_baseline": round(payload["results"]["primary_temp_exactly_3_gate"]["return_pct"] - payload["results"]["baseline"]["return_pct"], 4),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "candidate_dates": len(candidate_dates), "baseline": payload["results"]["baseline"], "temp3": payload["results"]["primary_temp_exactly_3_gate"], "comparison": payload["comparison"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
