"""Per-symbol view over the published full-market stage history.

The history parquet is written stock-by-stock, so a symbol filter with column
pruning stays cheap.  Everything returned here is descriptive: the labels say
what the price structure looked like on that day, not what it will do next.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.stage_classify import EVENT_STAGES, _REGION_LABELS, _STAGE_LABELS

FINAL_DIR = Path(__file__).resolve().parent.parent / "data" / "derived" / "datasets" / "final"
DEFAULT_HISTORY = FINAL_DIR / "stage_history.parquet"

DEFAULT_MONTHS = 12
MAX_MONTHS = 60

_SERIES_COLUMNS = [
    "trading_day", "region", "stage", "range_pos_60", "pos_high_60",
    "slope20", "slope60", "bias20", "vol_ratio",
]


@dataclass(frozen=True)
class StageSegment:
    stage: str
    region: str
    start: str
    end: str
    trading_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_label": _STAGE_LABELS.get(self.stage, self.stage),
            "region": self.region,
            "region_label": _REGION_LABELS.get(self.region, self.region),
            "is_event": self.stage in EVENT_STAGES,
            "start": self.start,
            "end": self.end,
            "trading_days": self.trading_days,
        }


def _segments(rows: pd.DataFrame) -> list[StageSegment]:
    """Collapse consecutive identical stages into runs (input must be ascending)."""
    segments: list[StageSegment] = []
    for record in rows.itertuples(index=False):
        stage = str(record.stage)
        day = str(record.trading_day)
        if segments and segments[-1].stage == stage:
            last = segments[-1]
            segments[-1] = StageSegment(last.stage, last.region, last.start, day, last.trading_days + 1)
        else:
            segments.append(StageSegment(stage, str(record.region), day, day, 1))
    return segments


def _round(value: object, digits: int) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, digits)


def load_stage_series(
    symbol: str,
    months: int = DEFAULT_MONTHS,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return the last `months` of stage labels for one symbol.

    Raises FileNotFoundError when the history library has not been built yet, and
    KeyError when the symbol has no rows in the window.
    """
    history_path = Path(path) if path is not None else DEFAULT_HISTORY
    if not history_path.exists():
        raise FileNotFoundError(f"stage history not built: {history_path}")

    code = str(symbol).strip().zfill(6)
    span = max(1, min(int(months), MAX_MONTHS))

    # push the symbol filter into pyarrow so row groups are pruned instead of
    # materialising all 12.5M rows for every request
    frame = pd.read_parquet(
        history_path,
        columns=["symbol", *_SERIES_COLUMNS],
        filters=[("symbol", "==", code)],
    ).sort_values("trading_day", kind="stable")
    if frame.empty:
        raise KeyError(code)

    as_of = str(frame["trading_day"].iloc[-1])
    window_start = str((pd.Timestamp(as_of) - pd.DateOffset(months=span)).date())
    window = frame[frame["trading_day"] >= window_start].reset_index(drop=True)
    if window.empty:
        raise KeyError(code)

    segments = _segments(window)
    current = segments[-1]
    rows = [
        {
            "trading_day": str(record.trading_day),
            "stage": str(record.stage),
            "region": str(record.region),
            "range_pos_60": _round(record.range_pos_60, 4),
            "pos_high_60": _round(record.pos_high_60, 4),
            "slope20": _round(record.slope20, 5),
            "slope60": _round(record.slope60, 5),
            "bias20": _round(record.bias20, 4),
            "vol_ratio": _round(record.vol_ratio, 3),
        }
        for record in window.itertuples(index=False)
    ]

    longest = max(segments, key=lambda item: item.trading_days)
    return {
        "ok": True,
        "symbol": code,
        "months": span,
        "as_of": as_of,
        "window_start": str(window["trading_day"].iloc[0]),
        "price_basis": "tdx_export_qfq",
        "lookahead": "none — each row uses bars up to and including its trading_day",
        "bars": len(rows),
        "current": {
            **current.as_dict(),
            "is_current": True,
        },
        "longest": longest.as_dict(),
        "segments": [segment.as_dict() for segment in segments],
        "rows": rows,
        "labels": {
            "stages": _STAGE_LABELS,
            "regions": _REGION_LABELS,
            "event_stages": sorted(EVENT_STAGES),
        },
    }
