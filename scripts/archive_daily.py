#!/usr/bin/env python3
"""Minimal stdlib-only daily archive pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.archive.jobs import (  # noqa: E402
    build_audit_artifacts,
    build_final_bars,
    build_final_datasets,
    build_final_features,
    build_final_snapshots,
    freeze_intraday_state,
    load_final_inputs,
)
from app.archive.manifest import build_day_manifest, write_day_manifest  # noqa: E402
from app.archive.markers import write_failed_marker, write_success_marker  # noqa: E402
from app.archive.validators import validate_trading_day, run_archive_validations  # noqa: E402


@dataclass
class ArchiveContext:
    trading_day: str
    force_rerun: bool
    rerun_reason: str | None
    dry_run: bool
    project_root: Path
    archive_root: Path
    manifests_dir: Path
    lock_path: Path
    manifest_path: Path
    success_marker_path: Path
    failed_marker_path: Path
    archive_revision: int
    run_id: str
    started_at: str
    generated_at: str
    data_cutoff_time: str
    current_stage: str = "phase_0_prepare"
    stage_history: list[str] = field(default_factory=list)

    def relpath(self, path: Path) -> str:
        return path.relative_to(self.project_root).as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily archive pipeline.")
    parser.add_argument("--trading-day", required=True, help="Trading day in YYYY-MM-DD format.")
    parser.add_argument("--force-rerun", action="store_true", help="Allow rerun when success marker exists.")
    parser.add_argument("--rerun-reason", help="Reason for the rerun.")
    parser.add_argument("--dry-run", action="store_true", help="Execute with placeholder outputs only.")
    return parser.parse_args()


def now_local() -> datetime:
    return datetime.now().astimezone()


def isoformat_local(dt: datetime | None = None) -> str:
    if dt is None:
        dt = now_local()
    return dt.isoformat(timespec="seconds")


def trading_day_cutoff(trading_day: str) -> str:
    date_value = datetime.strptime(trading_day, "%Y-%m-%d").date()
    return datetime.combine(date_value, time(hour=15), tzinfo=now_local().tzinfo or UTC).isoformat(timespec="seconds")


def compute_next_revision(archive_root: Path) -> int:
    manifest_path = archive_root / "manifests" / "day_manifest.json"
    if not manifest_path.exists():
        return 1
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 1
    return int(manifest.get("archive_revision", 0)) + 1


def build_run_id(trading_day: str, archive_revision: int) -> str:
    compact_day = trading_day.replace("-", "")
    return f"archive_{compact_day}_{archive_revision:02d}"


def init_context(args: argparse.Namespace) -> ArchiveContext:
    validate_trading_day(args.trading_day)
    archive_root = PROJECT_ROOT / "data" / "archive" / f"trading_day={args.trading_day}"
    archive_revision = compute_next_revision(archive_root)
    started_at = isoformat_local()
    return ArchiveContext(
        trading_day=args.trading_day,
        force_rerun=args.force_rerun,
        rerun_reason=args.rerun_reason,
        dry_run=args.dry_run,
        project_root=PROJECT_ROOT,
        archive_root=archive_root,
        manifests_dir=archive_root / "manifests",
        lock_path=archive_root / ".lock",
        manifest_path=archive_root / "manifests" / "day_manifest.json",
        success_marker_path=archive_root / "_SUCCESS.json",
        failed_marker_path=archive_root / "_FAILED.json",
        archive_revision=archive_revision,
        run_id=build_run_id(args.trading_day, archive_revision),
        started_at=started_at,
        generated_at=started_at,
        data_cutoff_time=trading_day_cutoff(args.trading_day),
    )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def acquire_lock(ctx: ArchiveContext) -> None:
    ensure_parent(ctx.lock_path)
    if ctx.lock_path.exists():
        raise RuntimeError(f"lock already exists: {ctx.relpath(ctx.lock_path)}")
    payload = {
        "trading_day": ctx.trading_day,
        "run_id": ctx.run_id,
        "archive_revision": ctx.archive_revision,
        "started_at": ctx.started_at,
        "pid": os.getpid(),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(ctx.lock_path, flags)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        ctx.lock_path.unlink(missing_ok=True)
        raise


def release_lock(ctx: ArchiveContext) -> None:
    ctx.lock_path.unlink(missing_ok=True)


def initialize_archive_dirs(ctx: ArchiveContext) -> None:
    for relative_dir in ("bars", "features", "datasets", "snapshots", "audit", "manifests"):
        (ctx.archive_root / relative_dir).mkdir(parents=True, exist_ok=True)


def check_prerequisites(ctx: ArchiveContext) -> None:
    validate_trading_day(ctx.trading_day)
    if ctx.success_marker_path.exists() and not ctx.force_rerun:
        raise RuntimeError(
            f"success marker already exists for {ctx.trading_day}; use --force-rerun to create revision {ctx.archive_revision}"
        )


def write_run_context(ctx: ArchiveContext) -> None:
    run_context_path = ctx.manifests_dir / "run_context.json"
    payload = {
        "trading_day": ctx.trading_day,
        "run_id": ctx.run_id,
        "archive_revision": ctx.archive_revision,
        "force_rerun": ctx.force_rerun,
        "rerun_reason": ctx.rerun_reason,
        "dry_run": ctx.dry_run,
        "started_at": ctx.started_at,
        "data_cutoff_time": ctx.data_cutoff_time,
    }
    run_context_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_stage(ctx: ArchiveContext, stage: str) -> None:
    ctx.current_stage = stage
    ctx.stage_history.append(stage)


def mark_previous_failure_superseded(ctx: ArchiveContext) -> None:
    if ctx.failed_marker_path.exists():
        ctx.failed_marker_path.unlink()


def execute_pipeline(ctx: ArchiveContext) -> dict[str, Any]:
    set_stage(ctx, "phase_0_prepare")
    check_prerequisites(ctx)
    initialize_archive_dirs(ctx)
    write_run_context(ctx)

    set_stage(ctx, "phase_2_market_close_freeze")
    freeze_state = freeze_intraday_state(ctx)

    set_stage(ctx, "phase_3_final_recompute")
    final_inputs = load_final_inputs(ctx)
    bars = build_final_bars(ctx, final_inputs)
    features = build_final_features(ctx, bars)
    datasets = build_final_datasets(ctx, features)
    snapshots = build_final_snapshots(ctx, datasets)
    audit = build_audit_artifacts(ctx, final_inputs)

    set_stage(ctx, "phase_5_validation_publish")
    validations = run_archive_validations(
        ctx=ctx,
        final_inputs=final_inputs,
        datasets_included=[*bars, *features, *datasets, *snapshots, *audit],
    )
    completed_at = isoformat_local()
    manifest = build_day_manifest(
        ctx=ctx,
        final_inputs=final_inputs,
        freeze_state=freeze_state,
        datasets_included=[*bars, *features, *datasets, *snapshots, *audit],
        validation_summary=validations,
        completed_at=completed_at,
    )
    set_stage(ctx, "manifest_write")
    write_day_manifest(ctx.manifest_path, manifest)

    set_stage(ctx, "success_marker_write")
    mark_previous_failure_superseded(ctx)
    write_success_marker(ctx.success_marker_path, manifest)
    return manifest


def build_failure_payload(ctx: ArchiveContext, exc: BaseException) -> dict[str, Any]:
    failed_at = isoformat_local()
    error_summary = str(exc).strip() or exc.__class__.__name__
    traceback_summary = traceback.format_exception_only(type(exc), exc)
    return {
        "trading_day": ctx.trading_day,
        "archive_status": "failed",
        "run_id": ctx.run_id,
        "archive_revision": ctx.archive_revision,
        "started_at": ctx.started_at,
        "failed_at": failed_at,
        "failed_stage": ctx.current_stage,
        "error_code": exc.__class__.__name__.upper(),
        "error_summary": error_summary,
        "retryable": True,
        "manifest_path": ctx.relpath(ctx.manifest_path) if ctx.manifest_path.exists() else None,
        "generated_at": failed_at,
        "details": [line.strip() for line in traceback_summary if line.strip()],
    }


def main() -> int:
    args = parse_args()
    ctx = init_context(args)
    acquire_lock(ctx)
    try:
        execute_pipeline(ctx)
        return 0
    except Exception as exc:
        initialize_archive_dirs(ctx)
        failure_payload = build_failure_payload(ctx, exc)
        write_failed_marker(ctx.failed_marker_path, failure_payload)
        return 1
    finally:
        release_lock(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
