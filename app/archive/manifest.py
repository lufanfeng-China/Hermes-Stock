"""Manifest builders for the archive pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_day_manifest(
    *,
    ctx: Any,
    final_inputs: dict[str, Any],
    freeze_state: dict[str, Any],
    datasets_included: list[dict[str, Any]],
    validation_summary: dict[str, Any],
    completed_at: str,
) -> dict[str, Any]:
    del freeze_state
    rerun_of = ctx.archive_revision - 1 if ctx.archive_revision > 1 else None
    return {
        "trading_day": ctx.trading_day,
        "run_id": ctx.run_id,
        "archive_revision": ctx.archive_revision,
        "archive_status": "success",
        "started_at": ctx.started_at,
        "completed_at": completed_at,
        "generated_at": completed_at,
        "data_cutoff_time": ctx.data_cutoff_time,
        "source_summary": final_inputs["source_summary"],
        "versions": final_inputs["versions"],
        "datasets_included": datasets_included,
        "snapshot_summary": {
            "market_snapshot": "available",
            "sector_snapshot": "not_enabled",
            "stock_snapshot": "not_enabled",
            "portfolio_snapshot": "not_enabled",
        },
        "validation_summary": validation_summary,
        "exception_summary": final_inputs["exception_summary"],
        "rerun_info": {
            "is_rerun": ctx.archive_revision > 1,
            "rerun_of": rerun_of,
            "rerun_reason": ctx.rerun_reason,
            "supersedes_revision": rerun_of,
        },
        "artifacts": {
            "success_marker": ctx.relpath(ctx.success_marker_path),
            "failure_marker": None,
            "manifest_path": ctx.relpath(ctx.manifest_path),
            "audit_root": ctx.relpath(ctx.archive_root / "audit"),
            "bars_root": ctx.relpath(ctx.archive_root / "bars"),
            "features_root": ctx.relpath(ctx.archive_root / "features"),
            "datasets_root": ctx.relpath(ctx.archive_root / "datasets"),
            "snapshots_root": ctx.relpath(ctx.archive_root / "snapshots"),
        },
        "notes": [
            *final_inputs.get("notes", []),
            "Dry run mode still writes placeholder archive artifacts." if ctx.dry_run else "Archive completed with placeholder artifact files.",
        ],
    }


def write_day_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
