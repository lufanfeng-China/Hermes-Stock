"""
Valuation models ported from FinanceToolkit (JerBouma/FinanceToolkit).
All calculations are pure functions that take pandas Series or floats.
Adapted for A-share data from Project-Hermes-Stock financial data pipeline.
"""
from __future__ import annotations

import math
from typing import Optional


def safe_div(a: Optional[float], b: Optional[float], default: float = 0) -> float:
    """Safe division, returns default if divisor is zero or None."""
    if a is None or b is None or b == 0:
        return default
    return a / b


# ──────────────────────────────────────────────────────────────
#  DCF Intrinsic Value
# ──────────────────────────────────────────────────────────────

def calc_intrinsic_value_dcf(
    free_cash_flow: float,
    growth_rate: float,
    perpetual_growth_rate: float,
    wacc: float,
    cash_and_equivalents: float,
    total_debt: float,
    shares_outstanding: float,
    periods: int = 5,
) -> dict:
    """
    DCF (Discounted Cash Flow) intrinsic value per share.

    Args:
        free_cash_flow: Current free cash flow (亿元)
        growth_rate: Expected annual growth rate (e.g. 0.08)
        perpetual_growth_rate: Terminal growth rate (e.g. 0.03)
        wacc: Weighted Average Cost of Capital (e.g. 0.09)
        cash_and_equivalents: Cash + short-term investments (亿元)
        total_debt: Total debt (亿元)
        shares_outstanding: Total shares outstanding (亿股)
        periods: Projection periods (default 5)
    """
    if wacc <= perpetual_growth_rate or wacc <= 0:
        return {"error": f"WACC ({wacc:.4f}) must be > perpetual growth rate ({perpetual_growth_rate:.4f})"}

    cash_flows = [free_cash_flow]
    for i in range(1, periods + 1):
        if i == 1:
            cash_flows.append(cash_flows[0] * (1 + growth_rate))
        else:
            cash_flows.append(cash_flows[-1] * (1 + growth_rate))

    # Terminal value (Gordon growth perpetuity)
    terminal_value = cash_flows[-1] * (1 + perpetual_growth_rate) / (wacc - perpetual_growth_rate)

    # Present value of all cash flows
    pv_sum = 0
    pv_details = []
    for i, cf in enumerate(cash_flows):
        pv = cf / (1 + wacc) ** (i + 1)
        pv_sum += pv
        pv_details.append({"year": i + 1, "cash_flow": round(cf, 4), "pv": round(pv, 4)})

    # Add terminal value PV
    tv_pv = terminal_value / (1 + wacc) ** (periods + 1)
    pv_details.append({"year": f"Terminal", "cash_flow": round(terminal_value, 4), "pv": round(tv_pv, 4)})

    enterprise_value = pv_sum + tv_pv
    equity_value = enterprise_value + cash_and_equivalents - total_debt
    intrinsic_value_per_share = equity_value / shares_outstanding if shares_outstanding else 0

    return {
        "free_cash_flow": round(free_cash_flow, 2),
        "growth_rate": round(growth_rate, 4),
        "perpetual_growth_rate": round(perpetual_growth_rate, 4),
        "wacc": round(wacc, 4),
        "periods": periods,
        "terminal_value": round(terminal_value, 2),
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "intrinsic_value_per_share": round(intrinsic_value_per_share, 2),
        "pv_details": pv_details,
    }


# ──────────────────────────────────────────────────────────────
#  Gordon Growth Model (Dividend Discount Model)
# ──────────────────────────────────────────────────────────────

def calc_gordon_growth(
    dividends_per_share: float,
    cost_of_equity: float,
    growth_rate: float,
) -> dict:
    """
    Gordon Growth Model (constant growth dividend discount model).

    P = D1 / (r - g)
    where D1 = D0 * (1 + g)
    """
    if cost_of_equity <= growth_rate:
        return {"error": f"Cost of equity ({cost_of_equity:.4f}) must be > growth rate ({growth_rate:.4f})"}

    next_dividend = dividends_per_share * (1 + growth_rate)
    intrinsic_value = next_dividend / (cost_of_equity - growth_rate)

    return {
        "dividends_per_share": round(dividends_per_share, 4),
        "next_dividend": round(next_dividend, 4),
        "cost_of_equity": round(cost_of_equity, 4),
        "growth_rate": round(growth_rate, 4),
        "intrinsic_value": round(intrinsic_value, 2),
    }


# ──────────────────────────────────────────────────────────────
#  WACC (Weighted Average Cost of Capital)
# ──────────────────────────────────────────────────────────────

def calc_cost_of_equity_capm(
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
) -> float:
    """Cost of Equity using CAPM: Re = Rf + β × (Rm - Rf)"""
    return risk_free_rate + beta * market_risk_premium


def calc_cost_of_debt(
    interest_expense: float,
    total_debt: float,
) -> float:
    """Cost of Debt: Rd = Interest Expense / Total Debt"""
    return safe_div(interest_expense, total_debt, 0)


def calc_wacc(
    market_value_equity: float,
    market_value_debt: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
) -> dict:
    """
    Weighted Average Cost of Capital:

    WACC = (E/V) * Re + (D/V) * Rd * (1 - Tc)
    """
    total_value = market_value_equity + market_value_debt
    if total_value <= 0:
        return {"error": "Total value (equity + debt) must be > 0"}

    equity_weight = market_value_equity / total_value
    debt_weight = market_value_debt / total_value
    after_tax_cost_of_debt = cost_of_debt * (1 - tax_rate)
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt

    return {
        "market_value_equity": round(market_value_equity, 2),
        "market_value_debt": round(market_value_debt, 2),
        "total_value": round(total_value, 2),
        "equity_weight": round(equity_weight, 4),
        "debt_weight": round(debt_weight, 4),
        "cost_of_equity": round(cost_of_equity, 4),
        "cost_of_debt": round(cost_of_debt, 4),
        "after_tax_cost_of_debt": round(after_tax_cost_of_debt, 4),
        "tax_rate": round(tax_rate, 4),
        "wacc": round(wacc, 4),
    }


def calc_tax_rate(
    income_tax_expense: float,
    income_before_tax: float,
) -> float:
    """Effective tax rate."""
    if income_before_tax is None or income_before_tax <= 0:
        return 0.25  # default China corporate tax rate
    return max(0, min(income_tax_expense / income_before_tax, 0.5))


# ──────────────────────────────────────────────────────────────
#  Altman Z-Score (for manufacturing companies)
# ──────────────────────────────────────────────────────────────

def calc_altman_z_score(
    current_assets: float,
    current_liabilities: float,
    total_assets: float,
    retained_earnings: float,
    ebit: float,
    market_cap: float,
    total_liabilities: float,
    revenue: float,
) -> dict:
    """
    Altman Z-Score (original 1968 model for public manufacturing firms):

    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5

    where:
        X1 = Working Capital / Total Assets
        X2 = Retained Earnings / Total Assets
        X3 = EBIT / Total Assets
        X4 = Market Value of Equity / Total Liabilities
        X5 = Sales / Total Assets
    """
    if not total_assets or total_assets == 0:
        return {"error": "Total assets must be > 0"}

    working_capital = current_assets - current_liabilities

    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = market_cap / total_liabilities if total_liabilities else 0
    x5 = revenue / total_assets

    z_score = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    # Interpretation
    if z_score > 2.99:
        zone = "Safe (安全区)"
    elif z_score > 1.81:
        zone = "Grey (灰色区)"
    else:
        zone = "Distress (危险区)"

    return {
        "working_capital": round(working_capital, 2),
        "x1_wc_to_ta": round(x1, 4),
        "x2_re_to_ta": round(x2, 4),
        "x3_ebit_to_ta": round(x3, 4),
        "x4_mve_to_tl": round(x4, 4),
        "x5_sales_to_ta": round(x5, 4),
        "z_score": round(z_score, 2),
        "zone": zone,
    }


# ──────────────────────────────────────────────────────────────
#  Piotroski F-Score (0-9)
# ──────────────────────────────────────────────────────────────

def calc_piotroski_f_score(
    # Current period
    net_income: float,
    ocf: float,
    roa: float,
    total_assets: float,
    current_assets: float,
    current_liabilities: float,
    total_liabilities: float,
    shares_outstanding: float,
    gross_margin: float,
    asset_turnover: float,
    # Previous period (same quarter last year)
    prev_net_income: float,
    prev_ocf: float,
    prev_roa: float,
    prev_current_assets: float,
    prev_current_liabilities: float,
    prev_total_liabilities: float,
    prev_total_assets: float,
    prev_shares_outstanding: float,
    prev_gross_margin: float,
    prev_asset_turnover: float,
) -> dict:
    """
    Piotroski F-Score: 9-point fundamental quality score.

    Profitability (4 points):
        1. Net Income > 0
        2. Operating Cash Flow > 0
        3. ROA increased YoY
        4. OCF > Net Income (quality of earnings)

    Leverage/Liquidity (3 points):
        5. Long-term debt ratio decreased
        6. Current ratio increased
        7. No share dilution

    Operating Efficiency (2 points):
        8. Gross margin increased
        9. Asset turnover increased
    """
    criteria = []

    # 1. Net income positive
    p1 = net_income is not None and net_income > 0
    criteria.append({"name": "净利润 > 0", "pass": p1, "value": net_income})

    # 2. Operating cash flow positive
    p2 = ocf is not None and ocf > 0
    criteria.append({"name": "经营现金流 > 0", "pass": p2, "value": ocf})

    # 3. ROA increased
    p3 = roa is not None and prev_roa is not None and roa > prev_roa
    criteria.append({"name": "ROA 同比提升", "pass": p3, "value": f"{roa} vs {prev_roa}"})

    # 4. OCF > Net Income (accruals quality)
    p4 = ocf is not None and net_income is not None and ocf > net_income
    criteria.append({"name": "经营现金流 > 净利润", "pass": p4, "value": f"OCF={ocf}, NI={net_income}"})

    # 5. Long-term debt ratio decreased
    prev_lt_debt_ratio = safe_div(prev_total_liabilities - prev_current_liabilities, prev_total_assets)
    lt_debt_ratio = safe_div(total_liabilities - current_liabilities, total_assets) if total_liabilities is not None and current_liabilities is not None and total_assets is not None else None
    p5 = lt_debt_ratio is not None and prev_lt_debt_ratio is not None and lt_debt_ratio < prev_lt_debt_ratio
    criteria.append({"name": "长期负债率下降", "pass": p5, "value": f"{lt_debt_ratio:.4f} vs {prev_lt_debt_ratio:.4f}" if lt_debt_ratio is not None else None})

    # 6. Current ratio increased
    prev_cr = safe_div(prev_current_assets, prev_current_liabilities)
    cr = safe_div(current_assets, current_liabilities)
    p6 = cr > prev_cr
    criteria.append({"name": "流动比率提升", "pass": p6, "value": f"{cr:.4f} vs {prev_cr:.4f}"})

    # 7. No share dilution
    p7 = shares_outstanding is not None and prev_shares_outstanding is not None and shares_outstanding <= prev_shares_outstanding
    criteria.append({"name": "未增发稀释", "pass": p7, "value": f"{shares_outstanding} vs {prev_shares_outstanding}"})

    # 8. Gross margin increased
    p8 = gross_margin is not None and prev_gross_margin is not None and gross_margin > prev_gross_margin
    criteria.append({"name": "毛利率提升", "pass": p8, "value": f"{gross_margin:.2f}% vs {prev_gross_margin:.2f}%" if gross_margin is not None else None})

    # 9. Asset turnover increased
    p9 = asset_turnover is not None and prev_asset_turnover is not None and asset_turnover > prev_asset_turnover
    criteria.append({"name": "资产周转率提升", "pass": p9, "value": f"{asset_turnover:.4f} vs {prev_asset_turnover:.4f}" if asset_turnover is not None else None})

    total_score = sum(1 for c in criteria if c["pass"])

    # Interpretation
    if total_score >= 8:
        grade = "优秀 (8-9)"
    elif total_score >= 6:
        grade = "良好 (6-7)"
    elif total_score >= 3:
        grade = "一般 (3-5)"
    else:
        grade = "差 (0-2)"

    return {
        "total_score": total_score,
        "grade": grade,
        "criteria": criteria,
    }


# ──────────────────────────────────────────────────────────────
#  DuPont Analysis
# ──────────────────────────────────────────────────────────────

def calc_dupont_analysis(
    net_income: float,
    revenue: float,
    total_assets: float,
    total_equity: float,
    ebit: float = None,
    income_before_tax: float = None,
) -> dict:
    """
    Extended DuPont Analysis decomposes ROE into 5 factors:

    ROE = Tax Burden × Interest Burden × Operating Margin × Asset Turnover × Equity Multiplier
    """
    if not total_equity or total_equity <= 0:
        return {"error": "Total equity must be > 0"}

    roe = net_income / total_equity
    net_profit_margin = safe_div(net_income, revenue)
    asset_turnover = safe_div(revenue, total_assets)
    equity_multiplier = safe_div(total_assets, total_equity)

    # Basic DuPont
    basic_roe = net_profit_margin * asset_turnover * equity_multiplier

    result = {
        "roe": round(roe, 4),
        "net_profit_margin": round(net_profit_margin, 4),
        "asset_turnover": round(asset_turnover, 4),
        "equity_multiplier": round(equity_multiplier, 4),
        "basic_dupont_roe": round(basic_roe, 4),
    }

    # Extended DuPont (5-factor)
    if ebit is not None and income_before_tax is not None and revenue and revenue > 0:
        tax_burden = safe_div(net_income, income_before_tax)
        interest_burden = safe_div(income_before_tax, ebit)
        operating_margin = safe_div(ebit, revenue)

        result["tax_burden"] = round(tax_burden, 4)
        result["interest_burden"] = round(interest_burden, 4)
        result["operating_margin"] = round(operating_margin, 4)
        result["extended_dupont_roe"] = round(tax_burden * interest_burden * operating_margin * asset_turnover * equity_multiplier, 4)

    return result


# ──────────────────────────────────────────────────────────────
#  Enterprise Value Breakdown
# ──────────────────────────────────────────────────────────────

def calc_enterprise_value_breakdown(
    market_cap: float,
    total_debt: float,
    cash_and_equivalents: float,
    preferred_equity: float = 0,
    minority_interest: float = 0,
) -> dict:
    """
    Enterprise Value = Market Cap + Total Debt + Preferred Equity + Minority Interest - Cash
    """
    ev = market_cap + total_debt + preferred_equity + minority_interest - cash_and_equivalents

    return {
        "market_cap": round(market_cap, 2),
        "total_debt": round(total_debt, 2),
        "cash_and_equivalents": round(cash_and_equivalents, 2),
        "preferred_equity": round(preferred_equity, 2),
        "minority_interest": round(minority_interest, 2),
        "enterprise_value": round(ev, 2),
    }
