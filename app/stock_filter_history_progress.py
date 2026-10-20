"""Atomic task progress files for on-demand historical stock-filter snapshots."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def progress_path(directory: Path, trading_day: str) -> Path:
    return directory / f"{trading_day}.progress.json"


def write_progress(directory: Path, trading_day: str, *, stage: str, percent: float, completed: int = 0, total: int = 0) -> dict[str, Any]:
    """Publish a small, atomically replaced progress record safe for browser polling."""
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "trading_day": trading_day,
        "stage": str(stage),
        "percent": max(0, min(100, int(float(percent)))),
        "completed": max(0, int(completed)),
        "total": max(0, int(total)),
    }
    target = progress_path(directory, trading_day)
    with NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        temp = Path(handle.name)
    os.replace(temp, target)
    return payload


def read_progress(directory: Path, trading_day: str) -> dict[str, Any]:
    try:
        payload = json.loads(progress_path(directory, trading_day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"trading_day": trading_day, "stage": "正在准备历史快照", "percent": 0, "completed": 0, "total": 0}
    if not isinstance(payload, dict):
        return {"trading_day": trading_day, "stage": "正在准备历史快照", "percent": 0, "completed": 0, "total": 0}
    return {
        "trading_day": trading_day,
        "stage": str(payload.get("stage") or "正在准备历史快照"),
        "percent": max(0, min(100, int(payload.get("percent") or 0))),
        "completed": max(0, int(payload.get("completed") or 0)),
        "total": max(0, int(payload.get("total") or 0)),
    }
