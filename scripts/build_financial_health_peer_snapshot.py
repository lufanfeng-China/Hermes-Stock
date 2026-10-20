#!/usr/bin/env python3
"""Build and publish one anchor-consistent all-market financial-health peer snapshot.

Only the normalized financial warehouse is read.  A changed quarterly anchor is a
new comparison universe: it always causes a complete rebuild and publication, never
an in-place mixture of records calculated from different quarters.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.financial.health_peer_anchor import select_health_snapshot_periods
from app.financial.reports import _materialize_financial_report
from app.search import index as search_index
from app.stock_filter_snapshot import build_strict_financial_record

WAREHOUSE = ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
FINAL_DIR = ROOT / "data" / "derived" / "datasets" / "final"
CURRENT_FILENAME = "financial_health_peer_snapshot_current.json"
VERSIONED_PREFIX = "financial_health_peer_snapshot_"
CURRENT_SNAPSHOT_SCHEMA = "financial-health-peer-v2"
MANIFEST = ROOT / "data" / "derived" / "manifests" / "financial_changes_current.json"


class _Materializer:
    _derive_sub_fields = staticmethod(search_index._derive_sub_fields)
    _pick = staticmethod(search_index._pick)


def market_for(symbol: str) -> str:
    return "sh" if symbol.startswith("6") else "bj" if symbol.startswith(("4", "8", "9")) else "sz"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def select_warehouse_periods(warehouse_dir: Path = WAREHOUSE) -> dict[str, object]:
    """Select the single five-annual + year-ago-quarter + newest-quarter basis."""
    return select_health_snapshot_periods([path.stem for path in Path(warehouse_dir).glob("*.parquet") if path.stem != "latest"])


def _snapshot_paths(output_dir: Path, selection: dict[str, object]) -> tuple[Path, Path]:
    annual, quarter = str(selection["annual_anchor"]), str(selection["quarterly_anchor"])
    return output_dir / CURRENT_FILENAME, output_dir / f"{VERSIONED_PREFIX}{annual}__{quarter}.json"


def publish_snapshot(payload: dict[str, Any], output_dir: Path = FINAL_DIR) -> tuple[Path, Path]:
    """Publish immutable anchor version first, then atomically replace current."""
    selection = {"annual_anchor": payload["annual_anchor"], "quarterly_anchor": payload["quarterly_anchor"]}
    current, versioned = _snapshot_paths(Path(output_dir), selection)
    _atomic_write_json(versioned, payload)
    _atomic_write_json(current, payload)
    return current, versioned


def _read_selected_frames(periods: list[str], warehouse_dir: Path, symbols: set[str] | None = None) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for period in periods:
        path = Path(warehouse_dir) / f"{period}.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path)
        frame.index = frame.index.map(lambda value: str(value).zfill(6))
        frame = frame[~frame.index.duplicated(keep="last")]
        if symbols is not None:
            frame = frame.loc[frame.index.intersection(symbols)]
        frames[period] = frame
    return frames


def _report(period: str, row: pd.Series) -> dict[str, Any]:
    suffix_dates = {"Q1": "0331", "Q2": "0630", "Q3": "0930", "A": "1231"}
    announce = row.get("announce_date") or row.get("财报公告日期") or ""
    return _materialize_financial_report(_Materializer, {
        "report_date": str(row.get("report_date") or f"{period[:4]}{suffix_dates[period[4:]]}"),
        "announce_date": announce, "year": period[:4], "period": period, "row": row,
    })


def _industry_map() -> dict[tuple[str, str], tuple[str | None, str | None]]:
    # health scoring uses level 1; peer response separately uses level 2 membership.
    return {key: (values[0] or None, values[1] or None) for key, values in search_index._load_industry_map().items()}


def _unavailable_record(selection: dict[str, object]) -> dict[str, Any]:
    """Represent a member missing the uniform source basis without an old fallback."""
    return {
        "annual": {
            "anchor_period": selection["annual_anchor"], "periods": [], "assessment_track": None,
            "score": None, "coverage_weight": 0, "score_coverage_status": "unavailable",
            "dimensions": {}, "derived": {}, "reason": "uniform_snapshot_periods_unavailable",
        },
        "quarterly": {
            "anchor_period": selection["quarterly_anchor"], "period": None,
            "score": None, "coverage_weight": 0, "score_coverage_status": "unavailable",
            "dimensions": {}, "quality": {}, "triggered_red_flag_count": 0,
            "reason": "uniform_snapshot_periods_unavailable",
        },
        # This is deliberately separate from the strict quarterly comparison.
        # It is a per-stock reference record and must never rank peers.
        "latest_available_quarterly": {
            "period": None, "score": None, "coverage_weight": 0,
            "score_coverage_status": "unavailable", "dimensions": {},
            "reason": "latest_quarterly_report_unavailable",
        },
    }


def _latest_available_quarter_periods(selection: dict[str, object]) -> list[str]:
    """Current-year Q3/Q2/Q1 candidates and their same-quarter TTM bases."""
    anchor = str(selection["quarterly_anchor"])
    year = int(anchor[:4])
    suffixes = ("Q3", "Q2", "Q1")
    return [f"{y}{suffix}" for y in (year, year - 1) for suffix in suffixes]


def _latest_available_quarterly_records(selection: dict[str, object], *, warehouse_dir: Path, symbols: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Build separately labelled per-stock latest-quarter reference records."""
    annual_periods = [period for period in selection["periods"] if str(period).endswith("A")]
    candidate_periods = _latest_available_quarter_periods(selection)
    frames = _read_selected_frames(list(dict.fromkeys(annual_periods + candidate_periods)), warehouse_dir, symbols)
    industries = _industry_map()
    all_codes = set.union(*(set(frame.index) for frame in frames.values())) if frames else set()
    year = int(str(selection["quarterly_anchor"])[:4])
    result: dict[str, dict[str, Any]] = {}
    for symbol in sorted(all_codes):
        market = market_for(symbol)
        _industry_l2, industry_l1 = industries.get((market, symbol), (None, None))
        reference = {"period": None, "score": None, "coverage_weight": 0,
                     "score_coverage_status": "unavailable", "dimensions": {},
                     "reason": "latest_quarterly_report_unavailable"}
        for suffix in ("Q3", "Q2", "Q1"):
            latest_period, prior_period = f"{year}{suffix}", f"{year - 1}{suffix}"
            if symbol not in frames[latest_period].index:
                continue
            reports = [_report(period, frames[period].loc[symbol]) for period in annual_periods if symbol in frames[period].index]
            if symbol in frames[prior_period].index:
                reports.append(_report(prior_period, frames[prior_period].loc[symbol]))
            reports.append(_report(latest_period, frames[latest_period].loc[symbol]))
            record = build_strict_financial_record(reports, industry_level_1=industry_l1,
                                                   annual_anchor=str(selection["annual_anchor"]), quarterly_anchor=latest_period)
            reference = {**record["quarterly"], "reference_only": True}
            break
        result[f"{market}:{symbol}"] = reference
    return result


def _attach_latest_available_quarterly(records: dict[str, dict[str, Any]], selection: dict[str, object], *, warehouse_dir: Path, symbols: set[str] | None = None) -> dict[str, dict[str, Any]]:
    references = _latest_available_quarterly_records(selection, warehouse_dir=warehouse_dir, symbols=symbols)
    for key, record in records.items():
        record["latest_available_quarterly"] = references.get(key, _unavailable_record(selection)["latest_available_quarterly"])
    return records


def _records_from_frames(frames: dict[str, pd.DataFrame], selection: dict[str, object]) -> dict[str, dict[str, Any]]:
    periods = list(selection["periods"])
    all_codes = set.union(*(set(frame.index) for frame in frames.values())) if frames else set()
    complete_codes = set.intersection(*(set(frame.index) for frame in frames.values())) if frames else set()
    industries = _industry_map()
    records: dict[str, dict[str, Any]] = {}
    for symbol in sorted(all_codes):
        market = market_for(symbol)
        _industry_l2, industry_l1 = industries.get((market, symbol), (None, None))
        key = f"{market}:{symbol}"
        if symbol not in complete_codes:
            records[key] = _unavailable_record(selection)
            continue
        reports = [_report(period, frames[period].loc[symbol]) for period in periods]
        records[key] = build_strict_financial_record(
            reports, industry_level_1=industry_l1,
            annual_anchor=str(selection["annual_anchor"]), quarterly_anchor=str(selection["quarterly_anchor"]),
        )
    return records


def build_full_snapshot(selection: dict[str, object], *, warehouse_dir: Path = WAREHOUSE) -> dict[str, Any]:
    periods = list(selection["periods"])
    frames = _read_selected_frames(periods, warehouse_dir)
    return {
        "schema_version": CURRENT_SNAPSHOT_SCHEMA,
        "annual_anchor": selection["annual_anchor"],
        "quarterly_anchor": selection["quarterly_anchor"],
        "periods_loaded": periods,
        "stocks": _attach_latest_available_quarterly(_records_from_frames(frames, selection), selection, warehouse_dir=warehouse_dir),
    }


def refresh_symbol_records(symbols: list[str], selection: dict[str, object], *, warehouse_dir: Path = WAREHOUSE) -> dict[str, dict[str, Any]]:
    normalized = {str(symbol).split(":")[-1].zfill(6) for symbol in symbols}
    frames = _read_selected_frames(list(selection["periods"]), warehouse_dir, normalized)
    return _attach_latest_available_quarterly(_records_from_frames(frames, selection), selection, warehouse_dir=warehouse_dir, symbols=normalized)


def _anchors_match(payload: dict[str, Any], selection: dict[str, object]) -> bool:
    periods = selection.get("periods")
    expected_periods = list(periods) if isinstance(periods, list) else []
    return (payload.get("schema_version"), payload.get("annual_anchor"), payload.get("quarterly_anchor"), payload.get("periods_loaded")) == (
        CURRENT_SNAPSHOT_SCHEMA, selection["annual_anchor"], selection["quarterly_anchor"], expected_periods,
    )


def refresh_snapshot(current_path: Path, symbols: list[str], *, warehouse_dir: Path = WAREHOUSE) -> dict[str, Any]:
    """Incrementally replace changed records only when the published basis matches."""
    selection = select_warehouse_periods(warehouse_dir)
    current_path = Path(current_path)
    existing = json.loads(current_path.read_text(encoding="utf-8")) if current_path.is_file() else None
    if not isinstance(existing, dict) or not _anchors_match(existing, selection):
        payload = build_full_snapshot(selection, warehouse_dir=warehouse_dir)
        publish_snapshot(payload, current_path.parent)
        return {"mode": "full_rebuild", "updated": len(payload["stocks"]), "selection": selection}

    changed = refresh_symbol_records(symbols, selection, warehouse_dir=warehouse_dir)
    # A changed symbol no longer present in every uniform period cannot retain an
    # old incomparable record.  Remove it rather than silently falling back.
    stock_records = dict(existing.get("stocks") or {})
    requested_keys = {f"{market_for(str(symbol).split(':')[-1].zfill(6))}:{str(symbol).split(':')[-1].zfill(6)}" for symbol in symbols}
    for key in requested_keys:
        stock_records.pop(key, None)
    stock_records.update(changed)
    payload = {**existing, "stocks": stock_records, "incremental_updated_symbols": sorted({str(item).split(":")[-1].zfill(6) for item in symbols})}
    publish_snapshot(payload, current_path.parent)
    return {"mode": "incremental", "updated": len(changed), "selection": selection}


def _changed_symbols(manifest: Path) -> list[str]:
    if not manifest.is_file():
        return []
    return list((json.loads(manifest.read_text(encoding="utf-8")) or {}).get("changed_symbols") or [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--warehouse-dir", type=Path, default=WAREHOUSE)
    parser.add_argument("--output-dir", type=Path, default=FINAL_DIR)
    parser.add_argument("--snapshot", type=Path, help="Deprecated alias for the current snapshot path")
    parser.add_argument("--symbols", nargs="*")
    args = parser.parse_args()
    current = args.snapshot or (args.output_dir / CURRENT_FILENAME)
    symbols = args.symbols if args.symbols is not None else _changed_symbols(args.manifest)
    result = refresh_snapshot(current, symbols, warehouse_dir=args.warehouse_dir)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
