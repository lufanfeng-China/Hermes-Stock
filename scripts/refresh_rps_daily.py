#!/usr/bin/env python3
"""Atomically refresh cross-sectional RPS datasets from Tongdaxin QFQ exports only.

The raw TDX daily feed is used solely as a freshness gate.  RPS signals are
never calculated from raw prices: if QFQ exports do not reach the raw feed's
latest trading day this command fails before changing any dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import TDX_QFQ_EXPORT_DIR
from app.data.rps_paths import RPS_MANIFEST_FILENAME, resolve_rps_dataset_path
from app.tdx.qfq_kline import load_tdx_qfq_daily

DEFAULT_TDX_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_REFERENCE_SYMBOL = "601600"
DEFAULT_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
RPS_COLUMNS = ["trading_day", "market", "symbol", "price_basis", "rps_20", "rps_50", "rps_120", "rps_250"]
MIN_ELIGIBLE_UNIVERSE = 2


class QfqCoverageError(RuntimeError):
    """Raised when the QFQ source is not fresh enough for an RPS refresh."""


def require_qfq_covers_raw(raw_latest_day: str, qfq_latest_day: str) -> None:
    if qfq_latest_day < raw_latest_day:
        raise QfqCoverageError(
            "QFQ export data is stale: raw TDX latest trading day is "
            f"{raw_latest_day}, but QFQ latest trading day is {qfq_latest_day}. "
            "export QFQ data from Tongdaxin through the raw latest trading day "
            "and rerun refresh_rps_daily; raw prices will not be used as a fallback."
        )


def _frame_dates(frame: pd.DataFrame) -> list[str]:
    return frame.index.strftime("%Y-%m-%d").tolist()


def reference_qfq_calendar(
    qfq_series: dict[tuple[str, str], pd.DataFrame], reference_symbol: str, raw_latest_day: str
) -> list[str]:
    """Return the declared QFQ reference calendar after proving it is fresh."""
    reference_symbol = reference_symbol.zfill(6)
    matches = [(key, frame) for key, frame in qfq_series.items() if key[1] == reference_symbol]
    if len(matches) != 1:
        raise QfqCoverageError(
            f"Expected exactly one QFQ reference calendar for {reference_symbol}, found {len(matches)}"
        )
    _, reference_frame = matches[0]
    dates = _frame_dates(reference_frame)
    if not dates:
        raise QfqCoverageError(f"QFQ reference calendar for {reference_symbol} is empty")
    try:
        require_qfq_covers_raw(raw_latest_day, dates[-1])
    except QfqCoverageError as exc:
        raise QfqCoverageError(
            f"Declared reference QFQ calendar for {reference_symbol} is stale: {exc}"
        ) from exc
    return dates


def _market_for_export(path: Path) -> str:
    prefix = path.name.split("#", 1)[0].lower()
    return {"sh": "sh", "sz": "sz", "bj": "bj"}.get(prefix, prefix)


def _symbol_for_export(path: Path) -> str:
    name = path.stem
    try:
        return name.split("#", 1)[1].zfill(6)
    except IndexError as exc:
        raise ValueError(f"Unexpected QFQ export filename: {path.name}") from exc


def _latest_raw_trading_day(tdxdir: str, symbol: str) -> str:
    from mootdx.reader import Reader

    reader = Reader.factory(market="std", tdxdir=tdxdir)
    daily = reader.daily(symbol=symbol)
    if daily is None or daily.empty:
        raise RuntimeError(f"No raw TDX daily bars available for reference symbol {symbol}")
    return pd.Timestamp(daily.index.max()).date().isoformat()


def load_qfq_series(export_dir: Path) -> dict[tuple[str, str], pd.DataFrame]:
    series: dict[tuple[str, str], pd.DataFrame] = {}
    for path in sorted(Path(export_dir).glob("*#*.txt")):
        try:
            market = _market_for_export(path)
            symbol = _symbol_for_export(path)
            daily = load_tdx_qfq_daily(symbol, export_dir=export_dir)
        except (FileNotFoundError, ValueError):
            continue
        if len(daily) >= 251:
            series[(market, symbol)] = daily.sort_index()
    if not series:
        raise RuntimeError(f"No QFQ exports with at least 251 daily bars found in {export_dir}")
    return series


def _rank_rps(rows: list[dict[str, Any]], field: str) -> dict[tuple[str, str], float | None]:
    ordered = sorted(rows, key=lambda row: float(row[field]), reverse=True)
    size = len(ordered)
    return {
        (row["market"], row["symbol"]): round((size - rank + 1) / size * 100.0, 2)
        for rank, row in enumerate(ordered, start=1)
    }


def eligible_universe_by_day(
    qfq_series: dict[tuple[str, str], pd.DataFrame], target_dates: list[str]
) -> dict[str, set[tuple[str, str]]]:
    """Return the complete QFQ-eligible universe for each declared calendar day."""
    eligible: dict[str, set[tuple[str, str]]] = {}
    for trading_day in target_dates:
        day_universe: set[tuple[str, str]] = set()
        for key, frame in qfq_series.items():
            dates = _frame_dates(frame)
            try:
                index = dates.index(trading_day)
            except ValueError:
                continue
            if index < 250:
                continue
            closes = frame["close"].astype(float).tolist()
            if any(closes[index - window] == 0 for window in (20, 50, 120, 250)):
                continue
            day_universe.add(key)
        if len(day_universe) < MIN_ELIGIBLE_UNIVERSE:
            raise QfqCoverageError(
                f"QFQ eligible universe for {trading_day} has {len(day_universe)} symbols; "
                f"at least {MIN_ELIGIBLE_UNIVERSE} are required for cross-sectional RPS"
            )
        eligible[trading_day] = day_universe
    return eligible


def compute_rps_rows(
    qfq_series: dict[tuple[str, str], pd.DataFrame], ndays: int, reference_dates: list[str]
) -> list[dict[str, Any]]:
    """Compute the most-recent QFQ-only cross-sectional RPS rows."""
    target_dates = reference_dates[-max(1, ndays):]
    expected_by_day = eligible_universe_by_day(qfq_series, target_dates)
    rows: list[dict[str, Any]] = []
    for trading_day in target_dates:
        cross_section: list[dict[str, Any]] = []
        for market, symbol in sorted(expected_by_day[trading_day]):
            frame = qfq_series[(market, symbol)]
            dates = _frame_dates(frame)
            index = dates.index(trading_day)
            closes = frame["close"].astype(float).tolist()
            cross_section.append({
                "market": market,
                "symbol": symbol,
                "return_20_pct": (closes[index] - closes[index - 20]) / closes[index - 20] * 100.0,
                "return_50_pct": (closes[index] - closes[index - 50]) / closes[index - 50] * 100.0,
                "return_120_pct": (closes[index] - closes[index - 120]) / closes[index - 120] * 100.0,
                "return_250_pct": (closes[index] - closes[index - 250]) / closes[index - 250] * 100.0,
            })
        if not cross_section:
            continue
        rankings = {field: _rank_rps(cross_section, field) for field in ("return_20_pct", "return_50_pct", "return_120_pct", "return_250_pct")}
        for row in cross_section:
            key = (row["market"], row["symbol"])
            rows.append({
                "trading_day": trading_day,
                "market": row["market"],
                "symbol": row["symbol"],
                "price_basis": "tdx_export_qfq",
                "rps_20": rankings["return_20_pct"][key],
                "rps_50": rankings["return_50_pct"][key],
                "rps_120": rankings["return_120_pct"][key],
                "rps_250": rankings["return_250_pct"][key],
            })
    if not rows:
        raise RuntimeError("QFQ exports produced no RPS rows")
    return rows


def _atomic_write_json(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    with handle:
        json.dump(rows, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return Path(handle.name)


def _atomic_write_json_value(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    with handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return Path(handle.name)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    handle.close()
    temporary = Path(handle.name)
    frame.to_parquet(temporary, compression="snappy", index=False)
    return temporary


def refresh_from_computed_rows(
    computed_rows: list[dict[str, Any]],
    history_json: Path,
    history_parquet: Path,
    current_json: Path,
    expected_eligible_by_day: dict[str, set[tuple[str, str]]],
) -> dict[str, Any]:
    """Merge QFQ rows by date, then atomically replace history/current datasets."""
    if not computed_rows:
        raise ValueError("computed_rows must not be empty")
    computed = pd.DataFrame(computed_rows).reindex(columns=RPS_COLUMNS)
    computed_days = set(computed["trading_day"].astype(str))
    for trading_day in computed_days:
        expected = expected_eligible_by_day.get(trading_day)
        computed_universe = set(
            zip(
                computed.loc[computed["trading_day"].astype(str) == trading_day, "market"],
                computed.loc[computed["trading_day"].astype(str) == trading_day, "symbol"],
            )
        )
        if expected is None or computed_universe != expected:
            raise ValueError(
                f"Refusing replacement with incomplete eligible universe for {trading_day}: "
                f"computed {len(computed_universe)}, expected {len(expected or set())}"
            )
    final_dir = history_parquet.parent
    if history_json.parent != final_dir or current_json.parent != final_dir:
        raise ValueError("all RPS datasets must share one final directory")
    active_history_parquet = resolve_rps_dataset_path(final_dir, history_parquet.name)
    if active_history_parquet.exists():
        existing = pd.read_parquet(active_history_parquet).reindex(columns=RPS_COLUMNS)
        for trading_day in computed_days:
            existing_day = existing[existing["trading_day"].astype(str) == trading_day]
            existing_universe = set(zip(existing_day["market"].astype(str), existing_day["symbol"].astype(str)))
            computed_day = computed[computed["trading_day"].astype(str) == trading_day]
            computed_universe = set(zip(computed_day["market"].astype(str), computed_day["symbol"].astype(str)))
            missing_members = existing_universe - computed_universe
            if missing_members:
                labels = ", ".join(f"{market}:{symbol}" for market, symbol in sorted(missing_members))
                raise ValueError(
                    f"Refusing replacement that drops existing historical members for {trading_day}: {labels}"
                )
        existing = existing[~existing["trading_day"].astype(str).isin(computed_days)]
        merged = pd.concat([existing, computed], ignore_index=True)
    else:
        merged = computed
    merged = merged.sort_values(["trading_day", "market", "symbol"], kind="stable").drop_duplicates(
        ["trading_day", "market", "symbol"], keep="last"
    ).reset_index(drop=True)
    # Older datasets predate this field but are retained RPS values derived from
    # the same QFQ-only contract; make the persisted schemas explicit and equal.
    merged["price_basis"] = merged["price_basis"].fillna("tdx_export_qfq")
    merged = merged.where(pd.notna(merged), None)
    rows = merged.to_dict(orient="records")
    latest_day = max(computed_days)
    current_rows = [row for row in rows if row["trading_day"] == latest_day]

    generations_root = final_dir / "rps_generations"
    generations_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(dir=generations_root, prefix=".rps-generation-"))
    generation_name = uuid.uuid4().hex
    generation_dir = generations_root / generation_name
    manifest_path = final_dir / RPS_MANIFEST_FILENAME
    try:
        staged_paths = (
            (_atomic_write_parquet(staging_dir / history_parquet.name, merged), staging_dir / history_parquet.name),
            (_atomic_write_json(staging_dir / history_json.name, rows), staging_dir / history_json.name),
            (_atomic_write_json(staging_dir / current_json.name, current_rows), staging_dir / current_json.name),
        )
        for temporary, destination in staged_paths:
            os.replace(temporary, destination)
        os.replace(staging_dir, generation_dir)
        manifest = {
            "schema_version": 1,
            "generation": str(generation_dir.relative_to(final_dir)),
            "price_basis": "tdx_export_qfq",
        }
        temporary_manifest = _atomic_write_json_value(manifest_path, manifest)
        os.replace(temporary_manifest, manifest_path)
    except Exception:
        if staging_dir.exists():
            for path in staging_dir.iterdir():
                path.unlink(missing_ok=True)
            staging_dir.rmdir()
        raise
    return {
        "ok": True,
        "rows": len(rows),
        "computed_rows": len(computed_rows),
        "trading_days": int(merged["trading_day"].nunique()),
        "latest_trading_day": latest_day,
        "current_rows": len(current_rows),
        "price_basis": "tdx_export_qfq",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh RPS history/current from QFQ exports only")
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--qfq-export-dir", default=str(TDX_QFQ_EXPORT_DIR))
    parser.add_argument("--reference-symbol", default=DEFAULT_REFERENCE_SYMBOL)
    parser.add_argument("--ndays", type=int, default=120)
    parser.add_argument("--history-json", default=str(DEFAULT_FINAL_DIR / "dataset_stock_rps_history.json"))
    parser.add_argument("--history-parquet", default=str(DEFAULT_FINAL_DIR / "dataset_stock_rps_history.parquet"))
    parser.add_argument("--current-json", default=str(DEFAULT_FINAL_DIR / "dataset_stock_rps_current.json"))
    args = parser.parse_args()
    try:
        raw_latest = _latest_raw_trading_day(args.tdxdir, args.reference_symbol)
        qfq_series = load_qfq_series(Path(args.qfq_export_dir))
        reference_dates = reference_qfq_calendar(qfq_series, args.reference_symbol, raw_latest)
        target_dates = reference_dates[-max(1, args.ndays):]
        expected_eligible_by_day = eligible_universe_by_day(qfq_series, target_dates)
        computed_rows = compute_rps_rows(qfq_series, args.ndays, reference_dates)
        summary = refresh_from_computed_rows(
            computed_rows, Path(args.history_json), Path(args.history_parquet), Path(args.current_json), expected_eligible_by_day
        )
        summary.update({"raw_latest_trading_day": raw_latest, "qfq_latest_trading_day": reference_dates[-1]})
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "price_basis": "tdx_export_qfq"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
