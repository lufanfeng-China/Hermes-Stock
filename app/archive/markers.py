"""Status marker writers for archive runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_success_marker(path: Path, manifest: dict[str, Any]) -> None:
    payload = {
        "trading_day": manifest["trading_day"],
        "archive_status": "success",
        "run_id": manifest["run_id"],
        "archive_revision": manifest["archive_revision"],
        "started_at": manifest["started_at"],
        "completed_at": manifest["completed_at"],
        "data_cutoff_time": manifest["data_cutoff_time"],
        "dataset_count": len(manifest["datasets_included"]),
        "validation_passed": manifest["validation_summary"]["overall_status"] == "passed",
        "manifest_path": manifest["artifacts"]["manifest_path"],
        "generated_at": manifest["generated_at"],
    }
    _write_json(path, payload)


def write_failed_marker(path: Path, payload: dict[str, Any]) -> None:
    _write_json(path, payload)
