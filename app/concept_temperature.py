"""Pure concept-temperature calculations using Tongdaxin concept mappings and QFQ bars."""
from __future__ import annotations

from collections import defaultdict
from bisect import bisect_right
from statistics import median
from typing import Any

import numpy as np
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


def prepare_series(frames: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """把每只股票的日线压成 numpy 数组，避免逐日裁剪 DataFrame。

    只对「收盘价无缺失」的股票建快路径；含缺失的股票留给调用方走原慢路径，
    以保证与旧实现逐位一致。
    """
    prepared: dict[str, dict[str, Any]] = {}
    for symbol, frame in frames.items():
        if frame is None or "close" not in frame:
            continue
        closes = pd.to_numeric(frame["close"], errors="coerce")
        if closes.isna().any():
            continue
        volumes = pd.to_numeric(frame["volume"], errors="coerce") if "volume" in frame else None
        volume_array = volumes.to_numpy(dtype=float) if volumes is not None else None
        prepared[symbol] = {
            "dates": frame.index.values.astype("datetime64[ns]").view("int64"),
            "close": closes.to_numpy(dtype=float),
            "volume": volume_array,
            # 旧实现按「截至当时的有效成交量条数」判断，这里用累计计数复现同一口径
            "volume_valid_upto": (np.cumsum(~np.isnan(volume_array)).astype(np.int64)
                                  if volume_array is not None else None),
        }
    return prepared


def metric_from_series(prepared: dict[str, dict[str, Any]], symbol: str,
                       as_of_ns: int, window: int) -> tuple[float, float, float] | None:
    """等价于把 frame 裁到 as_of 后调用 _return_and_volume。"""
    entry = prepared.get(symbol)
    if entry is None:
        return None
    dates = entry["dates"]
    position = int(np.searchsorted(dates, as_of_ns))
    if position >= len(dates) or int(dates[position]) != as_of_ns:
        return None
    required = max(window + 1, 25)
    if position + 1 < required:
        return None
    close = entry["close"]
    base_close = close[position - window]
    if not base_close > 0:
        return None
    return_pct = (close[position] / base_close - 1.0) * 100.0
    volume = entry["volume"]
    valid_upto = entry["volume_valid_upto"]
    if volume is None or valid_upto is None or int(valid_upto[position]) < 25:
        volume_ratio = 1.0
    else:
        # 与 pandas 的 mean() 一致：跳过缺失值
        latest = float(np.nanmean(volume[position - 4:position + 1]))
        base = float(np.nanmean(volume[position - 24:position - 4]))
        volume_ratio = latest / base if base > 0 else 1.0
    return return_pct, float(close[position]), volume_ratio


def percentile_of(values: list[float], targets: list[float]) -> list[float]:
    """与 _percentile 同义（≤ target 的占比），但排序后二分，O(n log n)。"""
    if not values:
        return [0.0 for _ in targets]
    ordered = sorted(values)
    size = len(ordered)
    return [bisect_right(ordered, target) / size for target in targets]


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


TREND_LABELS = {"warming": "升温", "cooling": "退坡", "unknown": "无前值"}


def _previous_level(concept_code: str, history_newest_first: list[dict[str, int | None]],
                    current: int) -> tuple[int | None, int | None]:
    """最近一次“与当前不同”的温度，以及它距今多少个交易日。

    跳过缺数据的交易日；连续相同的当前温度不算“前温”——所以前温永远不会等于
    当前温度，也就不存在“持平”。整段历史都没有不同温度时返回 (None, None)。
    """
    for gap, levels in enumerate(history_newest_first[1:], start=1):
        level = levels.get(concept_code)
        if level is None or level == current:
            continue
        return level, gap
    return None, None


def attach_temperature_streaks(current_rows: list[dict[str, Any]], history_newest_first: list[dict[str, int | None]]) -> None:
    """Add consecutive trading-day streaks and the previous *different* level.

    history_newest_first 按今天向前排序，每项是 code → 温度。
    temperature_previous 是最近一次不等于当前温度的那一档（不是昨天那一档）。
    """
    for row in current_rows:
        current = row.get("temperature")
        if current is None:
            row["temperature_streak_days"] = None
            row["temperature_previous"] = None
            row["temperature_previous_gap_days"] = None
            row["temperature_change"] = None
            row["temperature_trend"] = "unknown"
            row["temperature_trend_label"] = "数据不足"
            continue

        days = 0
        for levels in history_newest_first:
            if levels.get(row["concept_code"]) != current:
                break
            days += 1
        row["temperature_streak_days"] = days

        previous, gap = _previous_level(row["concept_code"], history_newest_first, current)
        row["temperature_previous"] = previous
        row["temperature_previous_gap_days"] = gap
        if previous is None:
            row["temperature_change"] = None
            row["temperature_trend"] = "unknown"
            row["temperature_trend_label"] = "无前值"
        else:
            row["temperature_change"] = int(current) - int(previous)
            row["temperature_trend"] = "warming" if current > previous else "cooling"
            row["temperature_trend_label"] = TREND_LABELS[row["temperature_trend"]]



def _stock_name_map() -> dict[str, str]:
    """symbol → 股票名称。行业映射快照里 stock_name 为空，用它兜底。"""
    try:
        from app.search.index import _stock_name_lookup
    except Exception:
        return {}
    try:
        lookup = _stock_name_lookup()
    except Exception:
        return {}
    return {str(symbol): str(name) for (_market, symbol), name in lookup.items() if name}


def fill_member_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给成分股行补上缺失的名称（原地修改并返回）。"""
    missing = [row for row in rows if not str(row.get("stock_name") or "").strip()]
    if not missing:
        return rows
    names = _stock_name_map()
    for row in missing:
        symbol = str(row.get("symbol") or "").strip().zfill(6)
        row["stock_name"] = names.get(symbol, symbol)
    return rows

def build_temperature_rows(mapping: list[dict[str, str]], frames: dict[str, pd.DataFrame], window: int = 10, min_members: int = 10, as_of: pd.Timestamp | None = None, include_members: bool = True, prepared: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Build concept heat rows at ``as_of`` (or current frame end) from QFQ bars.

    ``prepared`` 是 prepare_series() 的产物：给了它就不裁剪 DataFrame、不重复调
    pandas，指标逐位等价（含缺失收盘价的股票仍走原路径）。
    """
    if as_of is not None:
        frames = {
            symbol: clipped
            for symbol, frame in frames.items()
            if not (clipped := frame.loc[frame.index <= as_of]).empty and clipped.index.max() == as_of
        }

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    if prepared:
        as_of_ns = pd.Timestamp(as_of if as_of is not None else max(frame.index.max() for frame in frames.values())).value
        metrics = {symbol: metric_from_series(prepared, symbol, as_of_ns, window) for symbol in frames}
        for symbol, frame in frames.items():
            if metrics.get(symbol) is None and symbol not in prepared:
                metrics[symbol] = _return_and_volume(frame, window)
    else:
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

    metric_keys = ("median_return_pct", "breadth_pct", "excess_return_pct", "strong_stock_pct", "active_volume_pct")
    percentiles = {key: percentile_of([float(row[key]) for row in drafts], [float(row[key]) for row in drafts])
                   for key in metric_keys}
    for index, draft in enumerate(drafts):
        scores = [percentiles[key][index] for key in metric_keys]
        draft["heat_score"] = round((scores[0] * 30 + scores[1] * 25 + scores[2] * 20 + scores[3] * 15 + scores[4] * 10), 1)
    score_values = [row["heat_score"] for row in drafts]
    score_percentiles = percentile_of(score_values, score_values)
    for index, row in enumerate(drafts):
        temp, label = _temperature(score_percentiles[index], row["median_return_pct"], row["breadth_pct"], row["excess_return_pct"], row["strong_stock_pct"], row["active_volume_pct"], row["member_count"], min_members)
        row.update({"temperature": temp, "temperature_label": label, "window": window})
        for field in ("median_return_pct", "breadth_pct", "excess_return_pct", "strong_stock_pct", "active_volume_pct"):
            row[field] = round(float(row[field]), 2)
    drafts.sort(key=lambda row: (row["temperature"] is None, -(row["temperature"] if row["temperature"] is not None else -1), -row["heat_score"], row["concept_name"]))
    return drafts, members_out
