"""板块维度的「股价收益比」分布，供筛选页的弹框图表使用。

口径与筛选页一致：eps_ratio_5y = 最近 N 个完整年度「基本每股收益」加总 ÷ 最新前复权收盘价，
不足五年按 4/3/2/1 年年化；单位 %。负值代表五年累计亏损，不能当作低估值使用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.stock_filter import board_of

ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = ROOT / "data/derived/datasets/final/stock_filter_market_metrics_current.json"

BOARDS: tuple[tuple[str, str], ...] = (
    ("main", "沪深主板"),
    ("chinext", "创业板"),
    ("star", "科创板"),
    ("bj", "北交所"),
)

BIN_EDGES: tuple[tuple[float, float, str], ...] = (
    (float("-inf"), 0.0, "<0"),
    (0.0, 10.0, "0–10%"),
    (10.0, 20.0, "10–20%"),
    (20.0, 30.0, "20–30%"),
    (30.0, 50.0, "30–50%"),
    (50.0, float("inf"), "≥50%"),
)

DEFINITION = (
    "最近 5 个完整年度「基本每股收益」加总 ÷ 最新前复权收盘价，单位 %；"
    "不足五年按 4/3/2/1 年年化（×1.25 / ×5·3⁻¹ / ×2.5 / ×5）。"
    "负值代表五年累计亏损，不能当作低估值使用。"
)


def _pct(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q))


def _board_block(values: list[float], missing: int) -> dict[str, Any]:
    array = np.array(values, dtype=float)
    counts = []
    for low, high, label in BIN_EDGES:
        if low == float("-inf"):
            count = int((array < high).sum())
        elif high == float("inf"):
            count = int((array >= low).sum())
        else:
            count = int(((array >= low) & (array < high)).sum())
        counts.append({"label": label, "count": count, "pct": round(count / len(array) * 100, 2)})

    negative = int((array < 0).sum())
    median = _pct(array, 50)
    return {
        "n": int(array.size),
        "missing": int(missing),
        "mean": round(float(array.mean()), 2),
        "median": round(median, 2),
        "q1": round(_pct(array, 25), 2),
        "q3": round(_pct(array, 75), 2),
        "p10": round(_pct(array, 10), 2),
        "p90": round(_pct(array, 90), 2),
        "min": round(float(array.min()), 2),
        "max": round(float(array.max()), 2),
        "negative": negative,
        "negative_pct": round(negative / array.size * 100, 2),
        "median_positive": round(_pct(array[array >= 0], 50), 2) if (array >= 0).any() else None,
        "cheap_30": int((array >= 30).sum()),
        "cheap_30_pct": round(float((array >= 30).mean() * 100), 2),
        # 五年加总收益比换算成等价 PE：5 年 EPS 合计 ÷ 价格 = r  →  PE ≈ 5 / r
        "implied_pe": round(500.0 / median, 1) if median else None,
        "bins": counts,
    }


def eps_ratio_distribution() -> dict[str, Any]:
    """按板块给出 eps_ratio_5y 的分布统计。"""
    if not METRICS_PATH.exists():
        return {"ok": False, "error": {"code": "distribution_unavailable",
                                       "message": "stock filter metrics snapshot missing"}}
    payload = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    metrics = payload.get("metrics") or {}

    values: dict[str, list[float]] = {key: [] for key, _ in BOARDS}
    missing: dict[str, int] = {key: 0 for key, _ in BOARDS}
    as_of = ""
    for symbol, metric in metrics.items():
        market, _, code = symbol.partition(":")
        board = board_of(market, code)
        if board not in values:
            continue
        as_of = max(as_of, str(metric.get("qfq_as_of") or ""))
        value = metric.get("eps_ratio_5y")
        if value is None:
            missing[board] += 1
        else:
            values[board].append(float(value))

    boards = []
    for key, label in BOARDS:
        if not values[key]:
            boards.append({"key": key, "label": label, "n": 0, "missing": missing[key]})
            continue
        boards.append({"key": key, "label": label, **_board_block(values[key], missing[key])})

    return {
        "ok": True,
        "as_of_date": as_of,
        "metric": "eps_ratio_5y",
        "definition": DEFINITION,
        "bins": [label for _, _, label in BIN_EDGES],
        "boards": boards,
    }
