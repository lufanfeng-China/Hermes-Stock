#!/usr/bin/env python3
"""Build the full-market lifecycle-stage history parquet.

Every row is the stage of one stock on one trading day, computed **only** from
bars up to and including that day (no lookahead).  The file contains features
only — no forward returns, so it cannot be mistaken for a backtest dataset.

Guards before anything is written
---------------------------------
1. Staleness: the newest QFQ bar must equal the newest RPS trading day.  A
   stale front-adjusted source is blocked rather than silently shipped.
2. Parity: a seeded sample of stocks is compared bar-for-bar against the
   scalar classifier the stock-analysis page uses.  Any divergence aborts.

Outputs (written atomically via .tmp + os.replace)
    data/derived/datasets/final/stage_history.parquet
    data/derived/datasets/final/stage_history.manifest.json

Usage:
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/build_stage_history.py
    ... --limit 300            # smoke build
    ... --since 2018-01-01     # shorter history
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify import BIAS_CLIMAX, FLAT_SLOPE, MIN_DAYS, VOL_BREAKOUT  # noqa: E402
from app.stage_classify_series import classify_stage_series, summarise_series_parity  # noqa: E402
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
RPS_PATH = FINAL / "dataset_stock_rps_history.parquet"
DEFAULT_OUTPUT = FINAL / "stage_history.parquet"
PARITY_WINDOW_BARS = 729  # 3 years, same window the parity gate uses


def _parquet_schema():
    """Explicit, batch-stable schema for the history parquet."""
    import pyarrow as pa

    fields = [
        ("market", pa.string()),
        ("symbol", pa.string()),
        ("trading_day", pa.string()),
        ("region", pa.string()),
        ("stage", pa.string()),
    ]
    fields += [(name, pa.float64()) for name in (
        "ma5", "ma10", "ma20", "ma60", "slope20", "slope60", "slope20_prev",
        "bias20", "pos_high_60", "pos_low_60", "range_pos_60", "vol_ratio",
        "high_20", "low_20", "high_60", "low_60",
    )]
    return pa.schema(fields)


_PARQUET_SCHEMA = _parquet_schema()


def load_universe() -> tuple[list[tuple[str, str]], str]:
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
    """Block when the QFQ export lags the RPS universe date."""
    newest_seen: str | None = None
    checked = 0
    for market, symbol in universe[:sample]:
        try:
            frame = load_tdx_qfq_daily(symbol)
        except Exception:  # noqa: BLE001 - missing exports are counted later
            continue
        checked += 1
        day = frame.index[-1].strftime("%Y-%m-%d")
        if newest_seen is None or day > newest_seen:
            newest_seen = day
    if checked == 0:
        raise SystemExit("STALENESS BLOCKED: no QFQ export could be read")
    if newest_seen != latest_rps_day:
        raise SystemExit(
            f"STALENESS BLOCKED: newest QFQ bar {newest_seen} != RPS trading day {latest_rps_day}. "
            "Re-export front-adjusted daily bars before building stage history."
        )
    return newest_seen


def run_parity_gate(universe: list[tuple[str, str]], sample_size: int, seed: int) -> dict:
    rng = random.Random(seed)
    candidates = [item for item in universe if item[1].startswith(("6", "0", "3", "9"))]
    picked = rng.sample(candidates, min(sample_size, len(candidates)))
    totals = {"stocks": 0, "checked": 0, "region_mismatch": 0, "stage_mismatch": 0, "evidence_mismatch": 0}
    for market, symbol in picked:
        try:
            frame = load_tdx_qfq_daily(symbol)
        except Exception:  # noqa: BLE001
            continue
        if len(frame) > PARITY_WINDOW_BARS:
            frame = frame.iloc[-PARITY_WINDOW_BARS:]
        if len(frame) < MIN_DAYS + 1:
            continue
        result = summarise_series_parity(frame)
        totals["stocks"] += 1
        for key in ("checked", "region_mismatch", "stage_mismatch", "evidence_mismatch"):
            totals[key] += result[key]
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description="Build full-market stage history")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="only the first N stocks (smoke build)")
    parser.add_argument("--since", default=None, help="drop bars before this YYYY-MM-DD")
    parser.add_argument("--parity-sample", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--skip-parity", action="store_true", help="only for debugging; never for delivery")
    args = parser.parse_args()

    universe, latest_rps_day = load_universe()
    if args.limit:
        universe = universe[: args.limit]
    print(f"universe: {len(universe)} stocks | RPS trading day: {latest_rps_day}")

    newest_bar = check_source_freshness(universe, latest_rps_day)
    print(f"freshness: newest QFQ bar {newest_bar} == RPS day -> OK")

    parity = {"stocks": 0, "checked": 0, "region_mismatch": 0, "stage_mismatch": 0, "evidence_mismatch": 0}
    if not args.skip_parity:
        started = time.time()
        parity = run_parity_gate(universe, args.parity_sample, args.seed)
        print(f"parity: {parity['checked']} bars over {parity['stocks']} stocks | "
              f"region={parity['region_mismatch']} stage={parity['stage_mismatch']} "
              f"evidence={parity['evidence_mismatch']} | {time.time() - started:.0f}s")
        if parity["region_mismatch"] or parity["stage_mismatch"] or parity["evidence_mismatch"]:
            print("PARITY BLOCKED: vectorised path diverges from the scalar classifier; nothing written")
            return 1

    output = args.output
    tmp_path = output.with_suffix(output.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    since = pd.Timestamp(args.since) if args.since else None
    writer = None
    stage_counts: dict[str, int] = {}
    rows_written = 0
    stocks_used = 0
    stocks_skipped: list[str] = []
    first_day: str | None = None
    last_day: str | None = None
    started = time.time()

    def flush(frames: list[pd.DataFrame]) -> None:
        nonlocal writer
        import pyarrow as pa
        import pyarrow.parquet as pq

        frame = pd.concat(frames, ignore_index=True)
        # explicit schema: category dtype would encode dictionary indices as int8/int16
        # depending on cardinality, and a later row group would no longer match.
        table = pa.Table.from_pandas(frame, schema=_PARQUET_SCHEMA, preserve_index=False, safe=False)
        if writer is None:
            writer = pq.ParquetWriter(tmp_path, table.schema, compression="zstd")
        writer.write_table(table)

    batch: list[pd.DataFrame] = []
    for index, (market, symbol) in enumerate(universe, start=1):
        try:
            frame = load_tdx_qfq_daily(symbol)
        except Exception:  # noqa: BLE001 - delisted / missing export
            stocks_skipped.append(f"{market}:{symbol}")
            continue
        if since is not None:
            frame = frame[frame.index >= since]
        if len(frame) <= MIN_DAYS:
            stocks_skipped.append(f"{market}:{symbol}:short")
            continue

        series = classify_stage_series(frame)
        series = series[series["valid"]].copy()
        if series.empty:
            stocks_skipped.append(f"{market}:{symbol}:no_valid_bars")
            continue

        series.insert(0, "symbol", symbol)
        series.insert(0, "market", market)
        series["region"] = series["region"].astype("category")
        series["stage"] = series["stage"].astype("category")
        series = series.drop(columns=["valid"])

        rows_written += len(series)
        stocks_used += 1
        for code, count in series["stage"].value_counts().items():
            stage_counts[str(code)] = stage_counts.get(str(code), 0) + int(count)
        day_first, day_last = series["trading_day"].iloc[0], series["trading_day"].iloc[-1]
        first_day = day_first if first_day is None or day_first < first_day else first_day
        last_day = day_last if last_day is None or day_last > last_day else last_day

        batch.append(series)
        if len(batch) >= 200:
            flush(batch)
            batch = []

        if index % 500 == 0:
            elapsed = time.time() - started
            print(f"  {index}/{len(universe)} stocks | rows {rows_written:,} | {elapsed:.0f}s "
                  f"({elapsed / index * 1000:.0f}ms/stock)")

    if batch:
        flush(batch)
    if writer is not None:
        writer.close()

    if rows_written == 0:
        if tmp_path.exists():
            tmp_path.unlink()
        print("nothing written: no stock produced valid bars")
        return 1

    os.replace(tmp_path, output)

    try:
        parquet_label = str(output.relative_to(PROJECT_ROOT))
    except ValueError:  # out-of-tree output (smoke builds to /tmp)
        parquet_label = str(output)

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "parquet": parquet_label,
        "source": "TDX front-adjusted daily export (app.tdx.qfq_kline)",
        "price_basis": "tdx_export_qfq",
        "lookahead": "none — each row uses bars up to and including its trading_day",
        "forward_returns": "not stored by design; compute separately for evaluation only",
        "source_staleness_check": {"newest_qfq_bar": newest_bar, "rps_trading_day": latest_rps_day},
        "parity": parity,
        "thresholds": {
            "FLAT_SLOPE": FLAT_SLOPE,
            "BIAS_CLIMAX": BIAS_CLIMAX,
            "VOL_BREAKOUT": VOL_BREAKOUT,
            "MIN_DAYS": MIN_DAYS,
        },
        "universe": {"requested": len(universe), "stocks_written": stocks_used,
                     "stocks_skipped": len(stocks_skipped)},
        "rows": rows_written,
        "date_range": {"first": first_day, "last": last_day, "since_filter": args.since},
        "stage_counts": dict(sorted(stage_counts.items())),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    manifest_path = output.with_suffix(".manifest.json")
    tmp_manifest = manifest_path.with_suffix(".json.tmp")
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_manifest, manifest_path)

    print("\n=== build summary ===")
    print(f"stocks written : {stocks_used} / {len(universe)} (skipped {len(stocks_skipped)})")
    print(f"rows           : {rows_written:,}")
    print(f"date range     : {first_day} .. {last_day}")
    print(f"stage counts   : {json.dumps(dict(sorted(stage_counts.items())), ensure_ascii=False)}")
    print(f"parquet        : {output}")
    print(f"manifest       : {manifest_path}")
    print(f"elapsed        : {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
