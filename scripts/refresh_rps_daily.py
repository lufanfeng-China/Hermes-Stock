#!/usr/bin/env python3
"""Refresh the sole authoritative RPS Parquet dataset from Tongdaxin QFQ exports.

Raw TDX daily bars are a freshness gate only. RPS is never calculated from raw
prices, and a failed QFQ validation never replaces the authoritative dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import TDX_QFQ_EXPORT_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

DEFAULT_TDX_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_REFERENCE_SYMBOL = "601600"
DEFAULT_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
RPS_DATASET_FILENAME = "dataset_stock_rps_history.parquet"
RPS_COLUMNS = ["trading_day", "market", "symbol", "price_basis", "rps_20", "rps_50", "rps_120", "rps_250"]
MIN_ELIGIBLE_UNIVERSE = 2
LEGACY_RPS_FILENAMES = (
    "dataset_stock_rps_history.json",
    "dataset_stock_rps_current.json",
    "dataset_stock_rps_current.parquet",
    "dataset_stock_rps_manifest.json",
)


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
    reference_symbol = reference_symbol.zfill(6)
    matches = [(key, frame) for key, frame in qfq_series.items() if key[1] == reference_symbol]
    if len(matches) != 1:
        raise QfqCoverageError(f"Expected exactly one QFQ reference calendar for {reference_symbol}, found {len(matches)}")
    dates = _frame_dates(matches[0][1])
    if not dates:
        raise QfqCoverageError(f"QFQ reference calendar for {reference_symbol} is empty")
    try:
        require_qfq_covers_raw(raw_latest_day, dates[-1])
    except QfqCoverageError as exc:
        raise QfqCoverageError(f"Declared reference QFQ calendar for {reference_symbol} is stale: {exc}") from exc
    return dates


def publishable_reference_dates(reference_dates: list[str], raw_latest_day: str) -> list[str]:
    """Cap QFQ-derived signals at the latest raw day eligible for publication."""
    dates = [day for day in reference_dates if day <= raw_latest_day]
    if not dates:
        raise QfqCoverageError(f"No QFQ reference dates are publishable through raw latest trading day {raw_latest_day}")
    return dates


def _market_for_export(path: Path) -> str:
    prefix = path.name.split("#", 1)[0].lower()
    return {"sh": "sh", "sz": "sz", "bj": "bj"}.get(prefix, prefix)


def _symbol_for_export(path: Path) -> str:
    try:
        return path.stem.split("#", 1)[1].zfill(6)
    except IndexError as exc:
        raise ValueError(f"Unexpected QFQ export filename: {path.name}") from exc


def _latest_raw_trading_day(tdxdir: str, symbol: str) -> str:
    from mootdx.reader import Reader

    daily = Reader.factory(market="std", tdxdir=tdxdir).daily(symbol=symbol)
    if daily is None or daily.empty:
        raise RuntimeError(f"No raw TDX daily bars available for reference symbol {symbol}")
    return pd.Timestamp(daily.index.max()).date().isoformat()


def load_qfq_series(
    export_dir: Path, *, reference_symbol: str | None = None, tail_rows: int | None = None
) -> dict[tuple[str, str], pd.DataFrame]:
    """Load QFQ exports, retaining only the calculation window for non-reference symbols."""
    series: dict[tuple[str, str], pd.DataFrame] = {}
    reference_symbol = reference_symbol.zfill(6) if reference_symbol else None
    for path in sorted(Path(export_dir).glob("*#*.txt")):
        try:
            market = _market_for_export(path)
            symbol = _symbol_for_export(path)
            daily = load_tdx_qfq_daily(symbol, export_dir=export_dir)
        except (FileNotFoundError, ValueError):
            continue
        if len(daily) >= 251:
            if tail_rows is not None and symbol != reference_symbol:
                daily = daily.tail(tail_rows)
            series[(market, symbol)] = daily.sort_index()
    if not series:
        raise RuntimeError(f"No QFQ exports with at least 251 daily bars found in {export_dir}")
    return series


def _rank_rps(rows: list[dict[str, Any]], field: str) -> dict[tuple[str, str], float]:
    ordered = sorted(rows, key=lambda row: float(row[field]), reverse=True)
    return {(row["market"], row["symbol"]): round((len(ordered) - rank + 1) / len(ordered) * 100, 2)
            for rank, row in enumerate(ordered, start=1)}


def eligible_universe_and_positions_by_day(
    qfq_series: dict[tuple[str, str], pd.DataFrame], target_dates: list[str]
) -> tuple[dict[str, set[tuple[str, str]]], dict[tuple[str, str], dict[str, int]]]:
    """Index each QFQ frame once; avoid repeated list conversions/searches per day."""
    eligible = {day: set() for day in target_dates}
    positions: dict[tuple[str, str], dict[str, int]] = {}
    target_index = pd.to_datetime(target_dates)
    for key, frame in qfq_series.items():
        indexes = frame.index.get_indexer(target_index)
        closes = frame["close"].to_numpy(dtype=float, copy=False)
        key_positions: dict[str, int] = {}
        for trading_day, index in zip(target_dates, indexes):
            if index >= 250 and all(closes[index - window] != 0 for window in (20, 50, 120, 250)):
                eligible[trading_day].add(key)
                key_positions[trading_day] = int(index)
        if key_positions:
            positions[key] = key_positions
    for trading_day, day_universe in eligible.items():
        if len(day_universe) < MIN_ELIGIBLE_UNIVERSE:
            raise QfqCoverageError(f"QFQ eligible universe for {trading_day} has {len(day_universe)} symbols; at least {MIN_ELIGIBLE_UNIVERSE} are required for cross-sectional RPS")
    return eligible, positions


def eligible_universe_by_day(qfq_series: dict[tuple[str, str], pd.DataFrame], target_dates: list[str]) -> dict[str, set[tuple[str, str]]]:
    return eligible_universe_and_positions_by_day(qfq_series, target_dates)[0]


def compute_rps_rows(
    qfq_series: dict[tuple[str, str], pd.DataFrame], ndays: int, reference_dates: list[str],
    expected_by_day: dict[str, set[tuple[str, str]]] | None = None,
    positions_by_key: dict[tuple[str, str], dict[str, int]] | None = None,
    target_dates: list[str] | None = None,
) -> list[dict[str, Any]]:
    target_dates = target_dates or reference_dates[-max(1, ndays):]
    if expected_by_day is None or positions_by_key is None:
        expected_by_day, positions_by_key = eligible_universe_and_positions_by_day(qfq_series, target_dates)
    rows: list[dict[str, Any]] = []
    for trading_day in target_dates:
        cross_section: list[dict[str, Any]] = []
        for market, symbol in sorted(expected_by_day[trading_day]):
            frame = qfq_series[(market, symbol)]
            index = positions_by_key[(market, symbol)][trading_day]
            closes = frame["close"].to_numpy(dtype=float, copy=False)
            cross_section.append({"market": market, "symbol": symbol,
                "return_20_pct": (closes[index] - closes[index - 20]) / closes[index - 20] * 100,
                "return_50_pct": (closes[index] - closes[index - 50]) / closes[index - 50] * 100,
                "return_120_pct": (closes[index] - closes[index - 120]) / closes[index - 120] * 100,
                "return_250_pct": (closes[index] - closes[index - 250]) / closes[index - 250] * 100})
        rankings = {field: _rank_rps(cross_section, field) for field in ("return_20_pct", "return_50_pct", "return_120_pct", "return_250_pct")}
        for row in cross_section:
            key = (row["market"], row["symbol"])
            rows.append({"trading_day": trading_day, "market": row["market"], "symbol": row["symbol"], "price_basis": "tdx_export_qfq",
                "rps_20": rankings["return_20_pct"][key], "rps_50": rankings["return_50_pct"][key],
                "rps_120": rankings["return_120_pct"][key], "rps_250": rankings["return_250_pct"][key]})
    if not rows:
        raise RuntimeError("QFQ exports produced no RPS rows")
    return rows


def _atomic_replace_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_parquet(temporary, compression="snappy", index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.reindex(columns=RPS_COLUMNS).copy()
    if not frame.empty:
        frame["trading_day"] = frame["trading_day"].astype(str)
        frame["market"] = frame["market"].astype(str)
        frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
        frame["price_basis"] = frame["price_basis"].fillna("tdx_export_qfq")
    return frame


def _remove_legacy_publications(final_dir: Path) -> None:
    for name in LEGACY_RPS_FILENAMES:
        (final_dir / name).unlink(missing_ok=True)
    shutil.rmtree(final_dir / "rps_generations", ignore_errors=True)


def _load_legacy_json(path: Path) -> pd.DataFrame:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Legacy RPS JSON must be a list of rows: {path}")
    return _normalise(pd.DataFrame(rows))


def _active_generation_dir(final_dir: Path) -> Path | None:
    manifest_path = final_dir / "dataset_stock_rps_manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generation = manifest.get("generation") if isinstance(manifest, dict) else None
    if not isinstance(generation, str) or not generation:
        raise ValueError(f"RPS manifest has no valid generation: {manifest_path}")
    final_root = final_dir.resolve()
    generation_dir = (final_dir / generation).resolve()
    if not generation_dir.is_relative_to(final_root):
        raise ValueError(f"RPS manifest generation escapes final dataset directory: {generation}")
    if not generation_dir.is_dir():
        raise FileNotFoundError(f"RPS manifest active generation is missing: {generation_dir}")
    return generation_dir


def migrate_legacy_history_if_newer(history_parquet: Path, legacy_history_json: Path | None = None) -> dict[str, Any]:
    """Atomically consolidate legacy publications into the sole RPS Parquet file.

    An old manifest makes its active generation authoritative.  Its history is
    included even if the top-level legacy JSON has already disappeared, so an
    interrupted prior migration cannot silently truncate older trading days.
    """
    final_dir = history_parquet.parent
    legacy_history_json = legacy_history_json or history_parquet.with_suffix(".json")
    active_generation = _active_generation_dir(final_dir)
    legacy_current_json = final_dir / "dataset_stock_rps_current.json"
    sources: list[pd.DataFrame] = []

    # Earlier sources are superseded only for the same (day, market, symbol).
    # Generation sources are last because the manifest declares them active.
    for path in (legacy_history_json, legacy_current_json):
        if path.exists():
            sources.append(_load_legacy_json(path))
    existing = _normalise(pd.read_parquet(history_parquet)) if history_parquet.exists() else pd.DataFrame(columns=RPS_COLUMNS)
    if not existing.empty:
        sources.append(existing)
    if active_generation is not None:
        generation_json = active_generation / legacy_history_json.name
        generation_parquet = active_generation / history_parquet.name
        if generation_json.exists():
            sources.append(_load_legacy_json(generation_json))
        if generation_parquet.exists():
            sources.append(_normalise(pd.read_parquet(generation_parquet)))
        if not generation_json.exists() and not generation_parquet.exists():
            raise FileNotFoundError(f"RPS active generation has no history dataset: {active_generation}")

    has_legacy_publication = active_generation is not None or legacy_history_json.exists() or legacy_current_json.exists()
    if not has_legacy_publication:
        return {"migrated": False, "reason": "no legacy RPS publication is present"}

    existing_rows = len(existing)
    merged = pd.concat(sources, ignore_index=True)
    merged = merged.sort_values(["trading_day", "market", "symbol"], kind="stable")
    merged = merged.drop_duplicates(["trading_day", "market", "symbol"], keep="last").reset_index(drop=True)
    # Publication is deliberately before cleanup: an exception leaves the
    # manifest/generation available for a retry.
    _atomic_replace_parquet(history_parquet, merged)
    _remove_legacy_publications(final_dir)
    return {
        "migrated": True,
        "rows_added": max(0, len(merged) - existing_rows),
        "latest_trading_day": merged["trading_day"].max() if not merged.empty else "",
    }


def refresh_from_computed_rows(computed_rows: list[dict[str, Any]], history_parquet: Path, expected_eligible_by_day: dict[str, set[tuple[str, str]]]) -> dict[str, Any]:
    """Validate a complete QFQ update then atomically replace only Parquet."""
    if not computed_rows:
        raise ValueError("computed_rows must not be empty")
    computed = _normalise(pd.DataFrame(computed_rows))
    computed_days = set(computed["trading_day"])
    for trading_day in computed_days:
        expected = expected_eligible_by_day.get(trading_day)
        universe = set(zip(computed.loc[computed["trading_day"] == trading_day, "market"], computed.loc[computed["trading_day"] == trading_day, "symbol"]))
        if expected is None or universe != expected:
            raise ValueError(f"Refusing replacement with incomplete eligible universe for {trading_day}: computed {len(universe)}, expected {len(expected or set())}")
    existing = _normalise(pd.read_parquet(history_parquet)) if history_parquet.exists() else pd.DataFrame(columns=RPS_COLUMNS)
    for trading_day in computed_days:
        old = existing[existing["trading_day"] == trading_day]
        missing = set(zip(old["market"], old["symbol"])) - set(zip(computed.loc[computed["trading_day"] == trading_day, "market"], computed.loc[computed["trading_day"] == trading_day, "symbol"]))
        if missing:
            labels = ", ".join(f"{market}:{symbol}" for market, symbol in sorted(missing))
            raise ValueError(f"Refusing replacement that drops existing historical members for {trading_day}: {labels}")
    merged = pd.concat([existing[~existing["trading_day"].isin(computed_days)], computed], ignore_index=True)
    merged = merged.sort_values(["trading_day", "market", "symbol"], kind="stable").drop_duplicates(["trading_day", "market", "symbol"], keep="last").reset_index(drop=True)
    _atomic_replace_parquet(history_parquet, merged)
    return {"ok": True, "rows": len(merged), "computed_rows": len(computed), "trading_days": int(merged["trading_day"].nunique()), "latest_trading_day": max(computed_days), "price_basis": "tdx_export_qfq"}


def _incremental_target_dates(reference_dates: list[str], published_rps_days: set[str], recovery_window: int = 500) -> list[str]:
    """Repair the most-recent continuous RPS gap without reopening old history.

    Older historical gaps are not silently rewritten by a daily task.  Within
    the bounded recent reference-calendar window, a newer stray row cannot mask
    the first missing day: recomputation starts at its prior complete boundary.
    """
    if not published_rps_days:
        raise ValueError("No published RPS history; run an explicit audited bootstrap with --ndays")
    recent_dates = reference_dates[-recovery_window:]
    missing_index = next((index for index, day in enumerate(recent_dates) if day not in published_rps_days), None)
    if missing_index is None:
        return [recent_dates[-1]]
    return recent_dates[max(0, missing_index - 1):]


def _published_rps_days(history_parquet: Path) -> set[str]:
    if not history_parquet.exists():
        return set()
    return set(pd.read_parquet(history_parquet, columns=["trading_day"])["trading_day"].dropna().astype(str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh authoritative RPS Parquet from QFQ exports only")
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--qfq-export-dir", default=str(TDX_QFQ_EXPORT_DIR))
    parser.add_argument("--reference-symbol", default=DEFAULT_REFERENCE_SYMBOL)
    parser.add_argument("--ndays", type=int, default=None, help="explicit bootstrap/rebuild window; omit for incremental refresh from last published RPS day")
    parser.add_argument("--history-parquet", default=str(DEFAULT_FINAL_DIR / RPS_DATASET_FILENAME))
    parser.add_argument("--migrate-legacy", action="store_true", help="run legacy consolidation only and exit (normally automatic)")
    args = parser.parse_args()
    history_parquet = Path(args.history_parquet)
    try:
        migration = migrate_legacy_history_if_newer(history_parquet)
        if args.migrate_legacy:
            print(json.dumps(migration, ensure_ascii=False))
            return 0
        raw_latest = _latest_raw_trading_day(args.tdxdir, args.reference_symbol)
        published_rps_days = _published_rps_days(history_parquet)
        requested_days = args.ndays
        if requested_days is None:
            if not published_rps_days:
                raise ValueError("No published RPS history; run an explicit audited bootstrap with --ndays")
            # Retain a bounded catch-up window plus 250-bar lookback; the exact
            # contiguous repair range is selected from the QFQ reference calendar.
            requested_days = 500
        qfq_series = load_qfq_series(
            Path(args.qfq_export_dir), reference_symbol=args.reference_symbol,
            tail_rows=max(251, 250 + requested_days),
        )
        source_reference_dates = reference_qfq_calendar(qfq_series, args.reference_symbol, raw_latest)
        reference_dates = publishable_reference_dates(source_reference_dates, raw_latest)
        target_dates = (
            reference_dates[-max(1, args.ndays):]
            if args.ndays is not None
            else _incremental_target_dates(reference_dates, published_rps_days)
        )
        eligible_by_day, positions_by_key = eligible_universe_and_positions_by_day(qfq_series, target_dates)
        computed_rows = compute_rps_rows(qfq_series, len(target_dates), reference_dates, eligible_by_day, positions_by_key, target_dates)
        summary = refresh_from_computed_rows(computed_rows, history_parquet, eligible_by_day)
        summary["incremental_from_trading_day"] = target_dates[0]
        summary.update({"raw_latest_trading_day": raw_latest, "qfq_latest_trading_day": source_reference_dates[-1], "published_through_trading_day": reference_dates[-1], "legacy_migration": migration})
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "price_basis": "tdx_export_qfq"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
