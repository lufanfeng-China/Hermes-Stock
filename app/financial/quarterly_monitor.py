"""Provisional quarterly health monitor built from TTM flows and latest balances."""
from __future__ import annotations

from math import isfinite
from typing import Any

from app.financial.health import SPECIAL_INDUSTRY_L1

FLOW_FIELDS = ("revenue", "ex_net_profit", "ocf", "capex")
BALANCE_FIELDS = ("debt_ratio", "accounts_receivable", "inventory", "goodwill", "equity", "total_assets")


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _metric(row: dict[str, Any], key: str) -> float | None:
    return _number((row.get("metrics") or {}).get(key))


def _growth(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return (current / previous - 1) * 100


def _year(period: str) -> int | None:
    try:
        return int(str(period)[:4])
    except (TypeError, ValueError):
        return None


def _not_available(reason: str, status: str = "unavailable") -> dict[str, Any]:
    return {"status": status, "reason": reason, "latest_period": None, "ttm": {}, "dimensions": [], "alerts": []}


def build_quarterly_financial_monitor(reports: list[dict[str, Any]], industry_level_1: str | None) -> dict[str, Any]:
    """Return a non-scored early-warning monitor for the latest Q1/Q2/Q3 report.

    Flow fields are converted from cumulative Chinese-reporting values to TTM:
    current YTD - prior-year matching YTD + prior annual. Balance-sheet fields use
    the latest quarter-end balance and compare against the same quarter last year.
    """
    if not industry_level_1 or not str(industry_level_1).strip():
        return _not_available("industry_classification_unavailable", "not_applicable")
    if industry_level_1 in SPECIAL_INDUSTRY_L1:
        return _not_available("special_industry_not_applicable", "not_applicable")
    by_period = {str(row.get("period") or ""): row for row in reports}
    quarters = [row for row in reports if str(row.get("period") or "")[-2:] in {"Q1", "Q2", "Q3"}]
    if not quarters:
        return _not_available("latest_quarterly_report_unavailable")
    latest = max(quarters, key=lambda row: str(row.get("report_date") or ""))
    period = str(latest.get("period"))
    year = _year(period)
    suffix = period[-2:]
    if year is None:
        return _not_available("latest_quarterly_period_invalid")
    prior_quarter = by_period.get(f"{year - 1}{suffix}")
    prior_annual = by_period.get(f"{year - 1}A")
    if not prior_quarter or not prior_annual:
        return _not_available("ttm_comparison_base_unavailable")

    ttm: dict[str, float | None] = {}
    for key in FLOW_FIELDS:
        now, prior_ytd, prior_year = _metric(latest, key), _metric(prior_quarter, key), _metric(prior_annual, key)
        ttm[key] = now - prior_ytd + prior_year if None not in (now, prior_ytd, prior_year) else None
    ttm["free_cf"] = ttm["ocf"] - ttm["capex"] if None not in (ttm["ocf"], ttm["capex"]) else None
    ttm_margin = ttm["free_cf"] / ttm["revenue"] * 100 if ttm["free_cf"] is not None and ttm["revenue"] not in (None, 0) else None
    current_yoy = {key: _growth(_metric(prior_quarter, key), _metric(latest, key)) for key in FLOW_FIELDS}
    receivable_gap = _growth(_metric(prior_quarter, "accounts_receivable"), _metric(latest, "accounts_receivable"))
    inventory_gap = _growth(_metric(prior_quarter, "inventory"), _metric(latest, "inventory"))
    revenue_yoy = current_yoy["revenue"]
    receivable_gap = receivable_gap - revenue_yoy if None not in (receivable_gap, revenue_yoy) else None
    inventory_gap = inventory_gap - revenue_yoy if None not in (inventory_gap, revenue_yoy) else None
    debt_change = (_metric(latest, "debt_ratio") - _metric(prior_quarter, "debt_ratio")
                   if None not in (_metric(latest, "debt_ratio"), _metric(prior_quarter, "debt_ratio")) else None)

    alerts = []
    def alert(code: str, title: str, detail: str, severity: str = "watch") -> None:
        alerts.append({"code": code, "title": title, "detail": detail, "severity": severity})
    if revenue_yoy is not None and revenue_yoy > 0 and current_yoy["ex_net_profit"] is not None and current_yoy["ex_net_profit"] < 0:
        alert("revenue_up_profit_down", "收入增长但扣非利润下降", f"最新累计营收同比 {revenue_yoy:.1f}%，扣非利润同比 {current_yoy['ex_net_profit']:.1f}%", "high")
    if current_yoy["ex_net_profit"] is not None and current_yoy["ex_net_profit"] > 0 and current_yoy["ocf"] is not None and current_yoy["ocf"] < 0:
        alert("profit_up_ocf_down", "扣非利润改善但经营现金流下降", f"扣非利润同比 {current_yoy['ex_net_profit']:.1f}%，CFO 同比 {current_yoy['ocf']:.1f}%")
    if receivable_gap is not None and receivable_gap > 15:
        alert("receivables_growth_gap", "应收账款增长明显快于营收", f"应收增速较营收高 {receivable_gap:.1f}pct")
    if inventory_gap is not None and inventory_gap > 15:
        alert("inventory_growth_gap", "存货增长明显快于营收", f"存货增速较营收高 {inventory_gap:.1f}pct")
    if debt_change is not None and debt_change >= 3:
        alert("debt_ratio_rising", "资产负债率明显上升", f"较去年同季上升 {debt_change:.1f}pct")
    if ttm_margin is not None and ttm_margin < 0:
        alert("ttm_fcf_negative", "TTM 自由现金流为负", f"TTM FCF Margin 为 {ttm_margin:.1f}%", "high")

    def state(watch: bool, improving: bool = False) -> str:
        return "watch" if watch else "improving" if improving else "stable"
    dimensions = [
        {"code": "growth", "title": "核心增长质量", "status": state((revenue_yoy or 0) > 0 and (current_yoy["ex_net_profit"] or 0) < 0, (revenue_yoy or 0) > 0 and (current_yoy["ex_net_profit"] or 0) > 0), "detail": f"累计营收同比 {revenue_yoy:.1f}%；扣非利润同比 {current_yoy['ex_net_profit']:.1f}%" if None not in (revenue_yoy, current_yoy['ex_net_profit']) else "同比数据不足"},
        {"code": "profitability", "title": "盈利能力", "status": state((_metric(latest, "gross_margin") or 0) < (_metric(prior_quarter, "gross_margin") or 0) - 2 or (_metric(latest, "net_margin") or 0) < (_metric(prior_quarter, "net_margin") or 0) - 2, (_metric(latest, "gross_margin") or 0) > (_metric(prior_quarter, "gross_margin") or 0) + 2 and (_metric(latest, "net_margin") or 0) > (_metric(prior_quarter, "net_margin") or 0) + 2), "detail": f"毛利率 {_metric(latest, 'gross_margin'):.1f}%；净利率 {_metric(latest, 'net_margin'):.1f}%" if None not in (_metric(latest, 'gross_margin'), _metric(latest, 'net_margin')) else "利润率数据不足"},
        {"code": "cash", "title": "现金含金量", "status": state((ttm_margin or 0) < 0, (ttm_margin or 0) >= 5), "detail": f"TTM FCF Margin {ttm_margin:.1f}%" if ttm_margin is not None else "TTM 自由现金流数据不足"},
        {"code": "working_capital", "title": "营运资本", "status": state((receivable_gap or 0) > 15 or (inventory_gap or 0) > 15, (receivable_gap or 0) <= -5 and (inventory_gap or 0) <= -5), "detail": f"应收增速差 {receivable_gap:.1f}pct；存货增速差 {inventory_gap:.1f}pct" if None not in (receivable_gap, inventory_gap) else "同比数据不足"},
        {"code": "reinvestment", "title": "再投资效率", "status": state((current_yoy["capex"] or 0) > 20 and (revenue_yoy or 0) < 5 and (ttm_margin or 0) < 0, (ttm_margin or 0) >= 5 and (revenue_yoy or 0) > 0), "detail": f"TTM FCF Margin {ttm_margin:.1f}%；累计 CapEx 同比 {current_yoy['capex']:.1f}%" if None not in (ttm_margin, current_yoy['capex']) else "投入或现金流数据不足"},
        {"code": "financial_risk", "title": "财务风险", "status": state((debt_change or 0) >= 3 or (ttm_margin or 0) < 0, (debt_change or 0) <= -3 and (ttm_margin or 0) >= 0), "detail": f"资产负债率较去年同季 {debt_change:+.1f}pct" if debt_change is not None else "同季负债率数据不足"},
    ]
    return {"status": "available", "reason": None, "latest_period": period, "as_of": latest.get("report_date"), "basis": "TTM + latest_quarter_balance", "ttm": {**ttm, "fcf_margin": ttm_margin}, "yoy": current_yoy, "latest": {key: _metric(latest, key) for key in BALANCE_FIELDS}, "gaps": {"receivable_growth_gap": receivable_gap, "inventory_growth_gap": inventory_gap, "debt_ratio_change": debt_change}, "dimensions": dimensions, "alerts": alerts}
