"""Sector-specific annual health scoring for listed banks and securities firms."""

from __future__ import annotations

import math
from typing import Callable, Mapping


def _number(metrics: Mapping[str, object], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _band_high(value: float, bands: list[tuple[float, float]], default: float = 0.0) -> float:
    for threshold, score in bands:
        if value >= threshold:
            return score
    return default


def _band_low(value: float, bands: list[tuple[float, float]], default: float = 0.0) -> float:
    for threshold, score in bands:
        if value <= threshold:
            return score
    return default


def _dimension(
    metrics: Mapping[str, object],
    *,
    name: str,
    weight: float,
    required: tuple[str, ...],
    scorer: Callable[[], float],
) -> dict[str, object]:
    missing = [key for key in required if _number(metrics, key) is None and metrics.get(key) is None]
    if missing:
        return {"name": name, "max_score": weight, "score": None, "status": "unavailable", "missing_fields": missing}
    return {"name": name, "max_score": weight, "score": round(float(scorer()), 2), "status": "available", "missing_fields": []}


def _result(
    *,
    model_type: str,
    score_version: str,
    comparability: str,
    dimensions: dict[str, dict[str, object]],
    core_families: tuple[str, ...],
    red_flags: list[dict[str, object]],
) -> dict[str, object]:
    coverage = sum(float(item["max_score"]) for item in dimensions.values() if item["status"] == "available")
    unavailable_core = [name for name in core_families if dimensions[name]["status"] != "available"]
    eligible = coverage >= 85.0 and not unavailable_core
    score = round(sum(float(item["score"]) for item in dimensions.values() if item["score"] is not None), 2) if eligible else None
    return {
        "model_type": model_type,
        "score_version": score_version,
        "score_comparability": comparability,
        "score": score,
        "coverage_weight": round(coverage, 2),
        "status": "ready" if eligible else "insufficient_evidence",
        "dimensions": dimensions,
        "unavailable_core_families": unavailable_core,
        "red_flags": red_flags,
    }


def score_bank_health(metrics: Mapping[str, object]) -> dict[str, object]:
    npl = _number(metrics, "npl_ratio")
    provision = _number(metrics, "provision_coverage_ratio")
    npl_change = _number(metrics, "npl_yoy_change_pp")
    provision_change = _number(metrics, "provision_yoy_change_pp")
    cet1 = _number(metrics, "cet1_ratio")
    tier1 = _number(metrics, "tier1_ratio")
    car = _number(metrics, "capital_adequacy_ratio")
    roe = _number(metrics, "roe")
    roa = _number(metrics, "roa")
    nim = _number(metrics, "net_interest_margin")
    cost_income = _number(metrics, "cost_income_ratio")
    lcr = _number(metrics, "liquidity_coverage_ratio")
    nsfr = _number(metrics, "net_stable_funding_ratio")
    impairment = _number(metrics, "credit_impairment_revenue_pct")

    dimensions = {
        "asset_quality": _dimension(metrics, name="资产质量", weight=25, required=("npl_ratio", "provision_coverage_ratio", "npl_yoy_change_pp", "provision_yoy_change_pp"), scorer=lambda: (
            _band_low(npl, [(1.0, 10), (1.5, 8), (2.0, 5), (3.0, 2)])
            + _band_high(provision, [(300, 8), (200, 6), (150, 4), (100, 2)])
            + _band_low(npl_change, [(-0.05, 4), (0.05, 3), (0.15, 1)])
            + _band_high(provision_change, [(0, 3), (-20, 2), (-50, 1)])
        )),
        "capital_adequacy": _dimension(metrics, name="资本充足", weight=20, required=("cet1_ratio", "tier1_ratio", "capital_adequacy_ratio"), scorer=lambda: (
            _band_high(cet1, [(12, 10), (10.5, 8), (9, 6), (7.5, 3)])
            + _band_high(tier1, [(13, 4), (11, 3), (9, 2), (7, 1)])
            + _band_high(car, [(15, 6), (13, 5), (11.5, 3), (10.5, 1)])
        )),
        "profitability_efficiency": _dimension(metrics, name="盈利与效率", weight=20, required=("roe", "roa", "net_interest_margin", "cost_income_ratio"), scorer=lambda: (
            _band_high(roe, [(12, 6), (10, 5), (8, 3), (5, 1)])
            + _band_high(roa, [(1.0, 4), (0.8, 3), (0.6, 2), (0.4, 1)])
            + _band_high(nim, [(2.2, 6), (1.8, 5), (1.5, 3), (1.2, 1)])
            + _band_low(cost_income, [(28, 4), (33, 3), (38, 2), (45, 1)])
        )),
        "liquidity_funding": _dimension(metrics, name="流动性与负债稳定", weight=15, required=("liquidity_coverage_ratio", "net_stable_funding_ratio"), scorer=lambda: (
            _band_high(lcr, [(150, 8), (120, 6), (100, 4)])
            + _band_high(nsfr, [(120, 7), (110, 5), (100, 3)])
        )),
        "earnings_stability": _dimension(metrics, name="收入与利润稳定", weight=10, required=("revenue_path", "profit_path"), scorer=lambda: (
            {"continuous_growth": 5, "overall_growth": 4, "stable": 2}.get(str(metrics.get("revenue_path")), 0)
            + {"profitable_growth": 5, "profitable_volatile": 3, "loss_history": 1}.get(str(metrics.get("profit_path")), 0)
        )),
        "risk_buffer": _dimension(metrics, name="风险抵补", weight=10, required=("credit_impairment_revenue_pct", "risk_reserve_status"), scorer=lambda: (
            _band_low(impairment, [(10, 5), (20, 4), (30, 2), (40, 1)])
            + {"high_stable": 5, "stable": 3, "declining": 1}.get(str(metrics.get("risk_reserve_status")), 0)
        )),
    }
    red_flags: list[dict[str, object]] = []
    for triggered, code, label, actual in (
        (npl is not None and npl > 2.0, "high_npl_ratio", "不良贷款率偏高", npl),
        (provision is not None and provision < 150, "low_provision_coverage", "拨备覆盖率偏低", provision),
        (cet1 is not None and cet1 < 9, "low_cet1", "核心一级资本缓冲偏低", cet1),
        (car is not None and car < 11.5, "low_capital_adequacy", "资本充足率缓冲偏低", car),
        (lcr is not None and lcr < 100, "low_liquidity_coverage", "流动性覆盖率低于100%", lcr),
        (nsfr is not None and nsfr < 100, "low_nsfr", "净稳定资金比例低于100%", nsfr),
    ):
        if triggered:
            red_flags.append({"code": code, "label": label, "actual": actual})
    return _result(model_type="bank", score_version="bank-health-v1", comparability="within_bank_only", dimensions=dimensions, core_families=("asset_quality", "capital_adequacy", "profitability_efficiency"), red_flags=red_flags)


def score_securities_health(metrics: Mapping[str, object]) -> dict[str, object]:
    risk_coverage = _number(metrics, "risk_coverage_ratio")
    capital_leverage = _number(metrics, "capital_leverage_ratio")
    net_capital_ratio = _number(metrics, "net_capital_to_net_assets_pct")
    largest_share = _number(metrics, "largest_business_share_pct")
    proprietary_share = _number(metrics, "proprietary_income_revenue_pct")
    trading_assets = _number(metrics, "trading_assets_to_equity_pct")
    roe = _number(metrics, "roe")
    lcr = _number(metrics, "liquidity_coverage_ratio")
    nsfr = _number(metrics, "net_stable_funding_ratio")
    impairment = _number(metrics, "credit_impairment_revenue_pct")

    dimensions = {
        "capital_and_risk_coverage": _dimension(metrics, name="净资本与风险覆盖", weight=25, required=("risk_coverage_ratio", "capital_leverage_ratio", "net_capital_to_net_assets_pct"), scorer=lambda: (
            _band_high(risk_coverage, [(200, 10), (150, 8), (120, 6), (100, 4)])
            + _band_high(capital_leverage, [(15, 8), (12, 6), (10, 4), (8, 2)])
            + _band_high(net_capital_ratio, [(70, 7), (50, 5), (40, 3), (20, 1)])
        )),
        "income_structure": _dimension(metrics, name="收入结构与稳定", weight=20, required=("business_line_coverage", "largest_business_share_pct", "fee_income_trend"), scorer=lambda: (
            {"complete": 8, "partial": 4}.get(str(metrics.get("business_line_coverage")), 0)
            + _band_low(largest_share, [(50, 6), (65, 4), (80, 2)])
            + {"growth": 6, "stable": 4, "decline": 2}.get(str(metrics.get("fee_income_trend")), 0)
        )),
        "market_risk": _dimension(metrics, name="自营与市场风险", weight=20, required=("proprietary_income_revenue_pct", "trading_assets_to_equity_pct", "proprietary_volatility"), scorer=lambda: (
            _band_low(abs(proprietary_share), [(20, 10), (35, 8), (50, 5), (70, 2)])
            + _band_low(trading_assets, [(100, 6), (200, 4), (300, 2)])
            + {"low": 4, "medium": 2}.get(str(metrics.get("proprietary_volatility")), 0)
        )),
        "profitability_efficiency": _dimension(metrics, name="盈利与效率", weight=15, required=("roe", "profit_path"), scorer=lambda: (
            _band_high(roe, [(12, 8), (10, 6), (8, 4), (5, 2)])
            + {"profitable_growth": 7, "profitable_volatile": 5, "loss_history": 2}.get(str(metrics.get("profit_path")), 0)
        )),
        "leverage_liquidity": _dimension(metrics, name="杠杆与流动性", weight=10, required=("liquidity_coverage_ratio", "net_stable_funding_ratio"), scorer=lambda: (
            _band_high(lcr, [(150, 5), (120, 4), (100, 3)])
            + _band_high(nsfr, [(120, 5), (110, 4), (100, 3)])
        )),
        "credit_impairment": _dimension(metrics, name="信用与减值风险", weight=10, required=("credit_impairment_revenue_pct", "margin_financing_risk"), scorer=lambda: (
            _band_low(impairment, [(5, 5), (10, 4), (20, 2), (30, 1)])
            + {"stable": 5, "one_rising": 3}.get(str(metrics.get("margin_financing_risk")), 0)
        )),
    }
    red_flags: list[dict[str, object]] = []
    for triggered, code, label, actual in (
        (risk_coverage is not None and risk_coverage < 120, "low_risk_coverage", "风险覆盖率缓冲偏低", risk_coverage),
        (capital_leverage is not None and capital_leverage < 10, "low_capital_leverage", "资本杠杆率缓冲偏低", capital_leverage),
        (lcr is not None and lcr < 100, "low_liquidity_coverage", "流动性覆盖率低于100%", lcr),
        (nsfr is not None and nsfr < 100, "low_nsfr", "净稳定资金率低于100%", nsfr),
        (proprietary_share is not None and abs(proprietary_share) > 50, "high_proprietary_dependence", "自营收益依赖偏高", proprietary_share),
    ):
        if triggered:
            red_flags.append({"code": code, "label": label, "actual": actual})
    return _result(model_type="securities", score_version="securities-health-v1", comparability="within_securities_only", dimensions=dimensions, core_families=("capital_and_risk_coverage", "leverage_liquidity", "profitability_efficiency"), red_flags=red_flags)


def _quarterly_result(
    *,
    model_type: str,
    score_version: str,
    report_period: str,
    parts: list[tuple[str, float, float | None]],
    core_fields: tuple[str, ...],
    metrics: Mapping[str, object],
    minimum_coverage: float,
    previous_score: float | None,
    comparisons: Mapping[str, object] | None = None,
) -> dict[str, object]:
    coverage = sum(weight for _, weight, score in parts if score is not None)
    missing_core = [field for field in core_fields if _number(metrics, field) is None]
    eligible = coverage >= minimum_coverage and not missing_core
    score = round(sum(float(value) for _, _, value in parts if value is not None), 2) if eligible else None
    if score is None:
        status = "insufficient_evidence"
    elif comparisons:
        comparison_statuses = [
            str(item.get("status")) for item in comparisons.values() if isinstance(item, Mapping)
        ]
        deteriorating = comparison_statuses.count("deteriorating")
        improving = comparison_statuses.count("improving")
        if deteriorating >= 2:
            status = "deteriorating"
        elif deteriorating == 1:
            status = "watch"
        elif improving >= 2:
            status = "improving"
        else:
            status = "stable"
    elif score < 50:
        status = "deteriorating"
    elif previous_score is not None and score <= previous_score - 10:
        status = "deteriorating"
    elif score < 70:
        status = "watch"
    elif previous_score is not None and score >= previous_score + 5:
        status = "improving"
    else:
        status = "stable"
    return {
        "model_type": model_type,
        "score_version": score_version,
        "score_comparability": f"within_{model_type}_same_period_only",
        "report_period": report_period,
        "score": score,
        "status": status,
        "coverage_weight": round(coverage, 2),
        "missing_core_fields": missing_core,
        "parts": {name: {"weight": weight, "score": value} for name, weight, value in parts},
        "previous_score": previous_score,
        "comparisons": dict(comparisons or {}),
    }


def _metric_comparison(
    metrics: Mapping[str, object], previous: Mapping[str, object], year_start: Mapping[str, object],
    field: str, *, lower_better: bool, cumulative: bool, tolerance: float,
) -> dict[str, object]:
    current = _number(metrics, field)
    prior = _number(previous, field)
    start = None if cumulative else _number(year_start, field)
    basis = "yoy_same_period" if cumulative else "year_start_and_yoy"
    required = [prior] if cumulative else [prior, start]
    if current is None:
        return {"basis": basis, "current": None, "previous_same_period": prior, "year_start": start,
                "reference_status": "not_disclosed", "status": "insufficient_evidence"}
    if any(value is None for value in required):
        return {"basis": basis, "current": current, "previous_same_period": prior, "year_start": start,
                "reference_status": "stale_reference", "status": "stale_reference"}
    references = [float(value) for value in required if value is not None]
    signed = [(reference - current) if lower_better else (current - reference) for reference in references]
    if all(delta > tolerance for delta in signed):
        status = "improving"
    elif any(delta < -tolerance for delta in signed):
        status = "deteriorating"
    else:
        status = "stable"
    return {"basis": basis, "current": current, "previous_same_period": prior, "year_start": start,
            "reference_status": "available", "status": status}


def _quarterly_comparisons(
    metrics: Mapping[str, object], previous: Mapping[str, object] | None,
    year_start: Mapping[str, object] | None, definitions: Mapping[str, tuple[bool, bool, float]],
) -> dict[str, object]:
    previous = previous or {}
    year_start = year_start or {}
    return {
        field: _metric_comparison(
            metrics, previous, year_start, field,
            lower_better=lower_better, cumulative=cumulative, tolerance=tolerance,
        )
        for field, (lower_better, cumulative, tolerance) in definitions.items()
    }


def score_bank_quarterly_monitor(
    metrics: Mapping[str, object], *, report_period: str, previous_score: float | None = None,
    previous_metrics: Mapping[str, object] | None = None,
    year_start_metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    npl = _number(metrics, "npl_ratio")
    provision = _number(metrics, "provision_coverage_ratio")
    cet1 = _number(metrics, "cet1_ratio")
    tier1 = _number(metrics, "tier1_ratio")
    car = _number(metrics, "capital_adequacy_ratio")
    nim = _number(metrics, "net_interest_margin")
    cost = _number(metrics, "cost_income_ratio")
    lcr = _number(metrics, "liquidity_coverage_ratio")
    nsfr = _number(metrics, "net_stable_funding_ratio")
    impairment = _number(metrics, "credit_impairment_revenue_pct")
    parts = [
        ("npl_ratio", 12.5, None if npl is None else _band_low(npl, [(1.0, 12.5), (1.5, 10), (2.0, 7), (3.0, 3)])),
        ("provision_coverage_ratio", 12.5, None if provision is None else _band_high(provision, [(300, 12.5), (200, 10), (150, 7), (100, 3)])),
        ("cet1_ratio", 15, None if cet1 is None else _band_high(cet1, [(12, 15), (10.5, 12), (9, 8), (7.5, 4)])),
        ("tier1_ratio", 5, None if tier1 is None else _band_high(tier1, [(13, 5), (11, 4), (9, 2), (7, 1)])),
        ("capital_adequacy_ratio", 10, None if car is None else _band_high(car, [(15, 10), (13, 8), (11.5, 5), (10.5, 2)])),
        ("net_interest_margin", 7.5, None if nim is None else _band_high(nim, [(2.2, 7.5), (1.8, 6), (1.5, 4), (1.2, 2)])),
        ("cost_income_ratio", 7.5, None if cost is None else _band_low(cost, [(28, 7.5), (33, 6), (38, 4), (45, 2)])),
        ("liquidity_coverage_ratio", 10, None if lcr is None else _band_high(lcr, [(150, 10), (120, 8), (100, 5)])),
        ("net_stable_funding_ratio", 10, None if nsfr is None else _band_high(nsfr, [(120, 10), (110, 8), (100, 5)])),
        ("credit_impairment_revenue_pct", 10, None if impairment is None else _band_low(impairment, [(5, 10), (10, 8), (20, 5), (30, 2)])),
    ]
    comparisons = _quarterly_comparisons(metrics, previous_metrics, year_start_metrics, {
        "npl_ratio": (True, False, 0.05),
        "provision_coverage_ratio": (False, False, 5.0),
        "cet1_ratio": (False, False, 0.1),
        "tier1_ratio": (False, False, 0.1),
        "capital_adequacy_ratio": (False, False, 0.1),
        "net_interest_margin": (False, True, 0.05),
        "cost_income_ratio": (True, True, 1.0),
        "liquidity_coverage_ratio": (False, False, 2.0),
        "net_stable_funding_ratio": (False, False, 2.0),
        "credit_impairment_revenue_pct": (True, True, 0.5),
    }) if previous_metrics is not None or year_start_metrics is not None else {}
    return _quarterly_result(
        model_type="bank", score_version="bank-quarterly-v1", report_period=report_period,
        parts=parts, core_fields=("npl_ratio", "provision_coverage_ratio", "cet1_ratio", "capital_adequacy_ratio"),
        metrics=metrics, minimum_coverage=70, previous_score=previous_score, comparisons=comparisons,
    )


def score_securities_quarterly_monitor(
    metrics: Mapping[str, object], *, report_period: str, previous_score: float | None = None,
    previous_metrics: Mapping[str, object] | None = None,
    year_start_metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    risk = _number(metrics, "risk_coverage_ratio")
    leverage = _number(metrics, "capital_leverage_ratio")
    net_capital = _number(metrics, "net_capital_to_net_assets_pct")
    lcr = _number(metrics, "liquidity_coverage_ratio")
    nsfr = _number(metrics, "net_stable_funding_ratio")
    proprietary = _number(metrics, "proprietary_income_revenue_pct")
    margin_balance = _number(metrics, "margin_financing_balance")
    impairment = _number(metrics, "credit_impairment_revenue_pct")
    margin = metrics.get("margin_financing_risk")
    parts = [
        ("risk_coverage_ratio", 20, None if risk is None else _band_high(risk, [(200, 20), (150, 16), (120, 12), (100, 8)])),
        ("capital_leverage_ratio", 15, None if leverage is None else _band_high(leverage, [(15, 15), (12, 12), (10, 8), (8, 4)])),
        ("net_capital_to_net_assets_pct", 10, None if net_capital is None else _band_high(net_capital, [(70, 10), (50, 8), (40, 5), (20, 2)])),
        ("liquidity_coverage_ratio", 10, None if lcr is None else _band_high(lcr, [(150, 10), (120, 8), (100, 5)])),
        ("net_stable_funding_ratio", 10, None if nsfr is None else _band_high(nsfr, [(120, 10), (110, 8), (100, 5)])),
        ("proprietary_income_revenue_pct", 10, None if proprietary is None else _band_low(abs(proprietary), [(20, 10), (35, 8), (50, 5), (70, 2)])),
        ("margin_financing_risk", 15, None if margin is None or margin_balance is None else {"stable": 15, "one_rising": 8, "both_rising": 0}.get(str(margin), 0)),
        ("credit_impairment_revenue_pct", 10, None if impairment is None else _band_low(impairment, [(5, 10), (10, 8), (20, 5), (30, 2)])),
    ]
    comparisons = _quarterly_comparisons(metrics, previous_metrics, year_start_metrics, {
        "risk_coverage_ratio": (False, False, 2.0),
        "capital_leverage_ratio": (False, False, 0.1),
        "net_capital_to_net_assets_pct": (False, False, 1.0),
        "liquidity_coverage_ratio": (False, False, 2.0),
        "net_stable_funding_ratio": (False, False, 2.0),
        "proprietary_income_revenue_pct": (True, True, 1.0),
        "margin_financing_balance": (True, False, 0.0),
        "credit_impairment_revenue_pct": (True, True, 0.5),
    }) if previous_metrics is not None or year_start_metrics is not None else {}
    return _quarterly_result(
        model_type="securities", score_version="securities-quarterly-v1", report_period=report_period,
        parts=parts, core_fields=("risk_coverage_ratio", "capital_leverage_ratio", "liquidity_coverage_ratio", "net_stable_funding_ratio"),
        metrics=metrics, minimum_coverage=75, previous_score=previous_score, comparisons=comparisons,
    )
