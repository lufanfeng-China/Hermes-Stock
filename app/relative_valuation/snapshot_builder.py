from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app.relative_valuation.data_loader import INDUSTRY_VALUATION_CURRENT_PATH, build_industry_snapshot_for_industry
from app.search.index import load_industry_rows

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "archive"
ProgressCallback = Callable[[dict[str, object]], None]


def build_current_industry_snapshots(
    *,
    progress_callback: ProgressCallback | None = None,
    continue_on_error: bool = True,
    reuse_existing_complete: bool = False,
    existing_path: str | Path = INDUSTRY_VALUATION_CURRENT_PATH,
) -> list[dict[str, object]]:
    names = _current_industry_names()
    existing_lookup = _load_existing_snapshot_lookup(existing_path) if reuse_existing_complete else {}
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    skipped_count = 0
    total_member_valuation_rows = 0

    _emit(progress_callback, {"event": "start", "total_industries": len(names)})
    for index, name in enumerate(names, start=1):
        existing = existing_lookup.get(name)
        if reuse_existing_complete and _is_complete_industry_snapshot(existing):
            member_count = _member_valuation_row_count(existing)
            percentile_count = _percentile_sample_count(existing)
            skipped_count += 1
            total_member_valuation_rows += member_count
            rows.append(dict(existing or {}))
            _emit(progress_callback, {
                "event": "industry_skipped",
                "index": index,
                "total_industries": len(names),
                "industry_level_2_name": name,
                "member_valuation_row_count": member_count,
                "percentile_sample_count": percentile_count,
            })
            continue

        _emit(progress_callback, {
            "event": "industry_start",
            "index": index,
            "total_industries": len(names),
            "industry_level_2_name": name,
        })
        try:
            snapshot = build_industry_snapshot_for_industry(name)
        except Exception as exc:
            failure = {
                "industry_level_2_name": name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            failures.append(failure)
            _emit(progress_callback, {
                "event": "industry_failed",
                "index": index,
                "total_industries": len(names),
                "industry_level_2_name": name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            if not continue_on_error:
                raise
            continue
        if not snapshot:
            failure = {
                "industry_level_2_name": name,
                "error": "empty snapshot",
                "error_type": "EmptySnapshot",
            }
            failures.append(failure)
            _emit(progress_callback, {
                "event": "industry_failed",
                "index": index,
                "total_industries": len(names),
                "industry_level_2_name": name,
                "error": "empty snapshot",
                "error_type": "EmptySnapshot",
            })
            if not continue_on_error:
                raise RuntimeError(f"empty snapshot for {name}")
            continue
        member_count = _member_valuation_row_count(snapshot)
        percentile_count = _percentile_sample_count(snapshot)
        total_member_valuation_rows += member_count
        rows.append(snapshot)
        _emit(progress_callback, {
            "event": "industry_done",
            "index": index,
            "total_industries": len(names),
            "industry_level_2_name": name,
            "member_valuation_row_count": member_count,
            "percentile_sample_count": percentile_count,
        })

    rows.sort(key=lambda row: str(row.get("industry_level_2_name") or ""))
    _emit(progress_callback, {
        "event": "complete",
        "total_industries": len(names),
        "success_count": len(rows),
        "failure_count": len(failures),
        "skipped_count": skipped_count,
        "total_member_valuation_rows": total_member_valuation_rows,
        "failures": failures,
    })
    return rows


def write_current_industry_snapshots(
    path: str | Path = INDUSTRY_VALUATION_CURRENT_PATH,
    archive_root: str | Path | None = DEFAULT_ARCHIVE_ROOT,
    *,
    progress_callback: ProgressCallback | None = None,
    continue_on_error: bool = True,
    reuse_existing_complete: bool = False,
) -> Path:
    target = Path(path)
    rows = build_current_industry_snapshots(
        progress_callback=progress_callback,
        continue_on_error=continue_on_error,
        reuse_existing_complete=reuse_existing_complete,
        existing_path=target,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trading_day = _resolve_archive_trading_day(rows)
    if archive_root is not None and trading_day:
        archive_path = Path(archive_root) / f"trading_day={trading_day}" / "snapshots" / "snapshot_industry_relative_valuation_current.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _current_industry_names() -> list[str]:
    return sorted(
        {
            str(row.get("industry_level_2_name") or "").strip()
            for row in load_industry_rows()
            if str(row.get("industry_level_2_name") or "").strip()
        }
    )


def _load_existing_snapshot_lookup(path: str | Path) -> dict[str, dict[str, object]]:
    source = Path(path)
    if not source.exists():
        return {}
    try:
        rows = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}
    lookup: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("industry_level_2_name") or "").strip()
        if name:
            lookup[name] = row
    return lookup


def _is_complete_industry_snapshot(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("temperature_history_since_2022"), list):
        return False
    if not isinstance(row.get("percentile_samples"), dict):
        return False
    member_rows = row.get("member_valuation_rows")
    return isinstance(member_rows, list) and len(member_rows) > 0


def _member_valuation_row_count(row: object) -> int:
    if not isinstance(row, dict):
        return 0
    member_rows = row.get("member_valuation_rows")
    return len(member_rows) if isinstance(member_rows, list) else 0


def _percentile_sample_count(row: object) -> int:
    if not isinstance(row, dict):
        return 0
    samples = row.get("percentile_samples")
    if not isinstance(samples, dict):
        return 0
    total = 0
    for values in samples.values():
        if isinstance(values, list):
            total += len(values)
    return total


def _emit(progress_callback: ProgressCallback | None, event: dict[str, object]) -> None:
    if progress_callback is not None:
        progress_callback(event)


def _resolve_archive_trading_day(rows: list[dict[str, object]]) -> str | None:
    candidates = []
    for row in rows:
        trading_day = str(row.get("trading_day") or "").strip()
        if len(trading_day) == 10 and trading_day[4] == "-" and trading_day[7] == "-":
            candidates.append(trading_day)
    if not candidates:
        return None
    return max(candidates)
