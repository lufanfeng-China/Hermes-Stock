"""Shared, auditable cells for industry peer metric snapshots."""
from __future__ import annotations

from typing import Any

POINT_IN_TIME_METRICS = {"debt_ratio", "goodwill", "accounts_receivable", "inventory"}
DERIVED_CHANGE_METRICS = {
    "revenue_growth", "accounts_receivable_growth_gap", "inventory_growth_gap",
}
CASH_PROFIT_RATIO = "cash_profit_ratio"
SUPPORTED_METRICS = {
    "revenue", "net_profit", "ex_net_profit", "gross_margin", "net_margin", "roe_ex",
    "debt_ratio", "ocf", "free_cf", "capex", "goodwill", "accounts_receivable", "inventory",
    CASH_PROFIT_RATIO, "fcf_margin", "capex_intensity", *DERIVED_CHANGE_METRICS,
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _growth(current: float | None, prior: float | None, *, economically_comparable: bool = True) -> float | None:
    if not economically_comparable or current is None or prior is None or prior == 0:
        return None
    return round((current / prior - 1) * 100, 4)


def _percentage_point_change(current: float | None, prior: float | None, *, economically_comparable: bool = True) -> float | None:
    if not economically_comparable or current is None or prior is None:
        return None
    return round(current - prior, 4)


def _period_rows(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("period")): row for row in reports if isinstance(row, dict) and row.get("period")}


def _raw_metric_value(row: dict[str, Any] | None, metric: str) -> float | None:
    return _number(((row or {}).get("metrics") or {}).get(metric))


def _metric_value(row: dict[str, Any] | None, metric: str) -> float | None:
    metrics = (row or {}).get("metrics", {})
    revenue = _number(metrics.get("revenue"))
    if metric == CASH_PROFIT_RATIO:
        ocf, profit = _number(metrics.get("ocf")), _number(metrics.get("ex_net_profit"))
        return ocf / profit if ocf is not None and profit not in (None, 0) else None
    if metric == "fcf_margin":
        free_cf = _number(metrics.get("free_cf"))
        return free_cf / revenue * 100 if free_cf is not None and revenue not in (None, 0) else None
    if metric == "capex_intensity":
        capex = _number(metrics.get("capex"))
        return capex / revenue * 100 if capex is not None and revenue not in (None, 0) else None
    return _number(metrics.get(metric))


def _period_change(rows: dict[str, dict[str, Any]], period: str | None, metric: str) -> float | None:
    if not period:
        return None
    prior = f"{int(period[:4]) - 1}{period[4:]}"
    return _growth(_raw_metric_value(rows.get(period), metric), _raw_metric_value(rows.get(prior), metric))


def _derived_change_value(rows: dict[str, dict[str, Any]], period: str | None, metric: str) -> float | None:
    revenue_yoy = _period_change(rows, period, "revenue")
    if metric == "revenue_growth":
        return revenue_yoy
    base_metric = "accounts_receivable" if metric == "accounts_receivable_growth_gap" else "inventory"
    component_yoy = _period_change(rows, period, base_metric)
    return round(component_yoy - revenue_yoy, 4) if component_yoy is not None and revenue_yoy is not None else None


def _ttm_value(rows: dict[str, dict[str, Any]], period: str, metric: str) -> float | None:
    year, suffix = int(period[:4]), period[4:]
    current, annual, prior = rows.get(period), rows.get(f"{year - 1}A"), rows.get(f"{year - 1}{suffix}")
    if metric == CASH_PROFIT_RATIO:
        ocf = [_raw_metric_value(item, "ocf") for item in (current, annual, prior)]
        profit = [_raw_metric_value(item, "ex_net_profit") for item in (current, annual, prior)]
        if not all(value is not None for value in (*ocf, *profit)):
            return None
        numerator = ocf[0] + ocf[1] - ocf[2]
        denominator = profit[0] + profit[1] - profit[2]
        return round(numerator / denominator, 10) if denominator != 0 else None
    if metric in {"fcf_margin", "capex_intensity"}:
        numerator_metric = "free_cf" if metric == "fcf_margin" else "capex"
        numerators = [_raw_metric_value(item, numerator_metric) for item in (current, annual, prior)]
        revenues = [_raw_metric_value(item, "revenue") for item in (current, annual, prior)]
        if not all(value is not None for value in (*numerators, *revenues)):
            return None
        denominator = revenues[0] + revenues[1] - revenues[2]
        return round((numerators[0] + numerators[1] - numerators[2]) / denominator * 100, 10) if denominator != 0 else None
    values = [_metric_value(item, metric) for item in (current, annual, prior)]
    return round(values[0] + values[1] - values[2], 10) if all(value is not None for value in values) else None


def _cell(period: str | None, value: float | None, yoy_value: float | None, basis: str) -> dict[str, Any]:
    return {"period": period, "value": value, "yoy_value": yoy_value, "basis": basis}


def build_metric_cells(reports: list[dict[str, Any]], metric: str) -> dict[str, dict[str, Any]]:
    """Return annual, latest-quarter and TTM cells under one explicit metric contract."""
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"unsupported industry peer metric: {metric}")
    rows = _period_rows(reports)
    annuals = sorted(period for period in rows if period.endswith("A"))
    quarters = sorted(period for period in rows if len(period) == 6 and period[4:] in {"Q1", "Q2", "Q3"})
    annual_period = annuals[-1] if annuals else None
    quarter_period = quarters[-1] if quarters else None

    if metric in DERIVED_CHANGE_METRICS:
        annual = _cell(annual_period, _derived_change_value(rows, annual_period, metric), None, "annual_derived_change")
        quarter = _cell(quarter_period, _derived_change_value(rows, quarter_period, metric), None, "quarter_cumulative_derived_change")
        ttm = {"period": quarter_period, "value": None, "yoy_value": None, "basis": "not_applicable", "reason": "derived_change_metric"}
        return {"annual": annual, "quarter": quarter, "ttm": ttm}

    annual_value = _metric_value(rows.get(annual_period), metric) if annual_period else None
    quarter_value = _metric_value(rows.get(quarter_period), metric) if quarter_period else None
    annual_prior = f"{int(annual_period[:4]) - 1}A" if annual_period else None
    quarter_prior = f"{int(quarter_period[:4]) - 1}{quarter_period[4:]}" if quarter_period else None
    comparable = metric != CASH_PROFIT_RATIO or all(
        (_raw_metric_value(rows.get(period), "ex_net_profit") or 0) > 0
        for period in (annual_period, annual_prior, quarter_period, quarter_prior) if period
    )
    change_fn = _percentage_point_change if metric in {"fcf_margin", "capex_intensity"} else _growth
    annual = _cell(annual_period, annual_value, change_fn(annual_value, _metric_value(rows.get(annual_prior), metric), economically_comparable=comparable), "annual")
    quarter = _cell(quarter_period, quarter_value, change_fn(quarter_value, _metric_value(rows.get(quarter_prior), metric), economically_comparable=comparable), "quarter_cumulative")
    if metric in POINT_IN_TIME_METRICS:
        ttm = {"period": quarter_period, "value": None, "yoy_value": None, "basis": "not_applicable", "reason": "point_in_time_metric"}
    else:
        ttm_value = _ttm_value(rows, quarter_period, metric) if quarter_period else None
        previous_ttm = _ttm_value(rows, f"{int(quarter_period[:4]) - 1}{quarter_period[4:]}", metric) if quarter_period else None
        ttm = _cell(quarter_period, ttm_value, change_fn(ttm_value, previous_ttm, economically_comparable=comparable), "ttm")
    return {"annual": annual, "quarter": quarter, "ttm": ttm}


def build_industry_metric_rows(
    reports_by_stock: dict[tuple[str, str], dict[str, Any]],
    metric_code: str,
    *,
    current_stock: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Materialize identity-preserving peer rows without omitting unavailable members."""
    if metric_code not in SUPPORTED_METRICS:
        raise ValueError(f"unsupported industry peer metric: {metric_code}")
    rows: list[dict[str, Any]] = []
    for (market, symbol), member in sorted(reports_by_stock.items()):
        reports = member.get("reports") if isinstance(member, dict) else None
        reports = reports if isinstance(reports, list) else []
        metrics = build_metric_cells(reports, metric_code)
        available = any(cell.get("value") is not None for cell in metrics.values())
        rows.append({
            "market": str(market).lower(),
            "symbol": str(symbol).zfill(6),
            "stock_name": str(member.get("stock_name") or str(symbol)) if isinstance(member, dict) else str(symbol),
            "industry_level_2": member.get("industry_level_2") if isinstance(member, dict) else None,
            "is_current_stock": (market, symbol) == current_stock,
            "metrics": metrics,
            "available": available,
            "unavailable_reason": None if available else "metric_data_unavailable",
        })
    return rows
