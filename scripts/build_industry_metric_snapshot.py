#!/usr/bin/env python3
"""Publish an independent, versioned secondary-industry peer-metric snapshot.

The builder reads the already-published strict financial-health snapshot.  It
never loads raw financial reports: that keeps its output independently
publishable and preserves a clear source-version trail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search import index as search_index

FINAL_DIR = ROOT / "data" / "derived" / "datasets" / "final"
CURRENT_FILENAME = "dataset_industry_metric_peers_current.json"
VERSIONED_PREFIX = "dataset_industry_metric_peers_"
SCHEMA_VERSION = "industry-metric-peers-v2"


def _normalized_market(value: object) -> str:
    market = str(value or "").strip().lower()
    return "bj" if market == "2" else market


def _metric_coverage(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    coverage: dict[str, dict[str, int]] = {}
    for row in rows:
        for metric, cells in (row.get("peer_metrics") or {}).items():
            if not isinstance(cells, dict):
                continue
            counts = coverage.setdefault(str(metric), {"annual": 0, "quarter": 0, "ttm": 0})
            for basis in counts:
                cell = cells.get(basis)
                if isinstance(cell, dict) and cell.get("value") is not None:
                    counts[basis] += 1
    return dict(sorted(coverage.items()))


def _industry_source_version(industry_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return stable provenance fields when the membership dataset supplies them."""
    version: dict[str, Any] = {"source": "app.search.index.load_industry_rows"}
    for field in ("dataset_name", "parser_version", "generated_at", "data_cutoff_time"):
        values = sorted({str(row.get(field)).strip() for row in industry_rows if str(row.get(field) or "").strip()})
        if len(values) == 1:
            version[field] = values[0]
        elif values:
            version[field] = values
    return version


def build_snapshot(
    strict_snapshot: dict[str, Any],
    industry_rows: list[dict[str, Any]],
    *,
    name_lookup: dict[tuple[str, str], str],
    source_path: str | Path,
    built_at: str,
) -> dict[str, Any]:
    """Materialize every classified member into its secondary-industry partition."""
    stocks = strict_snapshot.get("stocks") or {}
    industries: dict[str, dict[str, Any]] = {}
    for industry_row in industry_rows:
        if not isinstance(industry_row, dict):
            continue
        industry_l2 = str(industry_row.get("industry_level_2_name") or "").strip()
        if not industry_l2:
            continue
        market = _normalized_market(industry_row.get("market"))
        symbol = str(industry_row.get("symbol") or "").strip().zfill(6)
        if market not in {"sh", "sz", "bj"} or not (symbol.isdigit() and len(symbol) == 6):
            continue
        industry_l1 = str(industry_row.get("industry_level_1_name") or "").strip() or None
        partition = industries.setdefault(industry_l2, {
            "industry_level_1": industry_l1,
            "industry_level_2": industry_l2,
            "rows": [],
        })
        record = stocks.get(f"{market}:{symbol}")
        peer_metrics = record.get("peer_metrics") if isinstance(record, dict) else None
        member = {
            "market": market,
            "symbol": symbol,
            "stock_name": str(name_lookup.get((market, symbol)) or industry_row.get("stock_name") or symbol),
            "peer_metrics": peer_metrics if isinstance(peer_metrics, dict) else {},
            "available": bool(peer_metrics),
            "_has_snapshot_record": isinstance(record, dict),
        }
        if not isinstance(record, dict):
            member["unavailable_reason"] = "strict_financial_health_snapshot_record_missing"
        elif not peer_metrics:
            member["unavailable_reason"] = "peer_metrics_unavailable"
        partition["rows"].append(member)

    for partition in industries.values():
        rows = partition["rows"]
        rows.sort(key=lambda row: (row["market"], row["symbol"]))
        partition["coverage"] = {
            "members": len(rows),
            "snapshot_records": sum(row.pop("_has_snapshot_record") for row in rows),
            "metrics": _metric_coverage(rows),
        }

    source = Path(source_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "built_at": built_at,
        "annual_anchor": strict_snapshot.get("annual_anchor"),
        "quarter_anchor": strict_snapshot.get("quarterly_anchor"),
        "source_versions": {
            "strict_financial_health_snapshot": {
                "path": source.name,
                "schema_version": strict_snapshot.get("schema_version"),
            },
            "industry_membership": _industry_source_version(industry_rows),
        },
        "industries": dict(sorted(industries.items())),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _partition_filename(industry_level_2: str) -> str:
    """Use a stable filesystem-safe name while preserving the industry in JSON."""
    return f"{hashlib.sha256(industry_level_2.encode('utf-8')).hexdigest()[:20]}.json"


def _manifest(payload: dict[str, Any], versioned_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split the build payload into a tiny routing manifest and industry files."""
    industries = payload.get("industries")
    if not isinstance(industries, dict):
        raise ValueError("industry metric snapshot must contain industries")
    partition_dir_name = f"{versioned_path.stem}.partitions"
    partitions: dict[str, str] = {}
    stock_to_industry: dict[str, str] = {}
    partition_payloads: dict[str, dict[str, Any]] = {}
    for industry_level_2, partition in sorted(industries.items()):
        if not isinstance(partition, dict):
            continue
        industry_name = str(industry_level_2)
        filename = _partition_filename(industry_name)
        partitions[industry_name] = f"{partition_dir_name}/{filename}"
        partition_payloads[filename] = partition
        for row in partition.get("rows") or []:
            if not isinstance(row, dict):
                continue
            market = _normalized_market(row.get("market"))
            symbol = str(row.get("symbol") or "").strip().zfill(6)
            if market in {"sh", "sz", "bj"} and symbol.isdigit() and len(symbol) == 6:
                stock_to_industry[f"{market}:{symbol}"] = industry_name
    manifest = {key: value for key, value in payload.items() if key != "industries"}
    manifest.update({
        "schema_version": SCHEMA_VERSION,
        "stock_to_industry": dict(sorted(stock_to_industry.items())),
        "partitions": partitions,
    })
    return manifest, partition_payloads


def publish_snapshot(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Atomically publish the immutable daily version before replacing current."""
    try:
        date = datetime.fromisoformat(str(payload["built_at"]).replace("Z", "+00:00")).date().isoformat()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("built_at must be an ISO-8601 timestamp") from exc
    versioned_path = output_dir / f"{VERSIONED_PREFIX}{date}.json"
    current_path = output_dir / CURRENT_FILENAME
    manifest, partition_payloads = _manifest(payload, versioned_path)
    partition_dir = output_dir / f"{versioned_path.stem}.partitions"
    for filename, partition in partition_payloads.items():
        _atomic_write_json(partition_dir / filename, partition)
    # Publish every referenced immutable partition before either manifest can
    # expose it.  The current manifest is the final atomic pointer swap.
    _atomic_write_json(versioned_path, manifest)
    _atomic_write_json(current_path, manifest)
    return current_path, versioned_path


def discover_strict_snapshot(final_dir: Path = FINAL_DIR) -> Path:
    """Choose the newest published strict snapshot without embedding its anchors."""
    candidates = list(final_dir.glob("strict_financial_health_snapshot_*.json"))
    if not candidates:
        raise FileNotFoundError(f"no published strict financial-health snapshot in {final_dir}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"strict snapshot must be a JSON object: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="published strict financial-health snapshot; defaults to newest")
    parser.add_argument("--output-dir", type=Path, default=FINAL_DIR)
    args = parser.parse_args()

    source_path = args.source or discover_strict_snapshot(FINAL_DIR)
    source = _load_json(source_path)
    industry_rows = search_index.load_industry_rows()
    payload = build_snapshot(
        source,
        industry_rows,
        name_lookup=search_index._stock_name_lookup(),
        source_path=source_path,
        built_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    current_path, versioned_path = publish_snapshot(payload, args.output_dir)
    print(json.dumps({
        "current": str(current_path), "versioned": str(versioned_path),
        "industries": len(payload["industries"]), "annual_anchor": payload["annual_anchor"],
        "quarter_anchor": payload["quarter_anchor"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
