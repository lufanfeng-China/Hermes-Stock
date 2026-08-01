"""Pure concept-temperature calculations using Tongdaxin concept mappings and QFQ bars."""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

import pandas as pd


def parse_tdx_concept_mapping(text: str) -> list[dict[str, str]]:
    """Parse the GB18030 Tongdaxin four-column concept mapping, preserving first occurrence."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        values = [part.strip() for part in line.split("\t")]
        if len(values) < 4:
            continue
        concept_code, concept_name, symbol, stock_name = values[:4]
        if not concept_code or not concept_name or len(symbol) != 6 or not symbol.isdigit():
            continue
        key = (concept_code, symbol)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"concept_code": concept_code, "concept_name": concept_name, "symbol": symbol, "stock_name": stock_name})
    return rows


def _percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    return sum(1 for current in values if current <= value) / len(values)


def _return_and_volume(frame: pd.DataFrame, window: int) -> tuple[float, float, float] | None:
    required = max(window + 1, 25)
    if frame is None or len(frame) < required or "close" not in frame:
        return None
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < required or float(close.iloc[-window - 1]) <= 0:
        return None
    return_pct = (float(close.iloc[-1]) / float(close.iloc[-window - 1]) - 1.0) * 100.0
    volume = pd.to_numeric(frame.get("volume"), errors="coerce")
    if volume is None or len(volume.dropna()) < 25:
        volume_ratio = 1.0
    else:
        latest = float(volume.iloc[-5:].mean())
        base = float(volume.iloc[-25:-5].mean())
        volume_ratio = latest / base if base > 0 else 1.0
    return return_pct, float(close.iloc[-1]), volume_ratio


def _temperature(score_percentile: float, median_return: float, breadth: float, excess: float, strong: float, active: float, valid_count: int, min_members: int) -> tuple[int | None, str]:
    if valid_count < min_members:
        return None, "数据不足"
    if score_percentile <= .20 and median_return <= 0 and breadth < 35:
        return 0, "冰点"
    if score_percentile <= .40:
        return 1, "偏冷"
    if score_percentile <= .60:
        return 2, "中性偏弱"
    if score_percentile <= .80 or median_return <= 0 or breadth < 55 or excess <= 0:
        return 3, "升温"
    if score_percentile >= .95 and median_return > 0 and breadth >= 75 and excess > 0 and strong >= 30 and active >= 20 and valid_count >= max(15, min_members):
        return 5, "极热"
    return 4, "热门"


def attach_temperature_streaks(current_rows: list[dict[str, Any]], history_newest_first: list[dict[str, int | None]]) -> None:
    """Add consecutive trading-day streaks for the row's current temperature.

    Each history item maps concept code to its temperature for one trading day,
    ordered from the current day backwards. A missing/insufficient-data state
    deliberately has no numerical streak.
    """
    for row in current_rows:
        current = row.get("temperature")
        if current is None:
            row["temperature_streak_days"] = None
            continue
        days = 0
        for levels in history_newest_first:
            if levels.get(row["concept_code"]) != current:
                break
            days += 1
        row["temperature_streak_days"] = days


def build_temperature_rows(mapping: list[dict[str, str]], frames: dict[str, pd.DataFrame], window: int = 10, min_members: int = 10, as_of: pd.Timestamp | None = None, include_members: bool = True) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Build concept heat rows at ``as_of`` (or current frame end) from QFQ bars."""
    if as_of is not None:
        frames = {
            symbol: clipped
            for symbol, frame in frames.items()
            if not (clipped := frame.loc[frame.index <= as_of]).empty and clipped.index.max() == as_of
        }

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    metrics = {symbol: _return_and_volume(frame, window) for symbol, frame in frames.items()}
    all_member_returns: list[float] = []
    for entry in mapping:
        metric = metrics.get(entry["symbol"])
        if metric is None:
            continue
        ret, close, volume_ratio = metric
        enriched = {**entry, "return_pct": round(ret, 2), "latest_close": round(close, 2), "volume_ratio_5d_20d": round(volume_ratio, 2)}
        groups[entry["concept_code"]].append(enriched)
        all_member_returns.append(ret)

    market_median = float(median(all_member_returns)) if all_member_returns else 0.0
    strong_cutoff = float(pd.Series(all_member_returns).quantile(.75)) if all_member_returns else 0.0
    drafts: list[dict[str, Any]] = []
    members_out: dict[str, list[dict[str, Any]]] = {}
    for concept_code, members in groups.items():
        members.sort(key=lambda row: (-row["return_pct"], row["symbol"]))
        if include_members:
            members_out[concept_code] = members
        returns = [row["return_pct"] for row in members]
        med = float(median(returns))
        breadth = sum(value > 0 for value in returns) / len(returns) * 100
        strong = sum(value > strong_cutoff for value in returns) / len(returns) * 100
        active = sum(row["volume_ratio_5d_20d"] > 1.20 for row in members) / len(members) * 100
        drafts.append({"concept_code": concept_code, "concept_name": members[0]["concept_name"], "member_count": len(members), "median_return_pct": med, "breadth_pct": breadth, "excess_return_pct": med - market_median, "strong_stock_pct": strong, "active_volume_pct": active})

    for draft in drafts:
        scores = []
        for key in ("median_return_pct", "breadth_pct", "excess_return_pct", "strong_stock_pct", "active_volume_pct"):
            values = [float(row[key]) for row in drafts]
            scores.append(_percentile(values, float(draft[key])))
        draft["heat_score"] = round((scores[0] * 30 + scores[1] * 25 + scores[2] * 20 + scores[3] * 15 + scores[4] * 10), 1)
    score_values = [row["heat_score"] for row in drafts]
    for row in drafts:
        temp, label = _temperature(_percentile(score_values, row["heat_score"]), row["median_return_pct"], row["breadth_pct"], row["excess_return_pct"], row["strong_stock_pct"], row["active_volume_pct"], row["member_count"], min_members)
        row.update({"temperature": temp, "temperature_label": label, "window": window})
        for field in ("median_return_pct", "breadth_pct", "excess_return_pct", "strong_stock_pct", "active_volume_pct"):
            row[field] = round(float(row[field]), 2)
    drafts.sort(key=lambda row: (row["temperature"] is None, -(row["temperature"] if row["temperature"] is not None else -1), -row["heat_score"], row["concept_name"]))
    return drafts, members_out
