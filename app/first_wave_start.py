"""Deterministic five-condition first-wave scanner for QFQ daily bars.

The caller must supply front-adjusted close/volume; no raw-price fallback is
performed. ``scan_symbol`` truncates at ``as_of_date`` and requires its exact bar.
Platform/event helpers are retained only for legacy research consumers.
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
    """Evaluate the five AND conditions on caller-supplied QFQ daily bars only."""
    if not {"date", "close", "volume"} <= set(bars.columns):
        raise ValueError("bars lack required date/close/volume columns")
    data = bars.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if data["date"].isna().any():
        return None
    data = data[data["date"] <= pd.Timestamp(as_of_date)].sort_values("date").reset_index(drop=True)
    if (len(data) < 60 or data.iloc[-1]["date"] != pd.Timestamp(as_of_date)
            or data["date"].duplicated().any()):
        return None
    # Only the 60 price bars and 31 volume bars required by the five rules
    # participate in validity checks; older suspension/zero-volume rows are not
    # an extra exclusion condition.
    data = data.iloc[-60:].reset_index(drop=True)
    close = pd.to_numeric(data["close"], errors="coerce").astype(float)
    volume = pd.to_numeric(data["volume"].iloc[-31:], errors="coerce").astype(float)
    if any(not math.isfinite(value) or value <= 0 for series in (close, volume) for value in series):
        return None
    prior_return = close.iloc[-2] / close.iloc[-32] - 1
    averages = {days: float(close.iloc[-days:].mean()) for days in (10, 20, 30, 60)}
    prior_volume = volume.iloc[-31:-1]
    minimum, maximum = float(prior_volume.min()), float(prior_volume.max())
    current_volume = float(volume.iloc[-1])
    day_return = close.iloc[-1] / close.iloc[-2] - 1
    # Inclusive decimal percentage boundaries tolerate only binary-float noise;
    # MA ordering remains strictly greater with no tolerance or rounding.
    prior_in_range = (prior_return >= 0.10 or math.isclose(prior_return, 0.10, rel_tol=0, abs_tol=1e-14)) and (
        prior_return <= 0.50 or math.isclose(prior_return, 0.50, rel_tol=0, abs_tol=1e-14))
    day_at_least_five = day_return >= 0.05 or math.isclose(day_return, 0.05, rel_tol=0, abs_tol=1e-14)
    if not (prior_in_range
            and averages[10] > averages[20] > averages[30] > averages[60]
            and current_volume >= 4 * minimum
            and day_at_least_five
            and maximum / minimum <= 2.5):
        return None
    return {"market": market, "symbol": str(symbol).zfill(6), "stock_name": stock_name,
            "as_of_date": as_of_date, "signal_date": str(data.iloc[-1]["date"].date()),
            "current_close": float(close.iloc[-1]), "classification": "FIRST_WAVE_ELIGIBLE",
            "evidence": {"prior_30d_return_pct": float(prior_return * 100),
                         **{f"ma{days}": value for days, value in averages.items()},
                         "prior_30d_min_volume": minimum, "prior_30d_max_volume": maximum,
                         "current_volume": current_volume, "volume_multiple": current_volume / minimum,
                         "day_return_pct": float(day_return * 100), "prior_volume_spread": maximum / minimum}}


def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Stable deterministic identity ordering; no score or legacy stage gates."""
    return (str(row.get("market")), str(row.get("symbol")))
