"""Validation helpers for archive pipeline outputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_DATASETS = {
    "bars_15m",
    "features_intraday_volume_windows",
    "dataset_stock_candidate_pool",
    "dataset_stock_industry_current",
    "dataset_stock_rps_current",
    "dataset_concept_dictionary",
    "dataset_stock_concept_current",
    "snapshot_market_overview",
    "snapshot_stock_industry_membership",
    "snapshot_stock_rps_current",
    "snapshot_stock_concept_membership",
}


def validate_trading_day(trading_day: str) -> None:
    datetime.strptime(trading_day, "%Y-%m-%d")


def _validation_item(name: str, status: str, details: str | None = None) -> dict[str, Any]:
    item = {"name": name, "status": status}
    if details:
        item["details"] = details
    return item


def run_archive_validations(
    *,
    ctx: Any,
    final_inputs: dict[str, Any],
    datasets_included: list[dict[str, Any]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    data_status = final_inputs["source_summary"]["data_status"]
    items.append(_validation_item("final_data_status_check", "passed" if data_status == "final" else "failed"))

    names = {item["dataset_name"] for item in datasets_included}
    missing = sorted(REQUIRED_DATASETS - names)
    items.append(
        _validation_item(
            "dataset_presence_check",
            "passed" if not missing else "failed",
            None if not missing else f"missing datasets: {', '.join(missing)}",
        )
    )

    versions = final_inputs.get("versions", {})
    version_ok = all(versions.get(key) for key in ("schema_version", "rule_version", "data_pipeline_version"))
    items.append(_validation_item("version_presence_check", "passed" if version_ok else "failed"))

    partition = f"trading_day={ctx.trading_day}"
    partition_ok = all(item["partition"] == partition for item in datasets_included)
    items.append(_validation_item("archive_partition_check", "passed" if partition_ok else "failed"))

    row_count_ok = all(item["row_count"] >= 0 for item in datasets_included)
    items.append(_validation_item("row_count_sanity_check", "passed" if row_count_ok else "failed"))

    timestamp_ok = all(item["data_cutoff_time"] == ctx.data_cutoff_time for item in datasets_included)
    items.append(_validation_item("timestamp_consistency_check", "passed" if timestamp_ok else "failed"))

    paths_ok = True
    for item in datasets_included:
        artifact_path = ctx.project_root / item["path"]
        if not artifact_path.exists():
            paths_ok = False
            warnings.append(f"artifact missing on disk: {item['path']}")
    items.append(_validation_item("artifact_existence_check", "passed" if paths_ok else "failed"))

    snapshot_present = any(item["dataset_category"] == "snapshot" for item in datasets_included)
    items.append(_validation_item("snapshot_presence_check", "passed" if snapshot_present else "failed"))

    audit_present = (ctx.archive_root / "audit" / "freeze_intraday_state.json").exists()
    items.append(_validation_item("audit_log_presence_check", "passed" if audit_present else "failed"))

    checks_failed = sum(item["status"] == "failed" for item in items)
    return {
        "overall_status": "passed" if checks_failed == 0 else "failed",
        "checks_total": len(items),
        "checks_passed": len(items) - checks_failed,
        "checks_failed": checks_failed,
        "warnings": len(warnings),
        "validation_items": items,
        "warning_messages": warnings,
    }
