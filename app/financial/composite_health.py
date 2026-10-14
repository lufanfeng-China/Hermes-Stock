"""Auditable blend of long-term financial health and latest-quarter monitor."""
from __future__ import annotations

from math import isfinite
from typing import Any

MIN_COVERAGE = 85
COMPLETE_QUARTER_WEIGHT = 0.30
PARTIAL_QUARTER_WEIGHT = 0.15


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _score_status(score: float | None) -> str:
    if score is None:
        return "unavailable"
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "stable"
    if score >= 50:
        return "watch"
    return "risk"


def _risk_item_summary(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return "未命名风险项"
    title = str(item.get("title") or item.get("code") or "未命名风险项").strip()
    detail = str(item.get("detail") or "").strip()
    return f"{title}（{detail}）" if detail else title


def _risk_overlay(health: dict[str, Any] | None, monitor: dict[str, Any] | None) -> dict[str, Any]:
    annual_flags = list((health or {}).get("red_flags") or [])
    alerts = list((monitor or {}).get("alerts") or [])
    critical_alerts = [item for item in alerts if str(item.get("severity") or "").lower() == "critical"]
    high_alerts = [item for item in alerts if str(item.get("severity") or "").lower() == "high"]
    critical_summaries = [_risk_item_summary(item) for item in critical_alerts]
    high_summaries = [_risk_item_summary(item) for item in high_alerts]
    if critical_alerts:
        return {
            "status": "critical", "annual_red_flag_count": len(annual_flags),
            "quarterly_alert_count": len(alerts), "high_alert_count": len(high_alerts),
            "critical_alert_count": len(critical_alerts),
            "message": f"极高风险：最新季度触发 {len(critical_alerts)} 项极高严重度预警：{'；'.join(critical_summaries)}",
        }
    if len(high_alerts) >= 2:
        return {
            "status": "critical", "annual_red_flag_count": len(annual_flags),
            "quarterly_alert_count": len(alerts), "high_alert_count": len(high_alerts), "critical_alert_count": 0,
            "message": f"极高风险：{len(high_alerts)} 项高严重度预警叠加：{'；'.join(high_summaries)}",
        }
    if len(high_alerts) == 1:
        return {
            "status": "high", "annual_red_flag_count": len(annual_flags),
            "quarterly_alert_count": len(alerts), "high_alert_count": 1, "critical_alert_count": 0,
            "message": f"高严重度预警：{high_summaries[0]}",
        }
    if annual_flags or alerts:
        count = len(annual_flags) + len(alerts)
        summaries = [_risk_item_summary(item) for item in [*annual_flags, *alerts]]
        return {
            "status": "watch", "annual_red_flag_count": len(annual_flags),
            "quarterly_alert_count": len(alerts), "high_alert_count": 0, "critical_alert_count": 0,
            "message": f"普通关注：仍有 {count} 项年度红旗或季度预警需要单独核查：{'；'.join(summaries)}",
        }
    return {
        "status": "none", "annual_red_flag_count": 0, "quarterly_alert_count": 0,
        "high_alert_count": 0, "critical_alert_count": 0, "message": "未触发已评估的年度红旗或季度预警。",
    }


def _display_status(score_status: str, overlay_status: str) -> str:
    order = {"risk": 0, "watch": 1, "stable": 2, "excellent": 3}
    if overlay_status == "critical":
        return "risk"
    if overlay_status == "high":
        return "watch"
    if overlay_status == "watch":
        return min(score_status, "stable", key=lambda item: order.get(item, -1))
    return score_status


def build_composite_financial_health(health: dict[str, Any] | None, monitor: dict[str, Any] | None) -> dict[str, Any]:
    """Blend comparable five-year and latest-quarter scores without hiding risks.

    The annual score is the long-term base. A complete quarterly score changes the
    result by 30%; a partial but eligible quarterly score changes it by 15%. Any
    alert affects the independently displayed status only and never applies an
    opaque second numerical deduction.
    """
    health = health or {}
    monitor = monitor or {}
    annual_score = _number(health.get("score"))
    annual_coverage = _number(health.get("coverage_weight")) or 0.0
    annual_comparable = health.get("assessment_track") == "five_year"
    realtime = monitor.get("realtime_score") or {}
    quarterly_score = _number(realtime.get("score"))
    quarterly_coverage = _number(realtime.get("coverage_weight")) or 0.0
    quarterly_eligible = monitor.get("status") == "available" and quarterly_score is not None and quarterly_coverage >= MIN_COVERAGE
    overlay = _risk_overlay(health, monitor)

    result: dict[str, Any] = {
        "version": "composite-financial-health-v1",
        "mode": "unavailable",
        "reason": None,
        "score": None,
        "annual_score": annual_score,
        "quarterly_score": quarterly_score,
        "annual_weight": 0.0,
        "quarterly_weight": 0.0,
        "annual_coverage_weight": annual_coverage,
        "quarterly_coverage_weight": quarterly_coverage,
        "quarterly_coverage_status": "complete" if quarterly_coverage == 100 else "partial" if quarterly_eligible else "insufficient",
        "quarterly_period": monitor.get("latest_period"),
        "score_status": "unavailable",
        "display_status": "unavailable",
        "risk_overlay": overlay,
    }

    if annual_comparable and annual_score is not None and annual_coverage >= MIN_COVERAGE:
        annual_value = annual_score
        if quarterly_eligible:
            # quarterly_eligible includes a numeric score; retain the explicit
            # guard so static checking and future call-sites cannot violate it.
            assert quarterly_score is not None
            quarterly_weight = COMPLETE_QUARTER_WEIGHT if quarterly_coverage == 100 else PARTIAL_QUARTER_WEIGHT
            annual_weight = 1.0 - quarterly_weight
            result.update({
                "mode": "blended", "annual_weight": annual_weight, "quarterly_weight": quarterly_weight,
                "score": round(annual_value * annual_weight + quarterly_score * quarterly_weight, 1),
            })
        else:
            result.update({
                "mode": "annual_only", "reason": "quarterly_score_unavailable",
                "annual_weight": 1.0, "score": round(annual_value, 1),
            })
    elif quarterly_eligible:
        assert quarterly_score is not None
        result.update({
            "mode": "quarterly_only", "reason": "annual_score_not_five_year_comparable",
            "quarterly_weight": 1.0, "score": round(quarterly_score, 1),
        })
    elif not annual_comparable:
        result["reason"] = "annual_score_not_five_year_comparable"
    else:
        result["reason"] = "annual_score_unavailable"

    result["score_status"] = _score_status(result["score"])
    result["display_status"] = _display_status(result["score_status"], overlay["status"])
    return result
