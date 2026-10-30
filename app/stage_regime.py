"""A/B/C/D regime classifier: 均线定位置、量能定性质、结构定边界.

Four stages replace the earlier 13-state model:
  A 底部构筑 / 下跌中继   B 突破启动确认   C 主升推进   D 高位派发

Six positive items + two penalties, all read from one trailing window of
WINDOW=60 trading days:

  价格均线   MA20                 → 位置（线上/线下）
  均量线     vol_ma5 / vol_ma60   → 性质（扩张/休眠/退潮）
  价格结构   60 根最高/最低/中轨  → 边界（箱体位置、是否创新低）

There is exactly ONE implementation: `app.stage_regime_series.classify_regime_series`
computes every bar, and `classify_regime` returns its last valid row. Keeping a
second hand-written scalar path previously drifted from the vectorised one on
1 of 120 sampled (symbol, bar) points, so the scalar is now a thin reader.

Deliberate deviations from the original framework text (documented, not silent):
  * 突破 is measured against the *previous* 20 bars' high, because "close above
    the 60-bar high" can never be true when that high includes today's bar.
  * 回踩 must actually retreat ≥1% before 守住 counts; otherwise every older
    breakout would keep scoring.
  * 低点不创新低 compares the last 20 bars' low with the *previous* 40 bars'
    low, so a downtrend whose minimum sits in the last 20 bars is not mistaken
    for a bottom.
  * Stage precedence is D (派发) > B (刚确认的突破) > C (主升) > A.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.stage_classify import prepare_bars  # noqa: F401  (kept for callers/tests)

WINDOW = 60
VOL_SHORT = 5
VOL_LONG = 60
BREAKOUT_LOOKBACK = 20
BREAKOUT_MULT = 1.5
BREAKOUT_RECENT = 10
PULLBACK_TOL = 0.02
STALL_VOL_SHRINK = 0.9
SELL_WINDOW = 15
SELL_DAYS_MIN = 4
SCORE_STRONG = 4

STAGE_LABELS = {
    "A": "底部构筑/下跌中继",
    "B": "突破启动确认",
    "C": "主升推进",
    "D": "高位派发",
}


def classify_regime(bars: pd.DataFrame) -> dict[str, Any]:
    """Classify the current stage from the last 60 valid daily bars."""
    if not isinstance(bars, pd.DataFrame):
        raise TypeError("bars must be a DataFrame")

    from app.stage_regime_series import ITEM_KEYS, classify_regime_series

    frame = classify_regime_series(bars)
    if frame.empty:
        raise ValueError(f"need at least {WINDOW} valid bars")

    row = frame.iloc[-1]
    if not bool(row["valid"]):
        raise ValueError(f"need at least {WINDOW} valid bars")

    items = {key: bool(row[key]) for key in ITEM_KEYS}
    penalties = {"放量滞涨": bool(row["放量滞涨"]), "抛售日密集": bool(row["抛售日密集"])}
    stage = str(row["stage"])
    score = int(row["score"])
    reason = str(row["reason"])

    return {
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "score": score,
        "items": items,
        "penalties": penalties,
        "reason": reason,
        "detail": f"{STAGE_LABELS[stage]}：{reason}（得分{score}）",
        "evidence": {
            "close": round(float(row["close"]), 3) if "close" in row else None,
            "ma20": float(row["ma20"]),
            "vol_ma5": float(row["vol_ma5"]),
            "vol_ma60": float(row["vol_ma60"]),
            "box_high": float(row["box_high"]),
            "box_low": float(row["box_low"]),
            "box_mid": float(row["box_mid"]),
            "box_position": float(row["box_position"]),
            "sell_days_15": int(row["sell_days_15"]),
        },
        "window_bars": WINDOW,
        "price_basis": "tdx_export_qfq",
    }
