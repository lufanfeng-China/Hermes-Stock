"""Per-symbol view over the published A/B/C/D regime history."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
DEFAULT_HISTORY = FINAL_DIR / "regime_history.parquet"

DEFAULT_BARS = 60
MIN_BARS = 1   # 调用方显式要多少根就给多少根，不做静默放大
MAX_BARS = 750

STAGE_LABELS = {
    "A": "底部构筑/下跌中继",
    "B": "突破启动确认",
    "C": "主升推进",
    "D": "高位派发",
}
STAGE_TONE = {"A": "base", "B": "breakout", "C": "up", "D": "risk"}

_ITEMS = ("低点不创新低", "量能线上", "红肥绿瘦", "放量突破", "缩量回踩守住", "价在MA20上")
_COLUMNS = [
    "trading_day", "stage", "stage_label", "score", "reason",
    "ma20", "vol_ma5", "vol_ma60", "box_high", "box_low", "box_mid", "box_position",
    "sell_days_15", *_ITEMS, "放量滞涨", "抛售日密集",
]


@dataclass(frozen=True)
class RegimeSegment:
    stage: str
    start: str
    end: str
    trading_days: int

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS.get(self.stage, self.stage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_label": self.stage_label,
            "tone": STAGE_TONE.get(self.stage, "base"),
            "start": self.start,
            "end": self.end,
            "trading_days": self.trading_days,
        }


def _segments(frame: pd.DataFrame) -> list[RegimeSegment]:
    segments: list[RegimeSegment] = []
    for row in frame.itertuples(index=False):
        stage = str(row.stage)
        day = str(row.trading_day)
        if segments and segments[-1].stage == stage:
            last = segments[-1]
            segments[-1] = RegimeSegment(last.stage, last.start, day, last.trading_days + 1)
        else:
            segments.append(RegimeSegment(stage, day, day, 1))
    return segments


def load_regime_series(
    symbol: str,
    bars: int = DEFAULT_BARS,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return the last `bars` trading days of A/B/C/D labels for one symbol.

    Raises FileNotFoundError when the history has not been built, KeyError when
    the symbol has no rows.
    """
    history_path = Path(path) if path is not None else DEFAULT_HISTORY
    if not history_path.exists():
        raise FileNotFoundError(f"regime history not built: {history_path}")

    code = str(symbol).strip().zfill(6)
    span = max(MIN_BARS, min(int(bars), MAX_BARS))

    frame = pd.read_parquet(history_path, columns=["symbol", *_COLUMNS], filters=[("symbol", "=", code)])
    if frame.empty:
        raise KeyError(code)
    frame = frame.sort_values("trading_day").reset_index(drop=True)
    window = frame.tail(span).reset_index(drop=True)

    rows = []
    for record in window.to_dict("records"):
        rows.append({
            "trading_day": str(record["trading_day"]),
            "stage": str(record["stage"]),
            "stage_label": STAGE_LABELS.get(str(record["stage"]), str(record["stage"])),
            "tone": STAGE_TONE.get(str(record["stage"]), "base"),
            "score": int(record["score"]),
            "reason": str(record["reason"]),
            "items": {key: bool(record[key]) for key in _ITEMS},
            "penalties": {"放量滞涨": bool(record["放量滞涨"]), "抛售日密集": bool(record["抛售日密集"])},
            "evidence": {
                "ma20": float(record["ma20"]),
                "vol_ma5": float(record["vol_ma5"]),
                "vol_ma60": float(record["vol_ma60"]),
                "box_high": float(record["box_high"]),
                "box_low": float(record["box_low"]),
                "box_mid": float(record["box_mid"]),
                "box_position": float(record["box_position"]),
                "sell_days_15": int(record["sell_days_15"]),
            },
        })

    segments = _segments(window)
    current = segments[-1]
    longest = max(segments, key=lambda item: item.trading_days)

    return {
        "symbol": code,
        "bars": len(rows),
        "window_bars": span,
        "window_start": rows[0]["trading_day"],
        "as_of": rows[-1]["trading_day"],
        "price_basis": "tdx_export_qfq",
        "lookahead": "none — each row uses bars up to and including its trading_day",
        "judgement_lookback_bars": 60,
        "rows": rows,
        "segments": [segment.as_dict() for segment in segments],
        "current": current.as_dict(),
        "longest": longest.as_dict(),
        "score_counts": {code_: sum(1 for row in rows if row["stage"] == code_)
                         for code_ in sorted({row["stage"] for row in rows})},
    }
