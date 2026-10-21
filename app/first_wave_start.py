"""Deterministic, auditable first-wave strength-start event scanner.

Signals are calculated exclusively from front-adjusted OHLCV.  The caller must
supply bars truncated at ``as_of_date``; this module never looks ahead.
"""
from __future__ import annotations

from typing import Any
import math
import pandas as pd


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume", "amount"}


def _f(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(float(value) * 2) / 2


def classify_event(*, pressure: float, closes: list[float]) -> str:
    """Classify an already-frozen B event without mutating its B date."""
    if any(float(close) < pressure * 0.985 for close in closes[1:]):
        return "FAILED_BREAKOUT"
    if closes and float(closes[-1]) > pressure * 1.10:
        return "EXTENDED"
    index = len(closes) - 1
    return ("FIRST_BREAKOUT", "EARLY_CONFIRMATION", "EARLY_CONFIRMATION", "EARLY_CONFIRMATION")[min(index, 3)] if index <= 3 else "LATE_ENTRY"


def _platform_record(frame: pd.DataFrame) -> dict[str, Any] | None:
    highs, lows, closes = frame["high"].astype(float), frame["low"].astype(float), frame["close"].astype(float)
    raw_high, raw_low = float(highs.max()), float(lows.min())
    hi_idx = highs.idxmax()
    row = frame.loc[hi_idx]
    candle_range = float(row["high"] - row["low"])
    upper_shadow = float(row["high"] - max(row["open"], row["close"])) / candle_range if candle_range > 0 else 0.0
    second_high = float(highs.drop(index=hi_idx).max()) if len(highs) > 1 else raw_high
    isolated = upper_shadow >= 0.60 and raw_high >= second_high * 1.05
    effective_high = float(closes.max()) if isolated else raw_high
    width = (effective_high - raw_low) / raw_low * 100 if raw_low > 0 else math.inf
    if width > 20:
        return None
    split = len(frame) // 2
    left, right = frame.iloc[:split], frame.iloc[split:]
    def width_of(part: pd.DataFrame) -> float:
        low = float(part["low"].min()); high = float(part["high"].max())
        return (high - low) / low if low > 0 else math.inf
    initial, latter = width_of(left), width_of(right)
    if initial == 0:
        contraction = 1.0 if latter == 0 else math.inf
    else:
        contraction = latter / initial
    return {"platform_start": str(pd.Timestamp(frame.iloc[0]["date"]).date()), "platform_end": str(pd.Timestamp(frame.iloc[-1]["date"]).date()),
            "platform_days": len(frame), "raw_low": raw_low, "effective_high": effective_high, "pressure": effective_high,
            "pressure_basis": "highest_close_after_isolated_upper_shadow" if isolated else "platform_high", "width_pct": round(width, 4),
            "contraction_ratio": contraction, "outlier_upper_shadow_pct": round(upper_shadow * 100, 2) if isolated else None}


def choose_platform(candidate_bars: pd.DataFrame) -> dict[str, Any] | None:
    """Select the shortest valid 8–30-bar platform ending at B-1."""
    if not REQUIRED_COLUMNS <= set(candidate_bars.columns):
        raise ValueError("candidate bars lack required OHLCV columns")
    bars = candidate_bars.sort_values("date").reset_index(drop=True)
    choices = []
    for length in range(8, min(30, len(bars)) + 1):
        record = _platform_record(bars.iloc[-length:])
        if record:
            choices.append(record)
    return choices[0] if choices else None


def _score_platform(p: dict[str, Any]) -> tuple[float, dict[str, float], list[str]]:
    d, width, ratio = p["platform_days"], p["width_pct"], p["contraction_ratio"]
    length = 1 if d <= 9 else 2 if d <= 14 else 3
    width_score = 3 if width <= 8 else 2 if width <= 14 else 1
    convergence = 4 if ratio <= .75 else 3 if ratio <= .9 else 2 if ratio <= 1.05 else 1 if ratio <= 1.2 else 0
    tags = ["platform_volatility_expanding"] if convergence == 0 else []
    return float(length + width_score + convergence), {"platform_length": float(length), "platform_width": float(width_score), "platform_convergence": float(convergence)}, tags


def _prior_wave(frame: pd.DataFrame, platform_start: int) -> tuple[bool, float | None, float | None]:
    before = frame.iloc[max(0, platform_start - 120):platform_start]
    if len(before) < 60:
        return False, None, None
    best: tuple[int, float, float] | None = None
    closes = before["close"].astype(float).tolist()
    for end in range(14, len(closes)):
        for days in range(15, 31):
            start = end - days
            if start < 0: continue
            gain = closes[end] / closes[start] - 1
            if gain >= .30:
                candidate = (end, gain, max(closes[start:end + 1]))
                if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and closes[end] > closes[best[0]]): best = candidate
    return (best is not None, best[1] * 100 if best else None, best[2] if best else None)


def scan_symbol(bars: pd.DataFrame, *, market: str, symbol: str, stock_name: str, as_of_date: str) -> dict[str, Any] | None:
    """Return one frozen current event or None.  No current/future data fallback."""
    if not REQUIRED_COLUMNS <= set(bars.columns): raise ValueError("bars lack required OHLCV columns")
    data = bars.copy(); data["date"] = pd.to_datetime(data["date"]); data = data[data["date"] <= pd.Timestamp(as_of_date)].sort_values("date").reset_index(drop=True)
    if len(data) < 69 or data["date"].duplicated().any() or (data[["open","high","low","close","volume","amount"]].isna().any().any()): return None
    # candidate B must be in the final four visible bars; first valid breakout after its chosen platform is frozen.
    event = None
    for bidx in range(max(68, len(data) - 4), len(data)):
        platform = choose_platform(data.iloc[:bidx])
        if not platform: continue
        if float(data.iloc[bidx]["close"]) >= platform["pressure"] * 1.01:
            event = (bidx, platform); break
    if not event: return None
    bidx, p = event; b = data.iloc[bidx]; observed = data.iloc[bidx:]
    state = classify_event(pressure=p["pressure"], closes=observed["close"].astype(float).tolist())
    if state in {"FAILED_BREAKOUT", "EXTENDED", "LATE_ENTRY"}: return None
    if len(data.iloc[-10:]) != 10 or float(data.iloc[-10:]["amount"].mean()) < 50_000_000: return None
    before_start = bidx - p["platform_days"]
    has_wave, wave_gain, wave_high = _prior_wave(data, before_start)
    background_count = before_start
    tags: list[str] = []
    classification = "FIRST_WAVE_ELIGIBLE"
    platform_min_close = float(data.iloc[before_start:bidx]["close"].min())
    if has_wave and wave_high and (wave_high - platform_min_close) / wave_high <= .10:
        return None  # CONTINUATION: hard exclusion from first-wave lists
    if has_wave:
        classification = "REBASE_REVIEW"; tags.append("prior_wave_rebase_review")
    elif background_count < 120:
        classification = "FIRST_WAVE_WATCH"; tags.append("background_under_120_days")
    structure, structure_detail, structure_tags = _score_platform(p); tags.extend(structure_tags)
    breakthrough_pct = (float(b["close"]) / p["pressure"] - 1) * 100
    break_score = 6 if breakthrough_pct < 1.5 else 10 if breakthrough_pct < 3 else 8 if breakthrough_pct < 5 else 4
    current_dist = (float(observed.iloc[-1]["close"]) / p["pressure"] - 1) * 100
    position = 6 if current_dist < 0 else 10 if current_dist < 3 else 8 if current_dist < 5 else 5 if current_dist < 8 else 2
    structure_total = _round(structure + break_score + position)
    prior10 = data.iloc[max(0, bidx - 10):bidx]
    up = prior10[prior10["close"].astype(float).diff().fillna(0) > 0]["volume"].astype(float); down = prior10.drop(up.index)["volume"].astype(float)
    ratio = float(up.mean() / down.mean()) if len(up) >= 2 and len(down) >= 2 and float(down.mean()) else None
    flow = 7.5 if ratio is None else 15 if ratio >= 1.5 else 12 if ratio >= 1.25 else 9 if ratio >= 1 else 5 if ratio >= .8 else 0
    bvol = float(b["volume"] / data.iloc[bidx-5:bidx]["volume"].astype(float).mean())
    bvol_score = 0 if bvol < .8 else 3 if bvol < 1 else 6 if bvol < 1.3 else 10 if bvol <= 2.5 else 7 if bvol <= 3 else 3
    if bvol > 3: tags.append("extreme_breakout_volume")
    centroid = 0.0
    if bidx >= 10:
        for col in ("close", "low"):
            change = (float(data.iloc[bidx-5:bidx][col].mean()) / float(data.iloc[bidx-10:bidx-5][col].mean()) - 1) * 100
            centroid += 5 if change >= 3 else 4 if change >= 1.5 else 3 if change >= .5 else 2 if change >= 0 else 0
    volume_total = _round(flow + bvol_score + centroid)
    rng = float(b["high"] - b["low"])
    if rng <= 0: return None
    close_pos = (float(b["close"] - b["low"]) / rng); upper = float(b["high"] - max(b["open"],b["close"])) / rng; body = abs(float(b["close"] - b["open"])) / rng
    kscore = (6 if close_pos >= .8 else 4 if close_pos >= .7 else 2 if close_pos >= .6 else 0) + (3 if upper <= .2 else 2 if upper <= .35 else 1 if upper <= .5 else 0) + (3 if body >= .6 else 2 if body >= .4 else 1 if body >= .2 else 0)
    fresh = [12, 10, 8, 6][len(observed)-1]
    acceptance = 5.5 if len(observed) == 1 else 0.0
    start_total = _round(fresh + kscore + acceptance)
    total = _round(structure_total + volume_total + start_total)
    return {"market": market, "symbol": str(symbol).zfill(6), "stock_name": stock_name, "as_of_date": as_of_date, "classification": classification, "stage": state,
            "b_date": str(pd.Timestamp(b["date"]).date()), "pressure": round(p["pressure"], 4), "current_close": round(float(observed.iloc[-1]["close"]), 4), "distance_to_pressure_pct": round(current_dist, 4),
            "platform": p, "structure_score": structure_total, "volume_price_score": volume_total, "start_score": start_total, "total_score": total,
            "acceptance_score": acceptance, "risk_tags": tags, "evidence": {"breakthrough_pct": round(breakthrough_pct,4), "prior_wave_pct": wave_gain, "average_amount_10d": float(data.iloc[-10:]["amount"].mean()), "breakout_volume_ratio": round(bvol,4), "up_down_volume_ratio": round(ratio,4) if ratio is not None else None, "close_position_ratio": round(close_pos,4), "upper_shadow_ratio": round(upper,4), "body_ratio": round(body,4), "structure": structure_detail}}


def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    stages = {"FIRST_BREAKOUT": 0, "EARLY_CONFIRMATION": 1}
    return (-float(row.get("total_score") or 0), stages.get(row.get("stage"), 9), abs(float(row.get("distance_to_pressure_pct") or 0)), str(row.get("market")), str(row.get("symbol")))
