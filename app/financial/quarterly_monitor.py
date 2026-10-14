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


_SEVERITY_ORDER = {"unavailable": -1, "watch": 0, "high": 1, "critical": 2}


def _severity_result(severity: str, rule: str, metrics: dict[str, float | None], thresholds: dict[str, float]) -> dict[str, Any]:
    return {"severity": severity, "rule": rule, "metrics": metrics, "thresholds": thresholds}


def classify_alert_severity(kind: str, **metrics: float | None) -> dict[str, Any]:
    """Classify a quarterly alert by observed magnitude, not its event type."""
    if kind == "revenue_profit_divergence":
        revenue_yoy, profit_yoy = _number(metrics.get("revenue_yoy")), _number(metrics.get("ex_net_profit_yoy"))
        growth_gap = revenue_yoy - profit_yoy if revenue_yoy is not None and profit_yoy is not None else None
        thresholds = {"high_profit_yoy_lte": -10.0, "high_growth_gap_gte": 20.0, "critical_profit_yoy_lte": -30.0, "critical_revenue_yoy_gte": 10.0}
        if revenue_yoy is None or profit_yoy is None or revenue_yoy <= 0 or profit_yoy >= 0:
            return _severity_result("unavailable", "revenue_positive_profit_negative", {"revenue_yoy": revenue_yoy, "ex_net_profit_yoy": profit_yoy, "growth_gap_pct": growth_gap}, thresholds)
        severity = "critical" if profit_yoy <= -30 and revenue_yoy >= 10 else "high" if profit_yoy <= -10 or (growth_gap is not None and growth_gap >= 20) else "watch"
        result = _severity_result(severity, "revenue_positive_profit_negative", {"revenue_yoy": revenue_yoy, "ex_net_profit_yoy": profit_yoy, "growth_gap_pct": growth_gap}, thresholds)
        result["growth_gap_pct"] = growth_gap
        return result
    if kind == "profit_cash_divergence":
        profit_yoy, ocf_yoy, ttm_ocf = _number(metrics.get("ex_net_profit_yoy")), _number(metrics.get("ocf_yoy")), _number(metrics.get("ttm_ocf"))
        growth_gap = profit_yoy - ocf_yoy if profit_yoy is not None and ocf_yoy is not None else None
        thresholds = {"high_ocf_yoy_lte": -20.0, "high_growth_gap_gte": 30.0, "critical_ocf_yoy_lte": -50.0, "critical_ttm_ocf_lt": 0.0}
        if profit_yoy is None or ocf_yoy is None or profit_yoy <= 0 or ocf_yoy >= 0:
            return _severity_result("unavailable", "profit_positive_ocf_negative", {"ex_net_profit_yoy": profit_yoy, "ocf_yoy": ocf_yoy, "ttm_ocf": ttm_ocf, "growth_gap_pct": growth_gap}, thresholds)
        severity = "critical" if ocf_yoy <= -50 and ttm_ocf is not None and ttm_ocf < 0 else "high" if ocf_yoy <= -20 or (growth_gap is not None and growth_gap >= 30) else "watch"
        return _severity_result(severity, "profit_positive_ocf_negative", {"ex_net_profit_yoy": profit_yoy, "ocf_yoy": ocf_yoy, "ttm_ocf": ttm_ocf, "growth_gap_pct": growth_gap}, thresholds)
    if kind == "working_capital_gap":
        gap = _number(metrics.get("growth_gap_pct"))
        thresholds = {"watch_growth_gap_gt": 15.0, "high_growth_gap_gt": 30.0, "critical_growth_gap_gt": 50.0}
        severity = "unavailable" if gap is None else "critical" if gap > 50 else "high" if gap > 30 else "watch"
        return _severity_result(severity, "working_capital_growth_gap", {"growth_gap_pct": gap}, thresholds)
    if kind == "leverage":
        debt_change, fcf_margin = _number(metrics.get("debt_change_pct")), _number(metrics.get("fcf_margin_pct"))
        thresholds = {"watch_debt_change_gte": 3.0, "high_debt_change_gte": 8.0, "critical_debt_change_gte": 15.0, "critical_fcf_margin_lt": 0.0}
        severity = "unavailable" if debt_change is None else "critical" if debt_change >= 15 and fcf_margin is not None and fcf_margin < 0 else "high" if debt_change >= 8 else "watch"
        return _severity_result(severity, "debt_ratio_rising", {"debt_change_pct": debt_change, "fcf_margin_pct": fcf_margin}, thresholds)
    if kind == "fcf_margin":
        fcf_margin = _number(metrics.get("fcf_margin_pct"))
        thresholds = {"watch_fcf_margin_lt": 0.0, "high_fcf_margin_lt": -5.0, "critical_fcf_margin_lt": -10.0}
        severity = "unavailable" if fcf_margin is None else "critical" if fcf_margin < -10 else "high" if fcf_margin < -5 else "watch"
        return _severity_result(severity, "ttm_fcf_negative", {"fcf_margin_pct": fcf_margin}, thresholds)
    raise ValueError(f"Unsupported quarterly alert kind: {kind}")


def aggregate_alert_severity(severities: list[str]) -> str:
    """Escalate three medium risks or two high risks without numerical score penalties."""
    critical_count = sum(item == "critical" for item in severities)
    high_count = sum(item == "high" for item in severities)
    watch_count = sum(item == "watch" for item in severities)
    if critical_count or high_count >= 2:
        return "critical"
    if high_count or watch_count >= 3:
        return "high"
    return "watch" if watch_count else "unavailable"


def _high_severity_threshold_note(basis: dict[str, Any]) -> str:
    rule = basis.get("rule")
    thresholds = basis.get("thresholds") or {}
    if rule == "revenue_positive_profit_negative":
        return f"高严重度阈值：扣非利润同比≤{thresholds['high_profit_yoy_lte']:.1f}% 或增速差≥{thresholds['high_growth_gap_gte']:.1f}pct"
    if rule == "profit_positive_ocf_negative":
        return f"高严重度阈值：CFO 同比≤{thresholds['high_ocf_yoy_lte']:.1f}% 或增速差≥{thresholds['high_growth_gap_gte']:.1f}pct"
    if rule == "working_capital_growth_gap":
        return f"高严重度阈值：增速差>{thresholds['high_growth_gap_gt']:.1f}pct"
    if rule == "debt_ratio_rising":
        return f"高严重度阈值：资产负债率同比上升≥{thresholds['high_debt_change_gte']:.1f}pct"
    if rule == "ttm_fcf_negative":
        return f"高严重度阈值：TTM FCF Margin<{thresholds['high_fcf_margin_lt']:.1f}%"
    return "高严重度阈值：详见风险规则"


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
    def alert(code: str, title: str, detail: str, severity_basis: dict[str, Any]) -> None:
        alerts.append({"code": code, "title": title, "detail": detail,
                       "severity": severity_basis["severity"], "severity_basis": severity_basis})
    if revenue_yoy is not None and revenue_yoy > 0 and current_yoy["ex_net_profit"] is not None and current_yoy["ex_net_profit"] < 0:
        basis = classify_alert_severity("revenue_profit_divergence", revenue_yoy=revenue_yoy, ex_net_profit_yoy=current_yoy["ex_net_profit"])
        alert("revenue_up_profit_down", "收入增长但扣非利润下降", f"最新累计营收同比 {revenue_yoy:.1f}%，扣非利润同比 {current_yoy['ex_net_profit']:.1f}%，利润相对营收增速差 {basis['growth_gap_pct']:.1f}pct；{_high_severity_threshold_note(basis)}", basis)
    if current_yoy["ex_net_profit"] is not None and current_yoy["ex_net_profit"] > 0 and current_yoy["ocf"] is not None and current_yoy["ocf"] < 0:
        basis = classify_alert_severity("profit_cash_divergence", ex_net_profit_yoy=current_yoy["ex_net_profit"], ocf_yoy=current_yoy["ocf"], ttm_ocf=ttm["ocf"])
        alert("profit_up_ocf_down", "扣非利润改善但经营现金流下降", f"扣非利润同比 {current_yoy['ex_net_profit']:.1f}%，CFO 同比 {current_yoy['ocf']:.1f}%，增速差 {basis['metrics']['growth_gap_pct']:.1f}pct；{_high_severity_threshold_note(basis)}", basis)
    if receivable_gap is not None and receivable_gap > 15:
        basis = classify_alert_severity("working_capital_gap", growth_gap_pct=receivable_gap)
        alert("receivables_growth_gap", "应收账款增长明显快于营收", f"应收增速较营收高 {receivable_gap:.1f}pct；{_high_severity_threshold_note(basis)}", basis)
    if inventory_gap is not None and inventory_gap > 15:
        basis = classify_alert_severity("working_capital_gap", growth_gap_pct=inventory_gap)
        alert("inventory_growth_gap", "存货增长明显快于营收", f"存货增速较营收高 {inventory_gap:.1f}pct；{_high_severity_threshold_note(basis)}", basis)
    if debt_change is not None and debt_change >= 3:
        basis = classify_alert_severity("leverage", debt_change_pct=debt_change, fcf_margin_pct=ttm_margin)
        detail = f"较去年同季上升 {debt_change:.1f}pct"
        if ttm_margin is not None:
            detail += f"，TTM FCF Margin {ttm_margin:.1f}%"
        alert("debt_ratio_rising", "资产负债率明显上升", f"{detail}；{_high_severity_threshold_note(basis)}", basis)
    if ttm_margin is not None and ttm_margin < 0:
        basis = classify_alert_severity("fcf_margin", fcf_margin_pct=ttm_margin)
        alert("ttm_fcf_negative", "TTM 自由现金流为负", f"TTM FCF Margin 为 {ttm_margin:.1f}%；{_high_severity_threshold_note(basis)}", basis)
    evaluated_severities = [str(item["severity"]) for item in alerts]
    aggregate_severity = aggregate_alert_severity(evaluated_severities)
    if aggregate_severity == "high" and all(item["severity"] == "watch" for item in alerts) and len(alerts) >= 3:
        alert("multiple_medium_risks", "多项中度季度风险叠加", f"同时触发 {len(alerts)} 项普通预警，组合升级为高严重度", {"severity": "high", "rule": "three_watch_alerts", "metrics": {"watch_alert_count": float(len(alerts))}, "thresholds": {"high_watch_alert_count_gte": 3.0}})

    def dimension(code: str, title: str, required: tuple[Any, ...], watch: bool, improving: bool, detail: str) -> dict[str, Any]:
        available = all(value is not None for value in required)
        return {"code": code, "title": title, "available": available,
                "status": "unavailable" if not available else "watch" if watch else "improving" if improving else "stable",
                "detail": detail if available else "评分所需季度数据不足"}

    gross_now, gross_prior = _metric(latest, "gross_margin"), _metric(prior_quarter, "gross_margin")
    net_now, net_prior = _metric(latest, "net_margin"), _metric(prior_quarter, "net_margin")
    def below(value: float | None, threshold: float) -> bool: return value is not None and value < threshold
    def above(value: float | None, threshold: float) -> bool: return value is not None and value > threshold
    def show(value: float | None) -> str: return f"{value:.1f}" if value is not None else "—"
    profit_watch = (gross_prior is not None and below(gross_now, gross_prior - 2)) or (net_prior is not None and below(net_now, net_prior - 2))
    profit_improve = gross_prior is not None and net_prior is not None and above(gross_now, gross_prior + 2) and above(net_now, net_prior + 2)
    dimensions = [
        dimension("growth", "核心增长质量", (revenue_yoy, current_yoy["ex_net_profit"]), above(revenue_yoy, 0) and below(current_yoy["ex_net_profit"], 0), above(revenue_yoy, 0) and above(current_yoy["ex_net_profit"], 0), f"累计营收同比 {show(revenue_yoy)}%；扣非利润同比 {show(current_yoy['ex_net_profit'])}%"),
        dimension("profitability", "盈利能力", (gross_now, gross_prior, net_now, net_prior), profit_watch, profit_improve, f"毛利率 {show(gross_now)}%；净利率 {show(net_now)}%"),
        dimension("cash", "现金含金量", (ttm_margin,), below(ttm_margin, 0), ttm_margin is not None and ttm_margin >= 5, f"TTM FCF Margin {show(ttm_margin)}%"),
        dimension("working_capital", "营运资本", (receivable_gap, inventory_gap), above(receivable_gap, 15) or above(inventory_gap, 15), receivable_gap is not None and inventory_gap is not None and receivable_gap <= -5 and inventory_gap <= -5, f"应收增速差 {show(receivable_gap)}pct；存货增速差 {show(inventory_gap)}pct"),
        dimension("reinvestment", "再投资效率", (current_yoy["capex"], revenue_yoy, ttm_margin), above(current_yoy["capex"], 20) and below(revenue_yoy, 5) and below(ttm_margin, 0), ttm_margin is not None and revenue_yoy is not None and ttm_margin >= 5 and revenue_yoy > 0, f"TTM FCF Margin {show(ttm_margin)}%；累计 CapEx 同比 {show(current_yoy['capex'])}%"),
        dimension("financial_risk", "财务风险", (debt_change, ttm_margin), debt_change is not None and ttm_margin is not None and (debt_change >= 3 or ttm_margin < 0), debt_change is not None and ttm_margin is not None and debt_change <= -3 and ttm_margin >= 0, f"资产负债率较去年同季 {show(debt_change)}pct"),
    ]
    weights = {"growth": 20, "profitability": 20, "cash": 20, "working_capital": 15, "reinvestment": 10, "financial_risk": 15}
    status_ratio = {"improving": 1.0, "stable": 0.6, "watch": 0.25}
    coverage_weight = sum(weights[item["code"]] for item in dimensions if item["available"])
    score = round(sum(weights[item["code"]] * status_ratio[item["status"]] for item in dimensions if item["available"]) / coverage_weight * 100) if coverage_weight >= 85 else None
    realtime_score = {"score": score, "weight": 100, "coverage_weight": coverage_weight,
                      "status": "complete" if coverage_weight == 100 else "partial" if score is not None else "insufficient",
                      "reason": None if score is not None else "quarterly_score_coverage_insufficient",
                      "version": "quarterly-v1", "breakdown": [{"code": item["code"], "title": item["title"], "weight": weights[item["code"]], "status": item["status"], "available": item["available"], "points": round(weights[item["code"]] * status_ratio[item["status"]], 1) if item["available"] else None} for item in dimensions]}
    return {"status": "available", "reason": None, "latest_period": period, "as_of": latest.get("report_date"), "basis": "TTM + latest_quarter_balance", "ttm": {**ttm, "fcf_margin": ttm_margin}, "yoy": current_yoy, "latest": {key: _metric(latest, key) for key in BALANCE_FIELDS}, "gaps": {"receivable_growth_gap": receivable_gap, "inventory_growth_gap": inventory_gap, "debt_ratio_change": debt_change}, "dimensions": dimensions, "alerts": alerts, "aggregate_alert_severity": aggregate_severity, "realtime_score": realtime_score}
