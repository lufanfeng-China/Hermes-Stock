"""Transparent five-year financial-health KPI calculations.

This module intentionally works only from complete annual reports.  Interim reports
remain useful for the raw trend charts, but are not mixed into five-year CAGR or
cumulative cash-quality calculations.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

DIMENSIONS = (
    ("growth_quality", "核心增长质量", 20),
    ("profitability", "盈利能力", 20),
    ("cash_quality", "现金含金量", 20),
    ("working_capital", "营运资本健康度", 15),
    ("reinvestment", "再投资效率", 10),
    ("financial_risk", "财务风险", 15),
)


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _metric(row: dict[str, Any], name: str) -> float | None:
    return _number((row.get("metrics") or {}).get(name))


def _cagr(first: float | None, last: float | None, periods: int = 4) -> float | None:
    if first is None or last is None or first <= 0 or last <= 0 or periods <= 0:
        return None
    return ((last / first) ** (1 / periods) - 1) * 100


def _growth(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return (current / previous - 1) * 100


def _sum(values: list[float | None]) -> float | None:
    return sum(values) if values and all(value is not None for value in values) else None


def _recent_annual_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annual = [row for row in reports if str(row.get("period") or "").endswith("A")]
    annual.sort(key=lambda row: str(row.get("report_date") or ""))
    return annual[-5:]


def _score_band(value: float | None, bands: tuple[tuple[float, float], ...]) -> float | None:
    if value is None:
        return None
    for threshold, score in bands:
        if value >= threshold:
            return score
    return 0.0


def _status(score: float, weight: float) -> str:
    ratio = score / weight if weight else 0
    return "green" if ratio >= .75 else "yellow" if ratio >= .45 else "red"


def _trend(first: float | None, last: float | None, neutral: float = 0.5) -> str:
    if first is None or last is None:
        return "unknown"
    delta = last - first
    return "up" if delta > neutral else "down" if delta < -neutral else "flat"


def _flag(code: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail}


def build_financial_health(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a transparent health score and independent red-flag list.

    The score is a screening aid only. Red flags are intentionally returned as an
    independent list and must never be hidden by a high composite score.
    """
    rows = _recent_annual_reports(reports)
    result: dict[str, Any] = {
        "periods": [str(row.get("period")) for row in rows],
        "score": None,
        "status": "insufficient_data",
        "coverage_weight": 0,
        "dimensions": [],
        "derived": {},
        "red_flags": [],
        "red_flag_count": 0,
    }
    if len(rows) < 5:
        return result

    values = {name: [_metric(row, name) for row in rows] for name in (
        "revenue", "ex_net_profit", "ocf", "free_cf", "gross_margin", "net_margin",
        "roe_ex", "debt_ratio", "accounts_receivable", "inventory", "capex", "goodwill",
        "equity", "total_assets",
    )}
    revenue_cagr = _cagr(values["revenue"][0], values["revenue"][-1])
    ex_profit_cagr = _cagr(values["ex_net_profit"][0], values["ex_net_profit"][-1])
    premium = ex_profit_cagr - revenue_cagr if revenue_cagr is not None and ex_profit_cagr is not None else None
    cash_profit_ratio = (_sum(values["ocf"]) / _sum(values["ex_net_profit"])
                         if _sum(values["ocf"]) is not None and _sum(values["ex_net_profit"]) not in (None, 0) else None)
    fcf_margin = (values["free_cf"][-1] / values["revenue"][-1] * 100
                  if values["free_cf"][-1] is not None and values["revenue"][-1] not in (None, 0) else None)
    capex_intensity = (values["capex"][-1] / values["revenue"][-1] * 100
                       if values["capex"][-1] is not None and values["revenue"][-1] not in (None, 0) else None)
    receivable_gap = _growth(values["accounts_receivable"][-2], values["accounts_receivable"][-1])
    inventory_gap = _growth(values["inventory"][-2], values["inventory"][-1])
    revenue_growth = _growth(values["revenue"][-2], values["revenue"][-1])
    receivable_gap = receivable_gap - revenue_growth if receivable_gap is not None and revenue_growth is not None else None
    inventory_gap = inventory_gap - revenue_growth if inventory_gap is not None and revenue_growth is not None else None
    goodwill_equity = (values["goodwill"][-1] / values["equity"][-1] * 100
                       if values["goodwill"][-1] is not None and values["equity"][-1] not in (None, 0) else None)
    goodwill_assets = (values["goodwill"][-1] / values["total_assets"][-1] * 100
                       if values["goodwill"][-1] is not None and values["total_assets"][-1] not in (None, 0) else None)
    result["derived"] = {
        "revenue_cagr": revenue_cagr,
        "ex_net_profit_cagr": ex_profit_cagr,
        "profit_growth_premium": premium,
        "five_year_cash_profit_ratio": cash_profit_ratio,
        "fcf_margin": fcf_margin,
        "receivable_growth_gap": receivable_gap,
        "inventory_growth_gap": inventory_gap,
        "capex_intensity": capex_intensity,
        "goodwill_equity_ratio": goodwill_equity,
        "goodwill_assets_ratio": goodwill_assets,
    }

    growth_score = _score_band(revenue_cagr, ((10, 7), (5, 5), (0, 3)))
    adjusted_score = _score_band(ex_profit_cagr, ((12, 7), (6, 5), (0, 3)))
    premium_score = _score_band(premium, ((5, 6), (0, 4), (-5, 2)))
    growth = None if None in (growth_score, adjusted_score, premium_score) else growth_score + adjusted_score + premium_score

    gross_score = _score_band(values["gross_margin"][-1] - values["gross_margin"][0] if None not in (values["gross_margin"][-1], values["gross_margin"][0]) else None, ((2, 5), (0, 3), (-2, 1)))
    net_score = _score_band(values["net_margin"][-1] - values["net_margin"][0] if None not in (values["net_margin"][-1], values["net_margin"][0]) else None, ((2, 5), (0, 3), (-2, 1)))
    roe_score = _score_band(values["roe_ex"][-1], ((15, 7), (10, 5), (5, 3), (0, 1)))
    roe_trend_score = _score_band(values["roe_ex"][-1] - values["roe_ex"][0] if None not in (values["roe_ex"][-1], values["roe_ex"][0]) else None, ((2, 3), (0, 2), (-2, 1)))
    profitability = None if None in (gross_score, net_score, roe_score, roe_trend_score) else gross_score + net_score + roe_score + roe_trend_score

    cash_ratio_score = _score_band(cash_profit_ratio, ((1.2, 10), (.8, 7), (.5, 3)))
    fcf_score = _score_band(fcf_margin, ((10, 10), (5, 7), (0, 4)))
    cash = None if None in (cash_ratio_score, fcf_score) else cash_ratio_score + fcf_score

    receivable_score = _score_band(-receivable_gap if receivable_gap is not None else None, ((5, 8), (-5, 6), (-15, 3)))
    inventory_score = _score_band(-inventory_gap if inventory_gap is not None else None, ((5, 7), (-5, 5), (-15, 2)))
    working = None if None in (receivable_score, inventory_score) else receivable_score + inventory_score

    capex_score = _score_band(-capex_intensity if capex_intensity is not None else None, ((-5, 5), (-10, 3), (-20, 1)))
    reinvest = None if capex_score is None or fcf_margin is None else capex_score + _score_band(fcf_margin, ((5, 5), (0, 3)))

    debt_score = _score_band(-values["debt_ratio"][-1] if values["debt_ratio"][-1] is not None else None, ((-40, 8), (-60, 5), (-75, 2)))
    goodwill_score = _score_band(-goodwill_equity if goodwill_equity is not None else None, ((-10, 4), (-25, 2)))
    risk_fcf_score = _score_band(fcf_margin, ((0, 3), (-5, 1)))
    risk = None if None in (debt_score, goodwill_score, risk_fcf_score) else debt_score + goodwill_score + risk_fcf_score

    scores = (growth, profitability, cash, working, reinvest, risk)
    trends = (
        _trend(revenue_cagr, ex_profit_cagr, 1),
        _trend(values["roe_ex"][0], values["roe_ex"][-1]),
        _trend(cash_profit_ratio, fcf_margin / 10 if fcf_margin is not None else None, .1),
        _trend(receivable_gap, inventory_gap, 1),
        _trend(values["capex"][0], values["capex"][-1]),
        _trend(values["debt_ratio"][0], values["debt_ratio"][-1]),
    )
    dimensions = []
    for (code, title, weight), score, trend in zip(DIMENSIONS, scores, trends):
        available = score is not None
        dimensions.append({"code": code, "title": title, "weight": weight, "score": score, "trend": trend, "status": _status(score, weight) if available else "unknown", "available": available})
    result["dimensions"] = dimensions
    coverage = sum(item["weight"] for item in dimensions if item["available"])
    raw_total = sum(item["score"] for item in dimensions if item["available"])
    result["coverage_weight"] = coverage
    result["score"] = round(raw_total / coverage * 100, 1) if coverage else None
    result["status"] = _status(result["score"], 100) if result["score"] is not None else "insufficient_data"

    flags: list[dict[str, str]] = []
    if revenue_growth is not None and revenue_growth > 0 and _growth(values["ex_net_profit"][-2], values["ex_net_profit"][-1]) is not None and _growth(values["ex_net_profit"][-2], values["ex_net_profit"][-1]) < 0:
        flags.append(_flag("revenue_up_ex_profit_down", "营收增长但扣非归母净利润下降", f"最新年度营收同比 {revenue_growth:.1f}%，扣非归母净利润同比下降。"))
    ex_growth = _growth(values["ex_net_profit"][-2], values["ex_net_profit"][-1])
    ocf_growth = _growth(values["ocf"][-2], values["ocf"][-1])
    if ex_growth is not None and ex_growth > 0 and ocf_growth is not None and ocf_growth < 0:
        flags.append(_flag("ex_profit_up_ocf_down", "扣非归母净利润增长但 CFO 下降", f"扣非归母净利润同比 {ex_growth:.1f}%，CFO 同比 {ocf_growth:.1f}%。"))
    if receivable_gap is not None and receivable_gap > 15:
        flags.append(_flag("receivables_growth_gap", "应收账款增长明显快于营收", f"应收增速较营收高 {receivable_gap:.1f}pct。"))
    if inventory_gap is not None and inventory_gap > 15:
        flags.append(_flag("inventory_growth_gap", "存货增长明显快于营收", f"存货增速较营收高 {inventory_gap:.1f}pct。"))
    if all(a is not None and b is not None and a > b for a, b in zip(values["gross_margin"][-3:], values["gross_margin"][-2:])):
        flags.append(_flag("gross_margin_two_year_decline", "毛利率连续两年下降", "最新三个完整年度毛利率连续下降。"))
    if all(a is not None and b is not None and a > b for a, b in zip(values["roe_ex"][-3:], values["roe_ex"][-2:])):
        flags.append(_flag("roe_ex_decline", "扣非 ROE 连续下降", "最新三个完整年度扣非 ROE 连续下降。"))
    if all(a is not None and b is not None and a < b for a, b in zip(values["debt_ratio"][-3:], values["debt_ratio"][-2:])):
        flags.append(_flag("debt_ratio_rising", "资产负债率连续上升", "最新三个完整年度资产负债率连续上升。"))
    if all(value is not None and value < 0 for value in values["free_cf"][-2:]):
        flags.append(_flag("fcf_two_year_negative", "自由现金流连续两年为负", "最新两个完整年度 FCF 均为负。"))
    goodwill_growth = _growth(values["goodwill"][-2], values["goodwill"][-1])
    if goodwill_growth is not None and goodwill_growth > 20 and ex_growth is not None and ex_growth <= 0:
        flags.append(_flag("goodwill_up_profit_not", "商誉增长但扣非利润未同步增长", f"商誉同比增长 {goodwill_growth:.1f}%，扣非归母净利润未增长。"))
    result["red_flags"] = flags
    result["red_flag_count"] = len(flags)
    return result
