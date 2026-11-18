"""Point-in-time Wyckoff price-action observations, not phases or trade signals.

Input: ascending, date-indexed OHLCV on a consistent price basis (QFQ expected).
No adjustment or volume/intent inference occurs here. Every event retains the
box edges known on its observation date; subsequent bars only resolve candidates.
"""
from __future__ import annotations

import pandas as pd

from app.stage_classify import prepare_bars

WINDOW = 60
MIN_PRIOR = 40
# Only user-approved gates differ from the original structural triggers.
# A threshold is inclusive; the first comparison remains strictly across the box edge.
EDGE_DEPTH = {"Spring": 0.005, "UT": 0.002, "SOS": 0.002,
              "SOW": 0.005, "LPS": 0.002, "LPSY": 0.002}


def _passes_event_gate(kind: str, box: dict, row: pd.Series, prior: pd.DataFrame) -> bool:
    """Apply approved edge and volume gates on effective QFQ bars, not future data."""
    previous_median = float(prior["volume"].iloc[-20:].median())
    volume = float(row["volume"])
    if not previous_median > 0 or not volume >= previous_median:
        return False
    if kind == "Spring":
        return float(row["low"]) <= box["lower"] * (1 - EDGE_DEPTH[kind])
    if kind == "UT":
        return float(row["high"]) >= box["upper"] * (1 + EDGE_DEPTH[kind])
    if kind in ("SOS", "LPS"):
        return float(row["close"]) >= box["upper"] * (1 + EDGE_DEPTH[kind])
    return float(row["close"]) <= box["lower"] * (1 - EDGE_DEPTH[kind])


def _day(index: object) -> str:
    return str(index.date()) if hasattr(index, "date") else str(index)


def _box(previous: pd.DataFrame) -> dict:
    """Prior-only robust swing envelope; 10th low/90th high reject one-off wicks."""
    sample = previous.iloc[-WINDOW:]
    return {"lower": float(sample["low"].quantile(0.10)),
            "upper": float(sample["high"].quantile(0.90)),
            "lookback_bars": len(sample), "through_date": _day(sample.index[-1]),
            "method": "prior_60_high_q90_low_q10"}


def _event(kind: str, day: str, box: dict, row: pd.Series, prior: pd.DataFrame) -> dict:
    boundary = box["lower"] if kind in ("Spring", "SOW", "LPSY") else box["upper"]
    prior_volume = float(prior["volume"].iloc[-20:].median())
    volume = float(row["volume"])
    return {"type": kind, "status": "candidate", "date": day,
            "confirmation_date": None,
            "evidence": {"boundary": boundary, "box_lower": box["lower"],
                         "box_upper": box["upper"], "box_through_date": box["through_date"],
                         "high": float(row["high"]), "low": float(row["low"]),
                         "close": float(row["close"]), "volume": volume,
                         "prior_volume_median_20": prior_volume,
                         "volume_ratio_20": volume / prior_volume if prior_volume > 0 else None},
            "invalidated_by": None}


def _resolve(event: dict, row: pd.Series, day: str) -> None:
    """Resolve on later bars only; never rewrite an event's original evidence."""
    if event["status"] == "invalidated" or event["date"] == day:
        return
    close = float(row["close"])
    boundary = event["evidence"]["boundary"]
    kind = event["type"]
    failed = close < boundary if kind in ("Spring", "SOS", "LPS") else close > boundary
    if failed:
        event["status"] = "invalidated"
        event["invalidated_by"] = {"date": day, "close": close, "reason": "closed_across_frozen_boundary"}
    elif event["status"] == "candidate":
        stronger_close = close > event["evidence"]["close"] if kind in ("Spring", "SOS", "LPS") else close < event["evidence"]["close"]
        if stronger_close:
            event["status"] = "confirmed"
            event["confirmation_date"] = day


def clean_wyckoff_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Use precisely the observer's traded-bar validation for chart exports."""
    clean = prepare_bars(bars)
    if len(clean):
        values = clean[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        valid = values.notna().all(axis=1) & (values["open"] > 0) & (values["volume"] > 0)
        valid &= (values["high"] >= values[["open", "close", "low"]].max(axis=1))
        valid &= (values["low"] <= values[["open", "close", "high"]].min(axis=1))
        clean = clean.loc[valid].sort_index()
    return clean


def observe_wyckoff(bars: pd.DataFrame) -> dict:
    """Observe Spring/UT, SOS/SOW and post-breakout LPS/LPSY causally.

    ``ok=False`` means fewer than 40 *prior traded* bars (or invalid input).
    ``current`` is only an event observed on the as-of bar, otherwise None;
    historic events can change candidate status only on subsequent observations.
    No phases, predictive score, or buy/sell signal are returned.
    """
    if not isinstance(bars, pd.DataFrame):
        raise TypeError("bars must be a pandas DataFrame")
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        return {"ok": False, "as_of_date": _day(bars.index[-1]) if len(bars) else None,
                "price_basis": "input (QFQ expected)", "box": None, "trend": None,
                "events": [], "current": None, "reason": "missing_columns: " + ", ".join(sorted(missing))}
    clean = clean_wyckoff_bars(bars)
    as_of = _day(clean.index[-1]) if len(clean) else None
    result = {"ok": False, "as_of_date": as_of, "price_basis": "input (QFQ expected)",
              "box": None, "trend": None, "events": [], "current": None}
    if len(clean) <= MIN_PRIOR:
        result["reason"] = f"insufficient_traded_bars: need {MIN_PRIOR} prior bars; have {max(0, len(clean)-1)}"
        return result
    events = result["events"]
    active_breakout = None
    box = None
    for i in range(MIN_PRIOR, len(clean)):
        prior = clean.iloc[:i]
        row = clean.iloc[i]
        date = _day(clean.index[i])
        box = _box(prior)
        for event in events:
            _resolve(event, row, date)
        if active_breakout is not None and active_breakout["status"] == "invalidated":
            active_breakout = None
        upper, lower = box["upper"], box["lower"]
        high, low, close = (float(row[x]) for x in ("high", "low", "close"))
        old_close = float(prior.iloc[-1]["close"])
        kind = None
        # Retests use the original breakout's frozen edge, not a rolling box.
        if active_breakout is not None and active_breakout["status"] == "confirmed":
            edge = active_breakout["evidence"]["boundary"]
            if active_breakout["type"] == "SOS" and low <= edge <= close < old_close:
                kind = "LPS"
            elif active_breakout["type"] == "SOW" and high >= edge >= close > old_close:
                kind = "LPSY"
            if kind:
                frozen = active_breakout["evidence"]
                event_box = {"lower": frozen["box_lower"], "upper": frozen["box_upper"],
                             "through_date": frozen["box_through_date"]}
                if _passes_event_gate(kind, event_box, row, prior):
                    event = _event(kind, date, event_box, row, prior)
                    events.append(event)
                    active_breakout = None  # first *qualifying* retest consumes this parent
                    continue
                kind = None
        if lower < close < upper:
            if low < lower and high <= upper:
                kind = "Spring"
            elif high > upper and low >= lower:
                kind = "UT"
        elif close > upper and old_close <= upper:
            kind = "SOS"
        elif close < lower and old_close >= lower:
            kind = "SOW"
        if kind and _passes_event_gate(kind, box, row, prior):
            event = _event(kind, date, box, row, prior)
            events.append(event)
            if kind in ("SOS", "SOW"):
                active_breakout = event
    last = clean.iloc[-1]
    first_close = float(clean.iloc[-20]["close"]) if len(clean) >= 20 else None
    change = float(last["close"]) / first_close - 1 if first_close else None
    result.update(ok=True, box=box,
                  trend={"change_20_traded_bars": change,
                         "direction": "rising" if change > 0 else "falling" if change < 0 else "unchanged"},
                  current=next((e for e in reversed(events) if e["date"] == as_of), None))
    return result
