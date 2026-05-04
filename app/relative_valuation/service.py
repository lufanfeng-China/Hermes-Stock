from __future__ import annotations

from .classifier import classify_relative_valuation_stock
from .data_loader import (
    load_industry_percentile_sample,
    load_industry_valuation_snapshot,
    load_stock_relative_valuation_inputs,
)
from .history import load_industry_temperature_history
from .labels import classify_percentile_band
from .percentiles import compute_empirical_percentile, should_warn_non_linear_high_percentile_risk


def build_relative_valuation_result(market: str, symbol: str) -> dict[str, object]:
    stock = load_stock_relative_valuation_inputs(market, symbol)
    if not stock:
        return {"ok": False, "error": "stock_not_found", "market": market, "symbol": symbol}

    industry_level_2_name = str(stock.get("industry_level_2_name") or "")
    industry_snapshot = load_industry_valuation_snapshot(industry_level_2_name) or {}
    industry_temperature_history = industry_snapshot.get("temperature_history_since_2022")
    if not isinstance(industry_temperature_history, list):
        industry_temperature_history = load_industry_temperature_history(industry_level_2_name)
    dynamic_threshold = _to_float(industry_snapshot.get("pe_invalid_threshold"))

    classified = classify_relative_valuation_stock(
        ttm_net_profit=_to_float(stock.get("ttm_net_profit")),
        pe_ttm=_to_float(stock.get("pe_ttm")),
        dynamic_pe_invalid_threshold=dynamic_threshold,
        ttm_revenue=_to_float(stock.get("ttm_revenue")),
        revenue_yoy=_to_float(stock.get("revenue_yoy")),
        gross_margin=_to_float(stock.get("gross_margin")),
        book_value_per_share=_to_float(stock.get("book_value_per_share")),
        listed_days=_to_int(stock.get("listed_days")),
    )

    sample_status = str(industry_snapshot.get("sample_status") or "insufficient")
    primary_metric = _resolve_primary_metric(classified.classification, classified.sub_classification)
    primary_value = _to_float(stock.get(primary_metric)) if primary_metric else None

    primary_percentile = None
    valuation_band_label = None
    notes: list[str] = []
    risk_flags: list[str] = []

    if classified.is_new_listing:
        sample_status = "new_listing"
        valuation_band_label = "次新股"
        risk_flags.append("上市未满60个交易日")
    elif sample_status != "ok":
        valuation_band_label = "样本不足"
    elif primary_metric is not None and primary_value is not None:
        sample = load_industry_percentile_sample(
            industry_level_2_name,
            primary_metric,
            classified.classification.value,
            classified.sub_classification.value if classified.sub_classification else None,
        )
        primary_percentile = compute_empirical_percentile(primary_value, sample)
        valuation_band_label = classify_percentile_band(primary_percentile)
        if should_warn_non_linear_high_percentile_risk(primary_percentile):
            risk_flags.append("80%以上分位风险非线性上升")

    if classified.classification.value == "B_THIN_PROFIT_DISTORTED":
        notes.append("PE invalid, fallback to PS percentile")

    temperature_label = industry_snapshot.get("temperature_label")
    if temperature_label in {"行业偏热", "行业过热"}:
        risk_flags.append("行业环境偏热/过热")

    return {
        "ok": True,
        "market": stock.get("market") or market,
        "symbol": stock.get("symbol") or symbol,
        "stock_name": stock.get("stock_name") or symbol,
        "industry_level_1_name": stock.get("industry_level_1_name"),
        "industry_level_2_name": industry_level_2_name,
        "classification": classified.classification.value,
        "sub_classification": classified.sub_classification.value if classified.sub_classification else None,
        "is_new_listing": classified.is_new_listing,
        "sample_status": sample_status,
        "current_price": _to_float(stock.get("current_price")),
        "free_float_market_cap": _to_float(stock.get("free_float_market_cap")),
        "ttm_net_profit": _to_float(stock.get("ttm_net_profit")),
        "ttm_revenue": _to_float(stock.get("ttm_revenue")),
        "revenue_yoy": _to_float(stock.get("revenue_yoy")),
        "gross_margin": _to_float(stock.get("gross_margin")),
        "book_value_per_share": _to_float(stock.get("book_value_per_share")),
        "pe_ttm": _to_float(stock.get("pe_ttm")),
        "ps_ttm": _to_float(stock.get("ps_ttm")),
        "industry_weighted_pe_ttm": _to_float(industry_snapshot.get("weighted_pe_ttm")),
        "industry_weighted_ps_ttm": _to_float(industry_snapshot.get("weighted_ps_ttm")),
        "dynamic_pe_invalid_threshold": dynamic_threshold,
        "industry_temperature_percentile_since_2022": _to_float(industry_snapshot.get("temperature_percentile_since_2022")),
        "industry_temperature_label": temperature_label,
        "industry_temperature_history": industry_temperature_history,
        "industry_valid_member_count": _to_int(industry_snapshot.get("valid_member_count")),
        "primary_percentile_metric": primary_metric,
        "primary_percentile_value": primary_value,
        "primary_percentile": primary_percentile,
        "valuation_band_label": valuation_band_label,
        "notes": notes,
        "risk_flags": risk_flags,
    }


def _resolve_primary_metric(classification, sub_classification) -> str | None:
    if classification.value == "A_NORMAL_EARNING":
        return "pe_ttm"
    if classification.value == "B_THIN_PROFIT_DISTORTED":
        return "ps_ttm"
    if sub_classification is None:
        return None
    if sub_classification.value in {"C1_REVENUE_LOSS", "C2_GROWTH_LOSS"}:
        return "ps_ttm"
    return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
