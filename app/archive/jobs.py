"""Stage jobs for the minimal archive pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _touch_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _dataset_entry(
    *,
    ctx: Any,
    dataset_name: str,
    dataset_category: str,
    dataset_scope: str,
    subject_type: str,
    storage_layer: str,
    relative_path: str,
    row_count: int,
    base_interval: str | None,
    target_interval: str | None,
    symbol_count: int | None = None,
) -> dict[str, Any]:
    artifact_path = ctx.project_root / relative_path
    placeholder_payload = {
        "dataset_name": dataset_name,
        "trading_day": ctx.trading_day,
        "run_id": ctx.run_id,
        "archive_revision": ctx.archive_revision,
        "data_status": "final",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if artifact_path.suffix == ".json":
        _write_json(artifact_path, placeholder_payload)
    else:
        _touch_placeholder(artifact_path)
        _write_json(artifact_path.with_suffix(".json"), placeholder_payload)
    entry = {
        "dataset_name": dataset_name,
        "dataset_category": dataset_category,
        "dataset_scope": dataset_scope,
        "subject_type": subject_type,
        "storage_layer": storage_layer,
        "data_status": "final",
        "base_interval": base_interval,
        "target_interval": target_interval,
        "partition": f"trading_day={ctx.trading_day}",
        "path": relative_path,
        "row_count": row_count,
        "generated_at": placeholder_payload["generated_at"],
        "data_cutoff_time": ctx.data_cutoff_time,
        "validation_status": "passed",
    }
    if symbol_count is not None:
        entry["symbol_count"] = symbol_count
    return entry


def freeze_intraday_state(ctx: Any) -> dict[str, Any]:
    freeze_path = ctx.archive_root / "audit" / "freeze_intraday_state.json"
    payload = {
        "trading_day": ctx.trading_day,
        "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "intraday_state": "stubbed",
        "dry_run": ctx.dry_run,
    }
    _write_json(freeze_path, payload)
    return payload


def load_final_inputs(ctx: Any) -> dict[str, Any]:
    metadata = {
        "source_summary": {
            "primary_source": "local_tdx",
            "secondary_sources": ["tdx_api"],
            "data_status": "final",
            "price_mode_default": "qfq",
            "intraday_base_interval": "1m",
            "derived_base_interval": "5m",
            "fallback_enabled": True,
        },
        "versions": {
            "api_version": "v1",
            "schema_version": "1.0.0",
            "rule_version": "1.0.0",
            "derivation_version": "1.0.0",
            "data_pipeline_version": "1.0.0",
            "model_version": "stdlib-stub",
        },
        "notes": [
            "This archive run uses stdlib-only placeholder outputs.",
            "Final source loading is stubbed and returns metadata only.",
        ],
        "exception_summary": {
            "has_exceptions": False,
            "exception_count": 0,
            "retryable_count": 0,
            "non_retryable_count": 0,
            "top_errors": [],
        },
    }
    _write_json(ctx.archive_root / "audit" / "final_inputs_metadata.json", metadata)
    return metadata


def build_final_bars(ctx: Any, final_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    del final_inputs
    return [
        _dataset_entry(
            ctx=ctx,
            dataset_name="bars_15m",
            dataset_category="bars",
            dataset_scope="stock",
            subject_type="time_series",
            storage_layer="derived_store",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/bars/bars_15m.parquet",
            row_count=10,
            symbol_count=3,
            base_interval="5m",
            target_interval="15m",
        )
    ]


def build_final_features(ctx: Any, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del bars
    return [
        _dataset_entry(
            ctx=ctx,
            dataset_name="features_intraday_momentum",
            dataset_category="features",
            dataset_scope="stock",
            subject_type="feature_series",
            storage_layer="derived_store",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/features/features_intraday_momentum.parquet",
            row_count=10,
            base_interval="5m",
            target_interval="15m",
        )
    ]


def build_final_datasets(ctx: Any, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del features
    return [
        _dataset_entry(
            ctx=ctx,
            dataset_name="dataset_stock_candidate_pool",
            dataset_category="dataset",
            dataset_scope="stock",
            subject_type="tabular_dataset",
            storage_layer="final_archive",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/datasets/dataset_stock_candidate_pool.parquet",
            row_count=3,
            base_interval=None,
            target_interval="daily",
        )
    ]


def build_final_snapshots(ctx: Any, datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del datasets
    return [
        _dataset_entry(
            ctx=ctx,
            dataset_name="snapshot_market_overview",
            dataset_category="snapshot",
            dataset_scope="market",
            subject_type="snapshot",
            storage_layer="final_archive",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/snapshots/snapshot_market_overview.json",
            row_count=1,
            base_interval=None,
            target_interval="daily",
        )
    ]


def build_audit_artifacts(ctx: Any, final_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    del final_inputs
    return [
        _dataset_entry(
            ctx=ctx,
            dataset_name="audit_signal_events",
            dataset_category="audit",
            dataset_scope="stock",
            subject_type="event_log",
            storage_layer="final_archive",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/audit/audit_signal_events.json",
            row_count=1,
            base_interval=None,
            target_interval=None,
        )
    ]
