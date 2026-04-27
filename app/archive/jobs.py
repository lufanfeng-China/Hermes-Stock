"""Stage jobs for the minimal archive pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import subprocess
from typing import Any

from app.tdx.parsers import (
    CONCEPT_CURRENT_DATASET,
    CONCEPT_DICTIONARY_DATASET,
    CONCEPT_SNAPSHOT_DATASET,
    DEFAULT_CONCEPT_SOURCE_FILE,
    DEFAULT_INDUSTRY_SOURCE_FILE,
    INDUSTRY_CURRENT_DATASET,
    INDUSTRY_SNAPSHOT_DATASET,
    build_concept_datasets,
    build_industry_datasets,
    load_text_file,
    with_dataset_name,
)


TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
TARGET_MARKET = "sh"
TARGET_SYMBOL = "601600"
REAL_FEATURE_DATASET_NAME = "features_intraday_volume_windows"
TDXHY_PATH = Path("/mnt/c/new_tdx64/T0002/hq_cache/tdxhy.cfg")
TDXZS3_PATH = Path("/mnt/c/new_tdx64/T0002/hq_cache/tdxzs3.cfg")
TDXZS_PATH = Path("/mnt/c/new_tdx64/T0002/hq_cache/tdxzs.cfg")
EXTERN_SYS_PATH = Path("/mnt/c/new_tdx64/T0002/signals/extern_sys.txt")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _touch_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _write_json_rows_with_placeholder(path: Path, rows: list[dict[str, Any]]) -> None:
    _touch_placeholder(path)
    _write_json(path.with_suffix(".json"), rows)


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


def _rows_to_dataset_entry(
    *,
    ctx: Any,
    dataset_name: str,
    dataset_category: str,
    dataset_scope: str,
    subject_type: str,
    storage_layer: str,
    relative_path: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_path = ctx.project_root / relative_path
    _write_json_rows_with_placeholder(artifact_path, rows)
    entry = {
        "dataset_name": dataset_name,
        "dataset_category": dataset_category,
        "dataset_scope": dataset_scope,
        "subject_type": subject_type,
        "storage_layer": storage_layer,
        "data_status": "final",
        "base_interval": None,
        "target_interval": "daily",
        "partition": f"trading_day={ctx.trading_day}",
        "path": relative_path,
        "row_count": len(rows),
        "generated_at": rows[0]["generated_at"] if rows else ctx.generated_at,
        "data_cutoff_time": ctx.data_cutoff_time,
        "validation_status": "passed",
    }
    symbols = {str(row.get("market", "")) + ":" + str(row.get("symbol", "")) for row in rows if row.get("symbol")}
    if symbols:
        entry["symbol_count"] = len(symbols)
    return entry


def _load_industry_concept_datasets(ctx: Any) -> dict[str, list[dict[str, Any]]]:
    cached = getattr(ctx, "_industry_concept_cache", None)
    if cached is not None:
        return cached

    industry_code_path = TDXZS3_PATH if TDXZS3_PATH.exists() else TDXZS_PATH
    industry_current_rows, industry_snapshot_rows = build_industry_datasets(
        stock_mapping_text=load_text_file(TDXHY_PATH, preferred_encoding="utf-8"),
        industry_code_text=load_text_file(industry_code_path, preferred_encoding="gbk"),
        trading_day=ctx.trading_day,
        generated_at=ctx.generated_at,
        data_cutoff_time=ctx.data_cutoff_time,
        source_file=DEFAULT_INDUSTRY_SOURCE_FILE if str(TDXHY_PATH).startswith("/mnt/c/new_tdx64/") else str(TDXHY_PATH),
    )
    concept_dictionary_rows, concept_current_rows, concept_snapshot_rows = build_concept_datasets(
        concept_text=load_text_file(EXTERN_SYS_PATH, preferred_encoding="gbk"),
        trading_day=ctx.trading_day,
        generated_at=ctx.generated_at,
        data_cutoff_time=ctx.data_cutoff_time,
        source_file=DEFAULT_CONCEPT_SOURCE_FILE if str(EXTERN_SYS_PATH).startswith("/mnt/c/new_tdx64/") else str(EXTERN_SYS_PATH),
    )
    cached = {
        "industry_current": industry_current_rows,
        "industry_snapshot": with_dataset_name(industry_snapshot_rows, INDUSTRY_SNAPSHOT_DATASET),
        "concept_dictionary": concept_dictionary_rows,
        "concept_current": concept_current_rows,
        "concept_snapshot": with_dataset_name(concept_snapshot_rows, CONCEPT_SNAPSHOT_DATASET),
    }
    setattr(ctx, "_industry_concept_cache", cached)
    return cached


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
    script = """
import json
import sys
from mootdx.reader import Reader

trading_day = sys.argv[1]
symbol = sys.argv[2]
tdxdir = sys.argv[3]
reader = Reader.factory(market="std", tdxdir=tdxdir)
frame = reader.minute(symbol=symbol, suffix=1)
day_frame = frame.loc[trading_day]
rows = []
for index, row in day_frame.iterrows():
    rows.append(
        {
            "timestamp": index.isoformat(sep=" ", timespec="seconds"),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "amount": float(row["amount"]),
            "volume": int(row["volume"]),
        }
    )
payload = {
    "market": sys.argv[4],
    "symbol": symbol,
    "trading_day": trading_day,
    "row_count": len(rows),
    "first_timestamp": rows[0]["timestamp"] if rows else None,
    "last_timestamp": rows[-1]["timestamp"] if rows else None,
    "rows": rows,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [TONGDAXIN_PYTHON, "-c", script, ctx.trading_day, TARGET_SYMBOL, TONGDAXIN_DIR, TARGET_MARKET],
        check=True,
        capture_output=True,
        text=True,
    )
    minute_payload = json.loads(result.stdout)
    metadata = {
        "source_summary": {
            "primary_source": "local_tongdaxin_minute",
            "secondary_sources": [],
            "data_status": "final",
            "price_mode_default": "raw",
            "intraday_base_interval": "1m",
            "derived_base_interval": "1m",
            "fallback_enabled": False,
        },
        "versions": {
            "api_version": "v1",
            "schema_version": "1.0.0",
            "rule_version": "1.0.0",
            "derivation_version": "real-volume-window-v1",
            "data_pipeline_version": "1.0.0",
            "model_version": "stdlib-subprocess-tdx",
        },
        "notes": [
            "Loaded local Tongdaxin 1-minute data via subprocess for one stock.",
            "Real feature aggregation is enabled only for symbol 601600.",
        ],
        "symbols_loaded": [
            {
                "market": minute_payload["market"],
                "symbol": minute_payload["symbol"],
                "row_count": minute_payload["row_count"],
                "first_timestamp": minute_payload["first_timestamp"],
                "last_timestamp": minute_payload["last_timestamp"],
            }
        ],
        "exception_summary": {
            "has_exceptions": False,
            "exception_count": 0,
            "retryable_count": 0,
            "non_retryable_count": 0,
            "top_errors": [],
        },
        "minute_data": minute_payload,
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
            row_count=1,
            symbol_count=1,
            base_interval="1m",
            target_interval="15m",
        )
    ]


def _sum_window(
    minute_rows: list[dict[str, Any]],
    *,
    trading_day: str,
    window_start: str,
    window_end: str,
) -> tuple[int, float, int]:
    start_ts = f"{trading_day} {window_start}:00"
    end_ts = f"{trading_day} {window_end}:00"
    selected_rows = [row for row in minute_rows if start_ts <= row["timestamp"] <= end_ts]
    volume_sum = sum(int(row["volume"]) for row in selected_rows)
    amount_sum = sum(float(row["amount"]) for row in selected_rows)
    return volume_sum, amount_sum, len(selected_rows)


def build_final_features(ctx: Any, final_inputs: dict[str, Any], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del bars
    minute_data = final_inputs["minute_data"]
    minute_rows = minute_data["rows"]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    indicators: list[dict[str, Any]] = []
    for indicator_name, window_start, window_end in (
        ("open_15m_volume", "09:31", "09:45"),
        ("window_1430_1445_volume", "14:30", "14:45"),
    ):
        volume_sum, amount_sum, bar_count = _sum_window(
            minute_rows,
            trading_day=ctx.trading_day,
            window_start=window_start,
            window_end=window_end,
        )
        indicators.append(
            {
                "trading_day": ctx.trading_day,
                "market": minute_data["market"],
                "symbol": minute_data["symbol"],
                "indicator_name": indicator_name,
                "window_start": window_start,
                "window_end": window_end,
                "base_interval": "1m",
                "volume_sum": volume_sum,
                "amount_sum": amount_sum,
                "bar_count": bar_count,
                "data_status": "final",
                "data_source": "local_tongdaxin_minute",
                "generated_at": generated_at,
                "data_cutoff_time": ctx.data_cutoff_time,
            }
        )

    relative_path = f"data/archive/trading_day={ctx.trading_day}/features/{REAL_FEATURE_DATASET_NAME}.json"
    artifact_path = ctx.project_root / relative_path
    artifact_payload = {
        "dataset_name": REAL_FEATURE_DATASET_NAME,
        "trading_day": ctx.trading_day,
        "market": minute_data["market"],
        "symbol": minute_data["symbol"],
        "base_interval": "1m",
        "data_source": "local_tongdaxin_minute",
        "data_status": "final",
        "generated_at": generated_at,
        "data_cutoff_time": ctx.data_cutoff_time,
        "indicator_count": len(indicators),
        "indicators": indicators,
    }
    _write_json(artifact_path, artifact_payload)
    return [
        {
            "dataset_name": REAL_FEATURE_DATASET_NAME,
            "dataset_category": "features",
            "dataset_scope": "stock",
            "subject_type": "feature_series",
            "storage_layer": "derived_store",
            "data_status": "final",
            "base_interval": "1m",
            "target_interval": "window",
            "partition": f"trading_day={ctx.trading_day}",
            "path": relative_path,
            "row_count": len(indicators),
            "symbol_count": 1,
            "generated_at": generated_at,
            "data_cutoff_time": ctx.data_cutoff_time,
            "validation_status": "passed",
        }
    ]


def build_final_datasets(ctx: Any, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del features
    reference_rows = _load_industry_concept_datasets(ctx)
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
        ),
        _rows_to_dataset_entry(
            ctx=ctx,
            dataset_name=INDUSTRY_CURRENT_DATASET,
            dataset_category="dataset",
            dataset_scope="stock",
            subject_type="tabular_dataset",
            storage_layer="derived_store",
            relative_path=f"data/derived/datasets/final/{INDUSTRY_CURRENT_DATASET}.parquet",
            rows=reference_rows["industry_current"],
        ),
        _rows_to_dataset_entry(
            ctx=ctx,
            dataset_name=CONCEPT_DICTIONARY_DATASET,
            dataset_category="dataset",
            dataset_scope="market",
            subject_type="tabular_dataset",
            storage_layer="derived_store",
            relative_path=f"data/derived/datasets/final/{CONCEPT_DICTIONARY_DATASET}.parquet",
            rows=reference_rows["concept_dictionary"],
        ),
        _rows_to_dataset_entry(
            ctx=ctx,
            dataset_name=CONCEPT_CURRENT_DATASET,
            dataset_category="dataset",
            dataset_scope="stock",
            subject_type="tabular_dataset",
            storage_layer="derived_store",
            relative_path=f"data/derived/datasets/final/{CONCEPT_CURRENT_DATASET}.parquet",
            rows=reference_rows["concept_current"],
        ),
    ]


def build_final_snapshots(ctx: Any, datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del datasets
    reference_rows = _load_industry_concept_datasets(ctx)
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
        ),
        _rows_to_dataset_entry(
            ctx=ctx,
            dataset_name=INDUSTRY_SNAPSHOT_DATASET,
            dataset_category="snapshot",
            dataset_scope="stock",
            subject_type="snapshot",
            storage_layer="archive",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/snapshots/{INDUSTRY_SNAPSHOT_DATASET}.parquet",
            rows=reference_rows["industry_snapshot"],
        ),
        _rows_to_dataset_entry(
            ctx=ctx,
            dataset_name=CONCEPT_SNAPSHOT_DATASET,
            dataset_category="snapshot",
            dataset_scope="stock",
            subject_type="snapshot",
            storage_layer="archive",
            relative_path=f"data/archive/trading_day={ctx.trading_day}/snapshots/{CONCEPT_SNAPSHOT_DATASET}.parquet",
            rows=reference_rows["concept_snapshot"],
        ),
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
