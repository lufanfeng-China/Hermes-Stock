from __future__ import annotations

import json
from pathlib import Path

from app.relative_valuation.data_loader import INDUSTRY_VALUATION_CURRENT_PATH, build_industry_snapshot_for_industry
from app.search.index import load_industry_rows

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "archive"


def build_current_industry_snapshots() -> list[dict[str, object]]:
    names = sorted(
        {
            str(row.get("industry_level_2_name") or "").strip()
            for row in load_industry_rows()
            if str(row.get("industry_level_2_name") or "").strip()
        }
    )
    rows: list[dict[str, object]] = []
    for name in names:
        snapshot = build_industry_snapshot_for_industry(name)
        if snapshot:
            rows.append(snapshot)
    rows.sort(key=lambda row: str(row.get("industry_level_2_name") or ""))
    return rows


def write_current_industry_snapshots(
    path: str | Path = INDUSTRY_VALUATION_CURRENT_PATH,
    archive_root: str | Path | None = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    target = Path(path)
    rows = build_current_industry_snapshots()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trading_day = _resolve_archive_trading_day(rows)
    if archive_root is not None and trading_day:
        archive_path = Path(archive_root) / f"trading_day={trading_day}" / "snapshots" / "snapshot_industry_relative_valuation_current.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _resolve_archive_trading_day(rows: list[dict[str, object]]) -> str | None:
    candidates = []
    for row in rows:
        trading_day = str(row.get("trading_day") or "").strip()
        if len(trading_day) == 10 and trading_day[4] == "-" and trading_day[7] == "-":
            candidates.append(trading_day)
    if not candidates:
        return None
    return max(candidates)
