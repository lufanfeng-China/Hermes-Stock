#!/usr/bin/env python3
"""Research a no-lookahead pre-surge breakout-confirmation candle from QFQ exports.

This is an exploratory cohort study, not a trading system.  Signals are known at
T close; the label is deliberately computed only from T+1 through T+20 highs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from mootdx.reader import Reader

from app.config import TDX_QFQ_EXPORT_DIR, TONGDAXIN_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

FUTURE_DAYS = 20
SURGE_THRESHOLD = 0.30
MIN_HISTORY = 65


def _future_high_excluding_signal_day(high: pd.Series, days: int = FUTURE_DAYS) -> pd.Series:
    """Return the maximum high strictly after each signal bar through T+days."""
    return pd.concat([high.shift(-offset) for offset in range(1, days + 1)], axis=1).max(axis=1)


def compute_confirmation_rows(
    frame: pd.DataFrame, symbol: str, start_day: str, raw_frame: pd.DataFrame | None = None
) -> list[dict[str, Any]]:
    """Return QFQ T-close signals with raw-price T+1..T+20 research labels."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")
    bars = frame.copy().sort_index()
    raw = bars if raw_frame is None else raw_frame.copy().sort_index().reindex(bars.index)
    raw_missing = required.difference(raw.columns)
    if raw_missing:
        raise ValueError(f"raw frame is missing OHLCV columns: {sorted(raw_missing)}")
    if len(bars) < MIN_HISTORY + FUTURE_DAYS:
        return []

    prior_20_high = bars["high"].shift(1).rolling(20, min_periods=20).max()
    volume_ma20 = bars["volume"].shift(1).rolling(20, min_periods=20).mean()
    ma20 = bars["close"].rolling(20, min_periods=20).mean()
    ma60 = bars["close"].rolling(60, min_periods=60).mean()
    day_range = bars["high"] - bars["low"]
    body_ratio = (bars["close"] - bars["open"]).abs() / day_range.where(day_range > 0)
    close_location = (bars["close"] - bars["low"]) / day_range.where(day_range > 0)
    volume_ratio = bars["volume"] / volume_ma20.where(volume_ma20 > 0)
    raw_entry_open = raw["open"].shift(-1)
    raw_future_high = _future_high_excluding_signal_day(raw["high"])
    raw_future_complete = raw["high"].shift(-FUTURE_DAYS).notna()
    raw_future_max_return = raw_future_high / raw_entry_open - 1.0

    signal = (
        (bars["close"] > prior_20_high)
        & (body_ratio >= 0.60)
        & (close_location >= 0.80)
        & (volume_ratio >= 1.50)
        & (volume_ratio <= 3.50)
        & (bars["close"] <= ma20 * 1.12)
        & (bars["close"] > ma20)
        & (ma20 > ma60)
        & (ma20 > ma20.shift(5))
        & raw_future_complete
        & raw_entry_open.notna()
        & (raw_entry_open > 0)
        & (raw["volume"].shift(-1) > 0)
        & (bars.index >= pd.Timestamp(start_day))
    )

    rows: list[dict[str, Any]] = []
    for position in bars.index[signal]:
        idx = bars.index.get_loc(position)
        if isinstance(idx, slice):
            continue
        rows.append(
            {
                "symbol": str(symbol).zfill(6),
                "trading_day": position.date().isoformat(),
                "close": round(float(bars.at[position, "close"]), 6),
                "prior_20_high": round(float(prior_20_high.at[position]), 6),
                "breakout_pct": round(float(bars.at[position, "close"] / prior_20_high.at[position] - 1), 6),
                "body_ratio": round(float(body_ratio.at[position]), 6),
                "close_location": round(float(close_location.at[position]), 6),
                "volume_ratio": round(float(volume_ratio.at[position]), 6),
                "ma20_gap": round(float(bars.at[position, "close"] / ma20.at[position] - 1), 6),
                "entry_date": bars.index[idx + 1].date().isoformat(),
                "entry_open_raw": round(float(raw_entry_open.at[position]), 6),
                "future_20_max_return": round(float(raw_future_max_return.at[position]), 6),
                "is_surge_30pct": bool(raw_future_max_return.at[position] >= SURGE_THRESHOLD),
                "next_trading_day": bars.index[idx + 1].date().isoformat(),
            }
        )
    return rows


def compute_funnel_counts(frame: pd.DataFrame, raw_frame: pd.DataFrame, start_day: str) -> dict[str, dict[str, int]]:
    """Measure each confirmation layer against the same raw T+1..T+20 outcome."""
    bars = frame.copy().sort_index()
    raw = raw_frame.copy().sort_index().reindex(bars.index)
    prior_20_high = bars["high"].shift(1).rolling(20, min_periods=20).max()
    volume_ma20 = bars["volume"].shift(1).rolling(20, min_periods=20).mean()
    ma20 = bars["close"].rolling(20, min_periods=20).mean()
    ma60 = bars["close"].rolling(60, min_periods=60).mean()
    day_range = bars["high"] - bars["low"]
    body_ratio = (bars["close"] - bars["open"]).abs() / day_range.where(day_range > 0)
    close_location = (bars["close"] - bars["low"]) / day_range.where(day_range > 0)
    volume_ratio = bars["volume"] / volume_ma20.where(volume_ma20 > 0)
    raw_entry_open = raw["open"].shift(-1)
    raw_future_high = _future_high_excluding_signal_day(raw["high"])
    raw_future_return = raw_future_high / raw_entry_open - 1.0
    complete_executable = (
        raw["high"].shift(-FUTURE_DAYS).notna()
        & raw_entry_open.notna()
        & (raw_entry_open > 0)
        & (raw["volume"].shift(-1) > 0)
        & (bars.index >= pd.Timestamp(start_day))
    )
    trend = complete_executable & (bars["close"] > ma20) & (ma20 > ma60) & (ma20 > ma20.shift(5))
    breakout = trend & (bars["close"] > prior_20_high)
    strong_candle = breakout & (body_ratio >= 0.60) & (close_location >= 0.80) & (bars["close"] <= ma20 * 1.12)
    volume_confirmed = strong_candle & (volume_ratio >= 1.50) & (volume_ratio <= 3.50)

    def measure(mask: pd.Series) -> dict[str, int]:
        return {"candidates": int(mask.sum()), "surges": int((mask & (raw_future_return >= SURGE_THRESHOLD)).sum())}

    return {
        "trend_background": measure(trend),
        "breakout": measure(breakout),
        "strong_candle": measure(strong_candle),
        "volume_confirmed": measure(volume_confirmed),
    }


def _export_symbols(export_dir: Path) -> list[str]:
    return sorted({path.stem.split("#", 1)[1] for path in export_dir.glob("*#*.txt") if "#" in path.stem})


def _summary(
    rows: list[dict[str, Any]], files_seen: int, failures: list[str], funnel: dict[str, dict[str, int]]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition": {
            "signal": "prior-20-day high breakout + strong body + upper-range close + 1.5-3.5x prior volume MA20 + close>MA20>MA60 + rising MA20",
            "signal_price_basis": "tdx_export_qfq",
            "label": "raw T+1 open entry; maximum raw high from T+1 through T+20 / entry open - 1 >= 30%",
            "future_days": FUTURE_DAYS,
            "surge_threshold": SURGE_THRESHOLD,
            "execution": "requires raw T+1 open>0 and volume>0; one-word limit-up filtering remains a separate audit",
        },
        "files_seen": files_seen,
        "files_failed": len(failures),
        "candidate_count": len(rows),
        "surge_count": sum(row["is_surge_30pct"] for row in rows),
        "surge_rate": round(sum(row["is_surge_30pct"] for row in rows) / len(rows), 6) if rows else None,
        "nested_funnel": {
            name: {
                **values,
                "surge_rate": round(values["surges"] / values["candidates"], 6) if values["candidates"] else None,
            }
            for name, values in funnel.items()
        },
        "failures": failures[:30],
    }
    if rows:
        data = pd.DataFrame(rows)
        data["year"] = pd.to_datetime(data["trading_day"]).dt.year
        by_year = data.groupby("year").agg(candidates=("symbol", "size"), surges=("is_surge_30pct", "sum"), median_return=("future_20_max_return", "median"))
        result["candidate_year_cohorts"] = [
            {
                "year": int(year),
                "candidates": int(row.candidates),
                "surges": int(row.surges),
                "surge_rate": round(float(row.surges / row.candidates), 6),
                "median_future_20_max_return": round(float(row.median_return), 6),
            }
            for year, row in by_year.iterrows()
        ]
        result["return_distribution"] = {
            "mean": round(float(data["future_20_max_return"].mean()), 6),
            "median": round(float(data["future_20_max_return"].median()), 6),
            "p75": round(float(data["future_20_max_return"].quantile(0.75)), 6),
            "p90": round(float(data["future_20_max_return"].quantile(0.90)), 6),
        }
        data["volume_bucket"] = pd.cut(data["volume_ratio"], [1.5, 2.0, 2.5, 3.0, 3.5], include_lowest=True)
        grouped = data.groupby("volume_bucket", observed=False).agg(candidates=("symbol", "size"), surges=("is_surge_30pct", "sum"), mean_return=("future_20_max_return", "mean"))
        result["volume_bucket_comparison"] = [
            {
                "bucket": str(index),
                "candidates": int(row.candidates),
                "surges": int(row.surges),
                "surge_rate": round(float(row.surges / row.candidates), 6) if row.candidates else None,
                "mean_future_20_max_return": round(float(row.mean_return), 6) if row.candidates else None,
            }
            for index, row in grouped.iterrows()
        ]
        result["top_surge_examples"] = sorted(
            (row for row in rows if row["is_surge_30pct"]), key=lambda row: row["future_20_max_return"], reverse=True
        )[:30]
    return result


def versioned_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / f"{stem}_v1{suffix}"
    version = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}_v{version}{suffix}"
        version += 1
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qfq-export-dir", type=Path, default=TDX_QFQ_EXPORT_DIR)
    parser.add_argument("--tdxdir", default=TONGDAXIN_DIR)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--output-dir", type=Path, default=Path("/mnt/c/Users/Sky.Lu/Desktop/output"))
    parser.add_argument("--limit", type=int, default=0, help="Process only first N symbols; 0 means all.")
    args = parser.parse_args()

    symbols = _export_symbols(args.qfq_export_dir)
    if args.limit:
        symbols = symbols[: args.limit]
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    funnel = {name: {"candidates": 0, "surges": 0} for name in ("trend_background", "breakout", "strong_candle", "volume_confirmed")}
    reader = Reader.factory(market="std", tdxdir=args.tdxdir)
    for number, symbol in enumerate(symbols, start=1):
        try:
            qfq = load_tdx_qfq_daily(symbol, args.qfq_export_dir)
            raw = reader.daily(symbol)
            if raw is None or raw.empty:
                raise ValueError("raw daily data is absent")
            rows.extend(compute_confirmation_rows(qfq, symbol, args.start, raw_frame=raw))
            for name, values in compute_funnel_counts(qfq, raw_frame=raw, start_day=args.start).items():
                funnel[name]["candidates"] += values["candidates"]
                funnel[name]["surges"] += values["surges"]
        except Exception as exc:  # Preserve a full-market study when individual exports are malformed.
            failures.append(f"{symbol}: {exc}")
        if number % 500 == 0:
            print(json.dumps({"progress": number, "candidates": len(rows), "failures": len(failures)}, ensure_ascii=False), flush=True)

    summary = _summary(rows, len(symbols), failures, funnel)
    stamp = date.today().strftime("%Y%m%d")
    stem = f"暴涨前确认K线_QFQ研究_{args.start}_至当前_{stamp}"
    json_path = versioned_output_path(args.output_dir, stem, ".json")
    json_path.write_text(json.dumps({"summary": summary, "candidates": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = versioned_output_path(args.output_dir, stem, ".txt")
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + f"\n\nMachine-readable detail: {json_path}\n", encoding="utf-8")
    print(json.dumps({"ok": True, "summary": summary, "json": str(json_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
