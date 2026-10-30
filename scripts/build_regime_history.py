"""Build the full-market A/B/C/D regime history parquet.

Same four gates as the lifecycle build: source staleness, sampled parity between
the vectorised series and the scalar reader, non-finite checks and an atomic
swap. Output is a separate file so the old 13-state dataset stays untouched
until the switch-over is fully verified.

    ~/.venvs/moontdx-china-stock-data/bin/python scripts/build_regime_history.py
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/build_regime_history.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify import MIN_DAYS, prepare_bars  # noqa: E402
from app.stage_regime import (  # noqa: E402
    BREAKOUT_LOOKBACK,
    BREAKOUT_MULT,
    BREAKOUT_RECENT,
    PULLBACK_TOL,
    SCORE_STRONG,
    SELL_DAYS_MIN,
    SELL_WINDOW,
    STALL_VOL_SHRINK,
    STAGE_LABELS,
    VOL_LONG,
    VOL_SHORT,
    WINDOW,
    classify_regime,
)
from app.stage_regime_series import ITEM_KEYS, classify_regime_series  # noqa: E402
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
RPS_PATH = FINAL / "dataset_stock_rps_history.parquet"
DEFAULT_OUTPUT = FINAL / "regime_history.parquet"
MANIFEST = FINAL / "regime_history.manifest.json"
BATCH_SIZE = 200


def manifest_thresholds() -> dict[str, object]:
    return {
        "WINDOW": WINDOW,
        "VOL_SHORT": VOL_SHORT,
        "VOL_LONG": VOL_LONG,
        "BREAKOUT_LOOKBACK": BREAKOUT_LOOKBACK,
        "BREAKOUT_MULT": BREAKOUT_MULT,
        "BREAKOUT_RECENT": BREAKOUT_RECENT,
        "PULLBACK_TOL": PULLBACK_TOL,
        "STALL_VOL_SHRINK": STALL_VOL_SHRINK,
        "SELL_WINDOW": SELL_WINDOW,
        "SELL_DAYS_MIN": SELL_DAYS_MIN,
        "SCORE_STRONG": SCORE_STRONG,
        "MIN_DAYS": MIN_DAYS,
        "STAGE_LABELS": STAGE_LABELS,
    }


def _parquet_schema() -> pa.schema:
    fields = [pa.field("market", pa.string()), pa.field("symbol", pa.string())]
    fields += [
        pa.field("trading_day", pa.string()),
        pa.field("stage", pa.string()),
        pa.field("stage_label", pa.string()),
        pa.field("score", pa.int16()),
        pa.field("reason", pa.string()),
        pa.field("ma20", pa.float64()),
        pa.field("vol_ma5", pa.float64()),
        pa.field("vol_ma60", pa.float64()),
        pa.field("box_high", pa.float64()),
        pa.field("box_low", pa.float64()),
        pa.field("box_mid", pa.float64()),
        pa.field("box_position", pa.float64()),
        pa.field("sell_days_15", pa.float64()),
    ]
    fields += [pa.field(key, pa.bool_()) for key in ITEM_KEYS]
    fields += [pa.field("放量滞涨", pa.bool_()), pa.field("抛售日密集", pa.bool_())]
    return pa.schema(fields)


def load_universe() -> tuple[list[tuple[str, str]], str]:
    """Reuse the RPS universe: one row per tradeable stock on the latest day."""
    frame = pd.read_parquet(RPS_PATH, columns=["trading_day", "market", "symbol"])
    frame["trading_day"] = frame["trading_day"].astype(str)
    latest_day = frame["trading_day"].max()
    latest = frame[frame["trading_day"] == latest_day]
    rows = sorted({
        (str(record["market"]).lower(), str(record["symbol"]).zfill(6))
        for record in latest.to_dict("records")
    })
    return rows, latest_day


def check_source_freshness(universe: list[tuple[str, str]], latest_rps_day: str, sample: int = 30) -> str:
    newest: str | None = None
    checked = 0
    for _, symbol in universe[:sample]:
        try:
            frame = load_tdx_qfq_daily(symbol)
        except Exception:  # noqa: BLE001 - missing exports are counted later
            continue
        checked += 1
        day = frame.index[-1].strftime("%Y-%m-%d")
        if newest is None or day > newest:
            newest = day
    if checked == 0:
        raise SystemExit("STALENESS BLOCKED: no QFQ export could be read")
    if newest != latest_rps_day:
        raise SystemExit(
            f"STALENESS BLOCKED: newest QFQ bar {newest} != RPS trading day {latest_rps_day}. "
            "Re-export front-adjusted daily bars before building regime history."
        )
    return newest


def run_parity_gate(universe: list[tuple[str, str]], sample_size: int, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    picked = rng.sample(universe, min(sample_size, len(universe)))
    checked = mismatch = 0
    for _, symbol in picked:
        try:
            frame = prepare_bars(load_tdx_qfq_daily(symbol))
        except Exception:  # noqa: BLE001
            continue
        if len(frame) <= WINDOW + 5:
            continue
        series = classify_regime_series(frame)
        last = series.iloc[-1]
        if not bool(last["valid"]):
            continue
        scalar = classify_regime(frame)
        checked += 1
        if str(last["stage"]) != scalar["stage"] or int(last["score"]) != scalar["score"]:
            mismatch += 1
    return {"stocks": len(picked), "checked": checked, "mismatch": mismatch}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build full-market A/B/C/D regime history")
    parser.add_argument("--limit", type=int, default=0, help="only the first N stocks (smoke test)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-gates", action="store_true")
    args = parser.parse_args()

    universe, latest_rps_day = load_universe()
    if args.limit:
        universe = universe[: args.limit]
    print(f"universe: {len(universe)} stocks | RPS trading day: {latest_rps_day}", flush=True)

    newest_qfq = None
    parity: dict[str, int] | None = None
    if not args.skip_gates:
        newest_qfq = check_source_freshness(universe, latest_rps_day)
        print(f"stale check: QFQ {newest_qfq} == RPS {latest_rps_day}", flush=True)
        parity = run_parity_gate(universe, min(40, len(universe)), seed=7)
        print(f"parity gate: {parity}", flush=True)
        if parity["mismatch"]:
            raise SystemExit(f"PARITY BLOCKED: {parity['mismatch']} of {parity['checked']} stocks differ")

    tmp = args.output.with_suffix(".parquet.tmp")
    tmp.unlink(missing_ok=True)
    writer = pq.ParquetWriter(tmp, _parquet_schema(), compression="zstd")
    batch: list = []
    stage_counts: dict[str, int] = {}
    rows_written = stocks_used = 0
    skipped: list[str] = []
    first_day = last_day = None

    def flush(items: list) -> None:
        if not items:
            return
        frame = pd.concat(items, ignore_index=True)
        writer.write_table(pa.Table.from_pandas(frame, schema=_parquet_schema(), preserve_index=False))

    started = time.time()
    for index, (market, symbol) in enumerate(universe, start=1):
        try:
            frame = prepare_bars(load_tdx_qfq_daily(symbol))
        except Exception:  # noqa: BLE001
            skipped.append(f"{market}:{symbol}")
            continue
        if len(frame) <= MIN_DAYS:
            skipped.append(f"{market}:{symbol}:short")
            continue
        series = classify_regime_series(frame)
        series = series[series["valid"]].copy()
        if series.empty:
            skipped.append(f"{market}:{symbol}:no_valid_bars")
            continue

        series.insert(0, "symbol", symbol)
        series.insert(0, "market", market)
        series = series.drop(columns=["valid"])

        rows_written += len(series)
        stocks_used += 1
        for code, count in series["stage"].value_counts().items():
            stage_counts[str(code)] = stage_counts.get(str(code), 0) + int(count)
        day_first, day_last = series["trading_day"].iloc[0], series["trading_day"].iloc[-1]
        first_day = day_first if first_day is None or day_first < first_day else first_day
        last_day = day_last if last_day is None or day_last > last_day else last_day

        batch.append(series)
        if len(batch) >= BATCH_SIZE:
            flush(batch)
            batch = []
        if index % 500 == 0:
            elapsed = time.time() - started
            print(f"  {index}/{len(universe)} stocks | rows {rows_written:,} | {elapsed:.0f}s", flush=True)

    flush(batch)
    writer.close()
    os.replace(tmp, args.output)

    manifest = {
        "dataset": "regime_history",
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": stocks_used,
        "rows": rows_written,
        "date_range": [first_day, last_day],
        "stage_counts": dict(sorted(stage_counts.items())),
        "thresholds": manifest_thresholds(),
        "price_basis": "tdx_export_qfq",
        "source_staleness_check": {"rps_trading_day": latest_rps_day, "newest_qfq_bar": newest_qfq},
        "parity": parity,
        "skipped_samples": skipped[:50],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== build summary ===")
    print(f"stocks written : {stocks_used} / {len(universe)} (skipped {len(skipped)})")
    print(f"rows           : {rows_written:,}")
    print(f"date range     : {first_day} .. {last_day}")
    print(f"stage counts   : {json.dumps(dict(sorted(stage_counts.items())), ensure_ascii=False)}")
    print(f"parquet        : {args.output}")
    print(f"manifest       : {MANIFEST}")
    print(f"elapsed        : {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
