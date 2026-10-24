"""Materialized snapshot access for the independent first-wave page."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.first_wave_start import sort_key
from app.stock_filter_history_progress import read_progress

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
CURRENT = FINAL / "first_wave_start_current.json"
HISTORY = FINAL / "first_wave_start_history"
SCHEMA_VERSION = "first-wave-start-v2-five-rules"


def response_from_rows(rows: list[dict[str, Any]], *, as_of_date: str, data_date: str, historical: bool) -> dict[str, Any]:
    groups = {"main": [row for row in rows if row.get("classification") == "FIRST_WAVE_ELIGIBLE"]}
    groups["main"].sort(key=sort_key)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "data_as_of": data_date, "effective_trade_date": as_of_date, "is_historical": historical,
            "groups": groups, "counts": {key: len(value) for key, value in groups.items()},
            "disclosure": "仅展示信号日收盘后可见的 PIT 证据；不展示未来收益或组合回测。"}


def _load(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def response(as_of_date: str = "") -> dict[str, Any]:
    historical = bool(as_of_date)
    path = HISTORY / f"{as_of_date}.json" if historical else CURRENT
    if historical:
        failure_path = HISTORY / f"{as_of_date}.error.json"
        failure = _load(failure_path)
        if failure.get("schema_version") == SCHEMA_VERSION:
            failure_path.unlink(missing_ok=True)  # A deliberate next query can retry.
            return {"ok": False, "error": {"code": "historical_snapshot_failed", "message": f"历史快照构建失败：{failure.get('message') or '未知错误'}；请检查日期与数据后重新查询。"}}
    payload = _load(path)
    if not payload or (historical and payload.get("schema_version") != SCHEMA_VERSION):
        if historical:
            HISTORY.mkdir(parents=True, exist_ok=True)
            lock = HISTORY / f"{as_of_date}.building"
            if not lock.exists():
                try:
                    lock.touch(exist_ok=False)
                    with open(HISTORY / f"{as_of_date}.log", "a", encoding="utf-8") as log:
                        subprocess.Popen([sys.executable, str(ROOT / "scripts" / "build_first_wave_snapshot.py"), "--trading-day", as_of_date], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except FileExistsError:
                    pass
                except OSError as exc:
                    lock.unlink(missing_ok=True)
                    return {"ok": False, "error": {"code": "historical_snapshot_failed", "message": f"无法启动历史快照构建：{exc}"}}
            return {"ok": False, "error": {"code": "historical_snapshot_building", "message": f"历史第一波快照正在构建：{as_of_date}", "progress": read_progress(HISTORY, as_of_date)}}
        return {"ok": False, "error": {"code": "snapshot_unavailable", "message": "当前第一波快照尚未构建"}}
    if payload.get("schema_version") != SCHEMA_VERSION:
        return {"ok": False, "error": {"code": "snapshot_stale", "message": "第一波快照版本过期，需重建"}}
    if historical and payload.get("as_of_date") != as_of_date:
        return {"ok": False, "error": {"code": "historical_snapshot_unavailable", "message": "历史快照日期不匹配"}}
    return response_from_rows(payload.get("rows") or [], as_of_date=str(payload.get("as_of_date") or ""), data_date=str(payload.get("data_date") or ""), historical=historical)
