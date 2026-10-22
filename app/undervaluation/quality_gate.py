"""Annual quality eligibility for the good-stock-and-undervaluation diagnostic."""
from __future__ import annotations

from typing import Any

MIN_ANNUAL_SCORE = 70.0
MIN_ANNUAL_COVERAGE = 85.0
CORE_RED_FLAG_FAMILIES = {
    "cash_quality": frozenset({"ex_profit_up_ocf_down", "fcf_two_year_negative"}),
    "leverage_solvency": frozenset({"debt_ratio_rising"}),
    "earnings_durability": frozenset({
        "revenue_up_ex_profit_down", "gross_margin_two_year_decline", "roe_ex_decline",
    }),
}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_quality_gate(annual_health: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate the frozen annual quality gateway without quarterly overrides."""
    health = annual_health or {}
    reasons: list[str] = []
    if health.get("assessment_track") != "five_year":
        reasons.append("annual_health_not_five_year_comparable")
    score = _number(health.get("score"))
    if score is None or score < MIN_ANNUAL_SCORE:
        reasons.append("annual_score_below_70")
    coverage = _number(health.get("coverage_weight"))
    if coverage is None or coverage < MIN_ANNUAL_COVERAGE:
        reasons.append("annual_coverage_below_85")
    unavailable_rules = set((health.get("red_flag_coverage") or {}).get("unavailable") or [])
    unavailable_core_families = [
        family for family, codes in CORE_RED_FLAG_FAMILIES.items()
        if codes.issubset(unavailable_rules)
    ]
    for family in unavailable_core_families:
        reasons.append(f"core_red_flag_family_unavailable:{family}")
    severe_flags = [
        item for item in (health.get("red_flags") or [])
        if isinstance(item, dict) and str(item.get("severity") or "").lower() in {"high", "critical"}
    ]
    if severe_flags:
        reasons.append("annual_high_or_critical_red_flag")
    status = "INSUFFICIENT_EVIDENCE" if unavailable_core_families else "QUALITY_ELIGIBLE" if not reasons else "NOT_QUALITY_ELIGIBLE"
    return {
        "version": "good-stock-quality-gate-v1",
        "status": status,
        "eligible": not reasons,
        "reasons": reasons,
        "annual_score": score,
        "annual_coverage_weight": coverage,
    }
