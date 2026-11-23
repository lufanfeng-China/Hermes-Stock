"""Assemble sector-health model inputs from TDX annual rows and PDF evidence."""

from __future__ import annotations

import math
import statistics
from typing import Mapping, Sequence


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _finite(row.get(name))
        if value is not None and value > 0:
            return value
    return None


def _first_finite(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _finite(row.get(name))
        if value is not None:
            return value
    return None


def _metric(evidence: Mapping[str, object], name: str) -> float | None:
    metrics = evidence.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    item = metrics.get(name)
    if not isinstance(item, Mapping):
        return None
    quality = _finite(item.get("quality"))
    if quality is None or quality < 80:
        return None
    return _finite(item.get("value"))


def _revenue(row: Mapping[str, object]) -> float | None:
    return _positive(row, "其中：营业收入", "营业收入")


def _profit(row: Mapping[str, object]) -> float | None:
    return _first_finite(row, "归属于母公司所有者的净利润", "净利润")


def _path(values: Sequence[float | None], *, profit: bool = False) -> str:
    if len(values) != 5 or any(value is None for value in values):
        return "unavailable"
    series = [float(value) for value in values if value is not None]
    if profit and series[-1] <= 0:
        return "latest_loss"
    if profit and any(value <= 0 for value in series):
        return "loss_history"
    deltas = [series[index] - series[index - 1] for index in range(1, len(series))]
    if all(delta > 0 for delta in deltas):
        return "profitable_growth" if profit else "continuous_growth"
    if series[-1] > series[0]:
        return "profitable_volatile" if profit else "overall_growth"
    if max(series) > 0 and (max(series) - min(series)) / max(series) <= 0.15:
        return "profitable_volatile" if profit else "stable"
    return "decline"


def _impairment_ratio(row: Mapping[str, object]) -> float | None:
    impairment_wan = _positive(row, "信用减值损失(万元)", "信用减值损失(万元、2019格式)")
    revenue = _revenue(row)
    if impairment_wan is None or revenue is None:
        return None
    return abs(impairment_wan * 10000.0 / revenue * 100.0)


def _reserve_status(rows: Sequence[Mapping[str, object]]) -> str | None:
    ratios: list[float] = []
    for row in rows:
        reserve = _positive(row, "一般风险准备(金融类)")
        equity = _positive(row, "归属于母公司股东权益(资产负债表)")
        if reserve is None or equity is None:
            return None
        ratios.append(reserve / equity)
    if ratios[-1] >= 0.08 and ratios[-1] >= ratios[0] * 0.95:
        return "high_stable"
    if ratios[-1] >= ratios[0] * 0.9:
        return "stable"
    return "declining"


def build_bank_metrics(
    annual_rows: Sequence[Mapping[str, object]],
    annual_evidence: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if len(annual_rows) != 5 or len(annual_evidence) != 5:
        return {}
    latest_row, previous_row = annual_rows[-1], annual_rows[-2]
    latest, previous = annual_evidence[-1], annual_evidence[-2]
    assets = [_positive(row, "资产总计") for row in annual_rows]
    profits = [_profit(row) for row in annual_rows]
    revenues = [_revenue(row) for row in annual_rows]
    latest_profit = profits[-1]
    average_assets = None
    if assets[-1] is not None and assets[-2] is not None:
        average_assets = (float(assets[-1]) + float(assets[-2])) / 2.0
    roa = (float(latest_profit) / average_assets * 100.0
           if latest_profit is not None and average_assets and average_assets > 0 else None)
    latest_npl = _metric(latest, "npl_ratio")
    previous_npl = _metric(previous, "npl_ratio")
    latest_provision = _metric(latest, "provision_coverage_ratio")
    previous_provision = _metric(previous, "provision_coverage_ratio")
    return {
        "npl_ratio": latest_npl,
        "provision_coverage_ratio": latest_provision,
        "npl_yoy_change_pp": (latest_npl - previous_npl if latest_npl is not None and previous_npl is not None else None),
        "provision_yoy_change_pp": (latest_provision - previous_provision
                                     if latest_provision is not None and previous_provision is not None else None),
        "cet1_ratio": _metric(latest, "cet1_ratio"),
        "tier1_ratio": _metric(latest, "tier1_ratio"),
        "capital_adequacy_ratio": _metric(latest, "capital_adequacy_ratio"),
        "roe": _first_finite(latest_row, "加权净资产收益率(每股指标)", "净资产收益率"),
        "roa": roa,
        "net_interest_margin": _metric(latest, "net_interest_margin"),
        "cost_income_ratio": _metric(latest, "cost_income_ratio"),
        "liquidity_coverage_ratio": _metric(latest, "liquidity_coverage_ratio"),
        "net_stable_funding_ratio": _metric(latest, "net_stable_funding_ratio"),
        "revenue_path": _path(revenues),
        "profit_path": _path(profits, profit=True),
        "credit_impairment_revenue_pct": _impairment_ratio(latest_row),
        "risk_reserve_status": _reserve_status(annual_rows),
    }


def build_securities_metrics(
    annual_rows: Sequence[Mapping[str, object]],
    annual_evidence: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if len(annual_rows) != 5 or len(annual_evidence) != 5:
        return {}
    latest_row, previous_row = annual_rows[-1], annual_rows[-2]
    latest, previous = annual_evidence[-1], annual_evidence[-2]
    revenue = _revenue(latest_row)
    equity = _positive(latest_row, "归属于母公司股东权益(资产负债表)")
    net_capital = _metric(latest, "net_capital")
    business_fields = (
        "brokerage_net_revenue",
        "investment_banking_net_revenue",
        "asset_management_net_revenue",
    )
    latest_business = [_metric(latest, field) for field in business_fields]
    first_business = [_metric(annual_evidence[0], field) for field in business_fields]
    business_complete = all(value is not None and value > 0 for value in latest_business)
    latest_business_sum = sum(float(value) for value in latest_business if value is not None)
    first_business_sum = sum(float(value) for value in first_business if value is not None)
    largest_share = (max(float(value) for value in latest_business if value is not None) / latest_business_sum * 100.0
                     if business_complete and latest_business_sum > 0 else None)
    if latest_business_sum > first_business_sum * 1.05 > 0:
        fee_trend = "growth"
    elif latest_business_sum >= first_business_sum * 0.9 > 0:
        fee_trend = "stable"
    else:
        fee_trend = "decline" if first_business_sum > 0 else None

    proprietary_ratios: list[float] = []
    for row in annual_rows:
        row_revenue = _revenue(row)
        investment = _finite(row.get("投资收益")) or 0.0
        fair_value = _finite(row.get("加：公允价值变动净收益"))
        if fair_value is None:
            loss = _finite(row.get("公允价值变动损失"))
            fair_value = -loss if loss is not None else 0.0
        if row_revenue and row_revenue > 0:
            proprietary_ratios.append((investment + fair_value) / row_revenue * 100.0)
    proprietary_ratio = proprietary_ratios[-1] if len(proprietary_ratios) == 5 else None
    volatility = None
    if len(proprietary_ratios) == 5:
        std = statistics.pstdev(proprietary_ratios)
        volatility = "low" if std <= 10 else "medium" if std <= 25 else "high"

    trading_assets = _positive(latest_row, "交易性金融资产")
    trading_assets_ratio = trading_assets / equity * 100.0 if trading_assets and equity else None
    profits = [_profit(row) for row in annual_rows]
    impairment_ratio = _impairment_ratio(latest_row)
    current_margin = _metric(latest, "margin_financing_balance")
    previous_margin = _metric(previous, "margin_financing_balance")
    current_impairment = _impairment_ratio(latest_row)
    previous_impairment = _impairment_ratio(previous_row)
    margin_growth = ((current_margin / previous_margin - 1.0) if current_margin and previous_margin else None)
    impairment_growth = ((current_impairment / previous_impairment - 1.0)
                         if current_impairment is not None and previous_impairment else None)
    if margin_growth is not None and impairment_growth is not None and margin_growth > 0.2 and impairment_growth > 0.2:
        margin_risk = "both_rising"
    elif ((margin_growth is not None and margin_growth > 0.2)
          or (impairment_growth is not None and impairment_growth > 0.2)):
        margin_risk = "one_rising"
    else:
        margin_risk = "stable" if margin_growth is not None and impairment_growth is not None else None

    return {
        "risk_coverage_ratio": _metric(latest, "risk_coverage_ratio"),
        "capital_leverage_ratio": _metric(latest, "capital_leverage_ratio"),
        "net_capital_to_net_assets_pct": (net_capital / equity * 100.0 if net_capital and equity else None),
        "business_line_coverage": "complete" if business_complete else None,
        "largest_business_share_pct": largest_share,
        "fee_income_trend": fee_trend,
        "proprietary_income_revenue_pct": proprietary_ratio,
        "trading_assets_to_equity_pct": trading_assets_ratio,
        "proprietary_volatility": volatility,
        "roe": _first_finite(latest_row, "加权净资产收益率(每股指标)", "净资产收益率"),
        "profit_path": _path(profits, profit=True),
        "liquidity_coverage_ratio": _metric(latest, "liquidity_coverage_ratio"),
        "net_stable_funding_ratio": _metric(latest, "net_stable_funding_ratio"),
        "credit_impairment_revenue_pct": impairment_ratio,
        "margin_financing_risk": margin_risk,
    }
