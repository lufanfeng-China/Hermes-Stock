"""Vectorised bar-by-bar A/B/C/D labels.

Per-symbol implementation (arrays are ~3.5k bars): rolling windows come from
pandas, and the breakout/pullback state is a single O(n) pass, so the meaning
stays identical to `app.stage_regime.classify_regime`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.stage_classify import prepare_bars
from app.stage_regime import (
    BREAKOUT_LOOKBACK,
    BREAKOUT_MULT,
    BREAKOUT_RECENT,
    PULLBACK_TOL,
    SCORE_STRONG,
    SELL_DAYS_MIN,
    D_MIN_BIAS20,
    D_MIN_BOX_POSITION,
    SELL_WINDOW,
    STALL_VOL_SHRINK,
    STAGE_LABELS,
    VOL_LONG,
    VOL_SHORT,
    WINDOW,
)

ITEM_KEYS = ("低点不创新低", "量能线上", "红肥绿瘦", "放量突破", "缩量回踩守住", "价在MA20上")


def _roll(values: np.ndarray, window: int, how: str) -> np.ndarray:
    roller = pd.Series(values).rolling(window, min_periods=window)
    return getattr(roller, how)().to_numpy(dtype=float)


def classify_regime_series(bars: pd.DataFrame) -> pd.DataFrame:
    work = prepare_bars(bars)
    n = len(work)
    close = work["close"].to_numpy(dtype=float)
    high = work["high"].to_numpy(dtype=float)
    low = work["low"].to_numpy(dtype=float)
    vol = work["volume"].to_numpy(dtype=float)

    ma20 = _roll(close, 20, "mean")
    vol_ma5 = _roll(vol, VOL_SHORT, "mean")
    vol_ma60 = _roll(vol, VOL_LONG, "mean")
    vol_ma20 = _roll(vol, 20, "mean")
    box_high = _roll(high, WINDOW, "max")
    box_low = _roll(low, WINDOW, "min")
    low_last_20 = _roll(low, 20, "min")
    prior_low40 = pd.Series(low).rolling(WINDOW - 20, min_periods=WINDOW - 20).min().shift(20).to_numpy(dtype=float)

    items: dict[str, np.ndarray] = {}
    items["低点不创新低"] = low_last_20 >= prior_low40 * (1 - 1e-9)

    prev_vol_ma5 = np.concatenate(([np.nan], vol_ma5[:-1]))
    items["量能线上"] = (vol_ma5 > vol_ma60) | ((prev_vol_ma5 <= vol_ma60) & (vol_ma5 > vol_ma60))

    rise = np.concatenate(([0.0], np.diff(close)))
    # 60 根窗口里只有 59 个涨跌差（首根没有前值），用 WINDOW-1 才与标量一致
    span = WINDOW - 1
    up_sum = _roll(np.where(rise > 0, vol, 0.0), span, "sum")
    up_cnt = _roll((rise > 0).astype(float), span, "sum")
    down_sum = _roll(np.where(rise < 0, vol, 0.0), span, "sum")
    down_cnt = _roll((rise < 0).astype(float), span, "sum")
    with np.errstate(invalid="ignore", divide="ignore"):
        up_mean = up_sum / up_cnt
        down_mean = down_sum / down_cnt
    both = (up_cnt > 0) & (down_cnt > 0)
    items["红肥绿瘦"] = np.where(both, up_mean > down_mean, up_cnt > 0)

    prior_high20 = pd.Series(high).rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK).max().shift(1).to_numpy(dtype=float)
    prior_vol20 = pd.Series(vol_ma20).shift(1).to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        breakout = (close > prior_high20) & (vol >= BREAKOUT_MULT * prior_vol20)
    breakout = np.nan_to_num(breakout, nan=0.0).astype(bool)
    # 与标量一致：条目看的是「窗口内出现过放量突破」，不是「今天是否突破」
    seen_breakout = _roll(breakout.astype(float), WINDOW, "sum")
    items["放量突破"] = np.nan_to_num(seen_breakout, nan=0.0) > 0

    holds = np.zeros(n, dtype=bool)
    fresh = np.zeros(n, dtype=bool)
    last_break = -1
    level = np.nan
    min_since = np.inf
    vol_sum = 0.0
    vol_cnt = 0
    for index in range(n):
        if last_break >= 0 and index > last_break:
            min_since = min(min_since, close[index])
            vol_sum += vol[index]
            vol_cnt += 1
            retreated = min_since < close[last_break] * 0.99
            held = min_since >= level * (1 - PULLBACK_TOL)
            shrank = (vol_sum / vol_cnt) < vol[last_break] if vol_cnt else False
            holds[index] = bool(retreated and held and shrank)
            fresh[index] = bool(index - last_break <= BREAKOUT_RECENT)
        if breakout[index]:
            last_break = index
            level = float(prior_high20[index])
            min_since = np.inf
            vol_sum = 0.0
            vol_cnt = 0
    items["缩量回踩守住"] = holds
    items["价在MA20上"] = close > ma20

    at_high = close >= _roll(close, WINDOW, "max") * 0.999
    stalling = at_high & (vol_ma5 < vol_ma20 * STALL_VOL_SHRINK)

    fell = np.concatenate(([False], close[1:] < close[:-1]))
    heavier = np.concatenate(([False], vol[1:] > vol[:-1]))
    sell_days = _roll((fell & heavier).astype(float), SELL_WINDOW, "sum")
    selling_cluster = np.nan_to_num(sell_days, nan=0.0) >= SELL_DAYS_MIN

    score = sum(items[key].astype(int) for key in ITEM_KEYS) - stalling.astype(int) - selling_cluster.astype(int)

    valid = np.zeros(n, dtype=bool)
    valid[WINDOW - 1:] = True
    valid &= np.isfinite(ma20) & np.isfinite(vol_ma60)

    stage = np.full(n, "", dtype=object)
    reason = np.full(n, "", dtype=object)

    # 「高位」必须是真的高位：箱体位置 >= 60%，或价格已显著远离 MA20（乖离 >= 5%）。
    # 否则下跌中继里的抛售日会被误判成「高位派发」。
    box_position = np.where(box_high > box_low, (close - box_low) / (box_high - box_low), 0.5)
    with np.errstate(invalid="ignore", divide="ignore"):
        bias20 = (close - ma20) / ma20
    high_zone = (box_position >= D_MIN_BOX_POSITION) | (bias20 >= D_MIN_BIAS20)
    distribution = (stalling | selling_cluster) & high_zone
    strong = (score >= SCORE_STRONG) & (close > ma20) & items["红肥绿瘦"] & ~stalling & ~selling_cluster

    stage[distribution] = "D"
    reason[distribution] = np.where(stalling[distribution], "放量滞涨", "抛售日密集")

    remaining = valid & (stage == "")
    pick = remaining & holds & fresh
    stage[pick] = "B"
    reason[pick] = "放量突破后缩量回踩守住（启动确认）"

    remaining = valid & (stage == "")
    pick = remaining & strong
    stage[pick] = "C"
    reason[pick] = "得分达标，多头量价配合"

    remaining = valid & (stage == "")
    pick = remaining & holds
    stage[pick] = "C"
    reason[pick] = "早前突破已确认，趋势延续中"

    remaining = valid & (stage == "")
    pick = remaining & items["低点不创新低"]
    stage[pick] = "A"
    reason[pick] = "低点不再创新低，箱体内运行"

    remaining = valid & (stage == "")
    stage[remaining] = "A"
    reason[remaining] = "低点仍在创新低，按下跌中继对待"

    def masked(values: np.ndarray) -> np.ndarray:
        return np.where(valid, values, None)

    frame = pd.DataFrame({
        "trading_day": [str(day)[:10] for day in work.index],
        "close": masked(np.round(close, 3)),
        "valid": valid,
        "stage": masked(stage),
        "stage_label": masked(np.array([STAGE_LABELS.get(code, "") for code in stage], dtype=object)),
        "score": masked(score),
        "reason": masked(reason),
        "ma20": masked(np.round(ma20, 3)),
        "vol_ma5": masked(np.round(vol_ma5, 1)),
        "vol_ma60": masked(np.round(vol_ma60, 1)),
        "box_high": masked(np.round(box_high, 3)),
        "box_low": masked(np.round(box_low, 3)),
        "box_mid": masked(np.round((box_high + box_low) / 2, 3)),
        "box_position": masked(np.round(box_position, 4)),
        "sell_days_15": masked(np.nan_to_num(sell_days, nan=0.0)),
    })
    for key in ITEM_KEYS:
        frame[key] = masked(items[key].astype(bool))
    frame["放量滞涨"] = masked(stalling)
    frame["抛售日密集"] = masked(selling_cluster)
    return frame
