"""Fast per-symbol reads from the normalized financial time-series warehouse."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAREHOUSE_DIR = PROJECT_ROOT / "data" / "derived" / "financial_ts" / "by_quarter"


def _period_order(period: str) -> tuple[int, int]:
    value = str(period).strip()
    year = int(value[:4]) if len(value) >= 4 and value[:4].isdigit() else 0
    suffix = value[4:]
    return year, {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}.get(suffix, 0)


def load_symbol_financial_rows(symbol: str, *, years: int = 6, warehouse_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return a symbol's recent rows without reading raw TDX CW archives.

    The warehouse files retain ``code`` as their pandas index.  Reading a single
    Parquet period is inexpensive compared with parsing a complete CW archive;
    only the target row is retained in the returned history.
    """
    code = str(symbol or "").strip().zfill(6)
    root = Path(warehouse_dir or DEFAULT_WAREHOUSE_DIR)
    files = sorted((p for p in root.glob("*.parquet") if p.stem != "latest"), key=lambda p: _period_order(p.stem))
    if not files:
        return []
    latest_year = max(_period_order(p.stem)[0] for p in files)
    earliest_year = latest_year - max(1, int(years)) + 1
    rows: list[dict[str, Any]] = []
    for path in files:
        period = path.stem
        if _period_order(period)[0] < earliest_year:
            continue
        frame = pd.read_parquet(path)
        candidates = (code, code.lstrip("0"), code[1:] if code.startswith("0") else "")
        selected = next((candidate for candidate in candidates if candidate and candidate in frame.index), None)
        if selected is None:
            continue
        rows.append({"period": period, "row": frame.loc[selected]})
    return rows
