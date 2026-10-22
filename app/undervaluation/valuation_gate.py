"""Dual-source valuation-margin gate for the good-stock diagnostic."""
from __future__ import annotations

from typing import Any

LOW_VALUE_PERCENTILE = 30.0
MIN_HISTORY_YEARS = 3
MIN_HISTORY_TRADING_DAYS = 500


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def evaluate_margin_evidence(
    *,
    quality: dict[str, Any] | None,
    industry: dict[str, Any] | None,
    history: dict[str, Any] | None,
) -> dict[str, Any]:
    """Require industry and own-history PE/PS discounts after quality eligibility."""
    quality = quality or {}
    industry = industry or {}
    history = history or {}
    if quality.get("status") != "QUALITY_ELIGIBLE" or not quality.get("eligible"):
        return {
            "version": "good-stock-margin-gate-v1",
            "status": "NOT_EVALUATED",
            "has_margin": False,
            "reasons": ["quality_gate_not_eligible"],
        }

    reasons: list[str] = []
    if industry.get("status") != "AVAILABLE":
        reasons.append("industry_valuation_unavailable")
    if history.get("status") != "AVAILABLE":
        reasons.append("own_history_valuation_unavailable")
    if reasons:
        return {
            "version": "good-stock-margin-gate-v1",
            "status": "UNAVAILABLE",
            "has_margin": False,
            "reasons": reasons,
        }

    years = _number(history.get("years"))
    pe_days = _number(history.get("pe_valid_trading_days"))
    ps_days = _number(history.get("ps_valid_trading_days"))
    history_short = (
        years is None or years < MIN_HISTORY_YEARS
        or pe_days is None or pe_days < MIN_HISTORY_TRADING_DAYS
        or ps_days is None or ps_days < MIN_HISTORY_TRADING_DAYS
    )
    if history_short:
        return {
            "version": "good-stock-margin-gate-v1",
            "status": "INSUFFICIENT_EVIDENCE",
            "has_margin": False,
            "reasons": ["own_history_coverage_insufficient"],
        }

    percentiles = {
        "industry_pe_percentile": _number(industry.get("pe_percentile")),
        "industry_ps_percentile": _number(industry.get("ps_percentile")),
        "history_pe_percentile": _number(history.get("pe_percentile")),
        "history_ps_percentile": _number(history.get("ps_percentile")),
    }
    missing = [key for key, value in percentiles.items() if value is None]
    if missing:
        return {
            "version": "good-stock-margin-gate-v1",
            "status": "UNAVAILABLE",
            "has_margin": False,
            "reasons": [f"missing:{key}" for key in missing],
        }

    failed = [key for key, value in percentiles.items() if value is not None and value > LOW_VALUE_PERCENTILE]
    return {
        "version": "good-stock-margin-gate-v1",
        "status": "HAS_MARGIN" if not failed else "NO_MARGIN",
        "has_margin": not failed,
        "reasons": [f"not_low_30pct:{key}" for key in failed],
        "thresholds": {
            "low_value_percentile_lte": LOW_VALUE_PERCENTILE,
            "minimum_history_years": MIN_HISTORY_YEARS,
            "minimum_history_trading_days": MIN_HISTORY_TRADING_DAYS,
        },
        "evidence": percentiles,
    }
