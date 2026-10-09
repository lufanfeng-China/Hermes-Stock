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

# The framework covers general industrial and commercial companies.  These Shenwan
# level-1 groups need their own capital, leverage and cash-flow definitions.
SPECIAL_INDUSTRY_L1 = frozenset({"银行", "非银金融", "房地产"})


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


def _annual_year(row: dict[str, Any]) -> int | None:
    period = str(row.get("period") or "")
    try:
        return int(period[:4]) if period.endswith("A") else None
    except ValueError:
        return None


def _recent_annual_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annual = [row for row in reports if _annual_year(row) is not None]
    annual.sort(key=lambda row: _annual_year(row) or 0)
    return annual[-5:]


def _are_contiguous_annuals(rows: list[dict[str, Any]]) -> bool:
    years = [_annual_year(row) for row in rows]
    return len(years) == 5 and all(year is not None for year in years) and all(b == a + 1 for a, b in zip(years, years[1:]))


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


def _trend(first: float | None, last: float | None, neutral: float = 0.5, inverse: bool = False) -> str:
    if first is None or last is None:
        return "unknown"
    delta = last - first
    if inverse:
        delta = -delta
    return "up" if delta > neutral else "down" if delta < -neutral else "flat"


def _series_trend(values: list[float | None], neutral: float = 0.5, inverse: bool = False) -> str:
    """Compare early and late two-year averages for one homogeneous time series."""
    if len(values) < 4 or any(value is None for value in values):
        return "unknown"
    early = sum(values[:2]) / 2
    late = sum(values[-2:]) / 2
    return _trend(early, late, neutral, inverse)


def _combined_trend(*trends: str) -> str:
    directions = [1 if trend == "up" else -1 if trend == "down" else 0 for trend in trends if trend != "unknown"]
    if not directions:
        return "unknown"
    total = sum(directions)
    return "up" if total > 0 else "down" if total < 0 else "flat"


def _growth_series(values: list[float | None]) -> list[float | None]:
    return [_growth(previous, current) for previous, current in zip(values, values[1:])]


def _ratio_series(numerators: list[float | None], denominators: list[float | None], multiplier: float = 1.0) -> list[float | None]:
    return [numerator / denominator * multiplier if numerator is not None and denominator not in (None, 0) else None for numerator, denominator in zip(numerators, denominators)]


def _profit_path(values: list[float | None]) -> str:
    if any(value is None for value in values):
        return "unknown"
    first, last = values[0], values[-1]
    if first <= 0 < last:
        return "turnaround"
    if first < 0 and last < 0:
        return "loss_narrowing" if last > first else "loss_widening" if last < first else "loss_flat"
    return "profitable" if first > 0 and last > 0 else "unknown"


def _average(values: list[float | None]) -> float | None:
    return sum(values) / len(values) if values and all(value is not None for value in values) else None


def _flag(code: str, title: str, detail: str) -> dict[str, str]:
    return {"code": code, "title": title, "detail": detail}


def build_financial_health(
    reports: list[dict[str, Any]],
    *,
    industry_level_1: str | None = None,
    industry_level_2: str | None = None,
) -> dict[str, Any]:
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
        "red_flag_coverage": {"evaluated": 0, "total": 10, "unavailable": []},
        "investigation_items": [],
        "conclusions": [],
        "series": {},
        "reason": None,
        "industry": {"level_1": industry_level_1, "level_2": industry_level_2},
    }
    if industry_level_1 in SPECIAL_INDUSTRY_L1:
        result["status"] = "not_applicable"
        result["reason"] = f"{industry_level_1}行业不适用通用工商企业五年财务健康度评分规则"
        return result
    if len(rows) < 5:
        result["reason"] = "annual_reports_insufficient"
        return result
    if not _are_contiguous_annuals(rows):
        result["reason"] = "annual_reports_not_contiguous"
        return result

    values = {name: [_metric(row, name) for row in rows] for name in (
        "revenue", "ex_net_profit", "ocf", "free_cf", "gross_margin", "net_margin",
        "roe_ex", "debt_ratio", "accounts_receivable", "inventory", "capex", "goodwill",
        "equity", "total_assets",
    )}
    revenue_cagr = _cagr(values["revenue"][0], values["revenue"][-1])
    ex_profit_cagr = _cagr(values["ex_net_profit"][0], values["ex_net_profit"][-1])
    premium = ex_profit_cagr - revenue_cagr if revenue_cagr is not None and ex_profit_cagr is not None else None
    total_ocf = _sum(values["ocf"])
    total_ex_profit = _sum(values["ex_net_profit"])
    cash_profit_ratio = (total_ocf / total_ex_profit
                         if total_ocf is not None and total_ex_profit is not None and total_ex_profit > 0 else None)
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
    revenue_growths = _growth_series(values["revenue"])
    ex_profit_growths = _growth_series(values["ex_net_profit"])
    annual_cash_profit_ratios = _ratio_series(values["ocf"], values["ex_net_profit"])
    fcf_margins = _ratio_series(values["free_cf"], values["revenue"], 100)
    capex_intensities = _ratio_series(values["capex"], values["revenue"], 100)
    receivable_gaps = [a - b if a is not None and b is not None else None for a, b in zip(_growth_series(values["accounts_receivable"]), revenue_growths)]
    inventory_gaps = [a - b if a is not None and b is not None else None for a, b in zip(_growth_series(values["inventory"]), revenue_growths)]
    goodwill_equities = _ratio_series(values["goodwill"], values["equity"], 100)
    ex_profit_path = _profit_path(values["ex_net_profit"])
    result["series"] = {"years": [str(row.get("period")) for row in rows], "annual_cash_profit_ratio": annual_cash_profit_ratios, "fcf_margin": fcf_margins, "receivable_growth_gap": receivable_gaps, "inventory_growth_gap": inventory_gaps, "capex_intensity": capex_intensities, "roe_ex": values["roe_ex"], "debt_ratio": values["debt_ratio"], "goodwill_equity_ratio": goodwill_equities}
    result["derived"] = {
        "revenue_cagr": revenue_cagr,
        "ex_net_profit_cagr": ex_profit_cagr,
        "profit_growth_premium": premium,
        "gross_margin_change": values["gross_margin"][-1] - values["gross_margin"][0] if None not in (values["gross_margin"][-1], values["gross_margin"][0]) else None,
        "net_margin_change": values["net_margin"][-1] - values["net_margin"][0] if None not in (values["net_margin"][-1], values["net_margin"][0]) else None,
        "roe_ex_average": _average(values["roe_ex"]),
        "roe_ex_trend": _series_trend(values["roe_ex"]),
        "ex_net_profit_path": ex_profit_path,
        "annual_cash_profit_ratio": annual_cash_profit_ratios[-1],
        "five_year_cash_profit_ratio": cash_profit_ratio,
        "fcf_margin": fcf_margin,
        "receivable_growth_gap": receivable_gap,
        "inventory_growth_gap": inventory_gap,
        "capex_intensity": capex_intensity,
        "debt_ratio_trend": _series_trend(values["debt_ratio"], .5, inverse=True),
        "goodwill_trend": _series_trend(goodwill_equities, .5, inverse=True),
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
    revenue_growths = _growth_series(values["revenue"])
    ex_profit_growths = _growth_series(values["ex_net_profit"])
    cash_profit_ratios = _ratio_series(values["ocf"], values["ex_net_profit"])
    fcf_margins = _ratio_series(values["free_cf"], values["revenue"], 100)
    capex_intensities = _ratio_series(values["capex"], values["revenue"], 100)
    receivable_gaps = [
        receivable_growth - revenue_growth_item if receivable_growth is not None and revenue_growth_item is not None else None
        for receivable_growth, revenue_growth_item in zip(_growth_series(values["accounts_receivable"]), revenue_growths)
    ]
    inventory_gaps = [
        inventory_growth - revenue_growth_item if inventory_growth is not None and revenue_growth_item is not None else None
        for inventory_growth, revenue_growth_item in zip(_growth_series(values["inventory"]), revenue_growths)
    ]
    goodwill_equities = _ratio_series(values["goodwill"], values["equity"], 100)
    trends = (
        _combined_trend(_series_trend(revenue_growths, 1), _series_trend(ex_profit_growths, 1)),
        _combined_trend(_series_trend(values["gross_margin"]), _series_trend(values["net_margin"]), _series_trend(values["roe_ex"])),
        _combined_trend(_series_trend(cash_profit_ratios, .1), _series_trend(fcf_margins)),
        _combined_trend(_series_trend(receivable_gaps, 1, inverse=True), _series_trend(inventory_gaps, 1, inverse=True)),
        _combined_trend(_series_trend(capex_intensities, .5, inverse=True), _series_trend(fcf_margins), _series_trend(revenue_growths, 1)),
        _combined_trend(_series_trend(values["debt_ratio"], .5, inverse=True), _series_trend(goodwill_equities, .5, inverse=True), _series_trend(fcf_margins)),
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

    investigations: list[dict[str, str]] = []
    if ex_profit_path in {"turnaround", "loss_narrowing", "loss_widening"}:
        labels = {"turnaround": "扣非利润已扭亏", "loss_narrowing": "扣非亏损正在收窄", "loss_widening": "扣非亏损正在扩大"}
        investigations.append(_flag(f"ex_net_profit_{ex_profit_path}", labels[ex_profit_path], "扣非利润存在亏损期，CAGR 不适用；请结合绝对利润路径判断。"))
    gross_change = result["derived"]["gross_margin_change"]
    net_change = result["derived"]["net_margin_change"]
    if gross_change is not None and net_change is not None and gross_change * net_change < 0:
        investigations.append(_flag("margin_divergence", "毛利率与净利率方向背离", "请结合费用、投资收益、补助和税率变化调查利润率背离原因。"))
    roe_change = values["roe_ex"][-1] - values["roe_ex"][0] if None not in (values["roe_ex"][-1], values["roe_ex"][0]) else None
    debt_change = values["debt_ratio"][-1] - values["debt_ratio"][0] if None not in (values["debt_ratio"][-1], values["debt_ratio"][0]) else None
    if roe_change is not None and debt_change is not None and roe_change > 1 and debt_change > 3:
        investigations.append(_flag("roe_leverage", "ROE 改善可能受杠杆驱动", "扣非 ROE 上升同时资产负债率明显上升，应区分经营改善与杠杆效应。"))
    result["investigation_items"] = investigations

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
    recent_capex = values["capex"][-3:]
    recent_revenue_growths = revenue_growths[-3:]
    if (all(a is not None and b is not None and a < b for a, b in zip(recent_capex, recent_capex[1:]))
            and all(a is not None and b is not None and a > b for a, b in zip(recent_revenue_growths, recent_revenue_growths[1:]))):
        flags.append(_flag("capex_up_revenue_growth_down", "资本开支持续增加但营收增速持续下降", "最新三个完整年度 CapEx 持续增加，营收同比增速持续下降。"))
    if all(value is not None and value < 0 for value in values["free_cf"][-2:]):
        flags.append(_flag("fcf_two_year_negative", "自由现金流连续两年为负", "最新两个完整年度 FCF 均为负。"))
    goodwill_growth = _growth(values["goodwill"][-2], values["goodwill"][-1])
    if goodwill_growth is not None and goodwill_growth > 20 and ex_growth is not None and ex_growth <= 0:
        flags.append(_flag("goodwill_up_profit_not", "商誉增长但扣非利润未同步增长", f"商誉同比增长 {goodwill_growth:.1f}%，扣非归母净利润未增长。"))
    result["red_flags"] = flags
    result["red_flag_count"] = len(flags)
    rule_inputs = {
        "revenue_up_ex_profit_down": values["revenue"][-2:] + values["ex_net_profit"][-2:],
        "ex_profit_up_ocf_down": values["ex_net_profit"][-2:] + values["ocf"][-2:],
        "receivables_growth_gap": values["accounts_receivable"][-2:] + values["revenue"][-2:],
        "inventory_growth_gap": values["inventory"][-2:] + values["revenue"][-2:],
        "gross_margin_two_year_decline": values["gross_margin"][-3:],
        "roe_ex_decline": values["roe_ex"][-3:],
        "debt_ratio_rising": values["debt_ratio"][-3:],
        "capex_up_revenue_growth_down": values["capex"][-3:] + values["revenue"][-4:],
        "fcf_two_year_negative": values["free_cf"][-2:],
        "goodwill_up_profit_not": values["goodwill"][-2:] + values["ex_net_profit"][-2:],
    }
    unavailable = [code for code, inputs in rule_inputs.items() if any(value is None for value in inputs)]
    result["red_flag_coverage"] = {"evaluated": 10 - len(unavailable), "total": 10, "unavailable": unavailable}
    def conclusion(code: str, question: str, status: str, detail: str) -> dict[str, str]:
        return {"code": code, "question": question, "status": status, "detail": detail}
    profit_metrics = [result["derived"]["gross_margin_change"], result["derived"]["net_margin_change"], result["derived"]["roe_ex_trend"]]
    profitability_status = "improving" if all(value is not None and value >= 0 for value in profit_metrics[:2]) and profit_metrics[2] == "up" else "watch" if any(value is None or value < 0 for value in profit_metrics[:2]) or profit_metrics[2] == "down" else "stable"
    cash_status = "improving" if cash_profit_ratio is not None and cash_profit_ratio >= .8 and fcf_margin is not None and fcf_margin >= 0 else "watch" if cash_profit_ratio is None or fcf_margin is None or cash_profit_ratio < .5 or fcf_margin < 0 else "stable"
    working_status = "watch" if (receivable_gap is not None and receivable_gap > 15) or (inventory_gap is not None and inventory_gap > 15) else "insufficient" if receivable_gap is None or inventory_gap is None else "stable"
    leverage_status = "watch" if (capex_intensities[-1] is not None and capex_intensities[0] is not None and capex_intensities[-1] > capex_intensities[0] and debt_change is not None and debt_change > 3) else "stable"
    result["conclusions"] = [
        conclusion("growth", "过去五年是否持续增长？", "improving" if revenue_cagr is not None and revenue_cagr > 0 and ex_profit_path == "profitable" else "watch" if revenue_cagr is not None else "insufficient", f"营收 CAGR {revenue_cagr:.1f}%；扣非利润路径：{ex_profit_path}。" if revenue_cagr is not None else "缺少可比增长数据。"),
        conclusion("profit_premium", "利润增长是否快于收入增长？", "improving" if premium is not None and premium > 0 else "watch" if premium is not None else "insufficient", f"利润增长溢价 {premium:.1f}pct。" if premium is not None else "扣非利润 CAGR 不适用或数据不足。"),
        conclusion("profitability", "毛利率、净利率和 ROE 是否在改善？", profitability_status, "结合五年毛利率、净利率变化和扣非 ROE 趋势判断。"),
        conclusion("cash_conversion", "利润是否真正转化成了现金？", cash_status, f"五年现金利润比 {cash_profit_ratio:.2f}，最新 FCF Margin {fcf_margin:.1f}% 。" if cash_profit_ratio is not None and fcf_margin is not None else "现金转化数据不足或亏损期不适用。"),
        conclusion("working_capital", "应收和库存是否出现异常增长？", working_status, "以最新年度应收、存货相对营收增速差判断。"),
        conclusion("capital_leverage", "增长是否依赖越来越高的资本投入和财务杠杆？", leverage_status, "结合 CapEx 强度和资产负债率五年趋势判断。"),
    ]
    return result
