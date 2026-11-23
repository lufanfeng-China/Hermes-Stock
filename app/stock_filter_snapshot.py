"""Strict, auditable financial records for the all-market stock filter.

Annual health is always derived from five complete annual reports; the separate
quarterly monitor is computed from one shared quarterly anchor and its TTM basis.
This module deliberately does not consume the percentile-based financial snapshots.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.financial.composite_health import build_composite_financial_health
from app.financial.health import build_financial_health
from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.undervaluation.quality_gate import evaluate_quality_gate
from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def calculate_qfq_market_metrics(bars: pd.DataFrame, *, free_float_shares: float | None, turnover_days: int) -> dict[str, Any]:
    """Calculate latest QFQ returns and a disclosed-window turnover from QFQ bars."""
    if bars is None or bars.empty or "close" not in bars or "volume" not in bars:
        return {"as_of": None, "returns": {}, "turnover": None}
    frame = bars.sort_index()
    closes = pd.to_numeric(frame["close"], errors="coerce")
    latest = _number(closes.iloc[-1])
    returns: dict[str, float | None] = {}
    for days in (1, 5, 20):
        previous = _number(closes.iloc[-1 - days]) if len(closes) > days else None
        returns[f"{days}d"] = round((latest / previous - 1) * 100, 4) if latest is not None and previous not in (None, 0) else None
    turnover = None
    shares = _number(free_float_shares)
    if shares is not None and shares > 0 and turnover_days > 0 and len(frame) >= turnover_days:
        volume = pd.to_numeric(frame["volume"].tail(turnover_days), errors="coerce")
        if volume.notna().all():
            sum_pct = float(volume.sum()) / shares * 100
            turnover = {"days": turnover_days, "sum_pct": round(sum_pct, 4), "avg_pct": round(sum_pct / turnover_days, 4)}
    return {"as_of": str(frame.index[-1].date()), "returns": returns, "turnover": turnover}


def _annual_dimensions(health: dict[str, Any]) -> dict[str, float | None]:
    return {str(item.get("code")): _number(item.get("score")) for item in health.get("dimensions") or []}


def _quarterly_dimensions(monitor: dict[str, Any]) -> dict[str, float | None]:
    # Quarterly monitor dimensions are status-led; convert its disclosed points to
    # an explicit score per dimension without blending them into annual health.
    return {str(item.get("code")): _number(item.get("points")) for item in (monitor.get("realtime_score") or {}).get("breakdown") or []}


def _quarterly_quality(monitor: dict[str, Any]) -> dict[str, Any]:
    """Persist only the disclosed evidence required by the reversal filter."""
    dimensions = {str(item.get("code")): item for item in monitor.get("dimensions") or []}
    alerts = monitor.get("alerts") or []
    return {
        "revenue_yoy": _number((monitor.get("yoy") or {}).get("revenue")),
        "ex_net_profit_yoy": _number((monitor.get("yoy") or {}).get("ex_net_profit")),
        "ttm_fcf_margin": _number((monitor.get("ttm") or {}).get("fcf_margin")),
        "profitability_status": dimensions.get("profitability", {}).get("status"),
        "has_high_or_critical_alert": any(str(item.get("severity") or "") in {"high", "critical"} for item in alerts),
        "triggered_red_flag_count": len(alerts),
    }


def build_sector_strict_financial_record(
    source: dict[str, Any], *, annual_anchor: str, quarterly_anchor: str,
) -> dict[str, Any]:
    """Project bank/securities model output into the strict snapshot contract."""
    annual_result = source.get("annual_score") if isinstance(source.get("annual_score"), dict) else {}
    quarterly_result = source.get("quarterly_score") if isinstance(source.get("quarterly_score"), dict) else {}
    annual_score = _number(annual_result.get("score"))
    quarterly_score = _number(quarterly_result.get("score"))
    annual_coverage = _number(annual_result.get("coverage_weight"))
    quarterly_coverage = _number(quarterly_result.get("coverage_weight"))
    scored_period = str(source.get("latest_scored_period") or "")
    announced_period = str(source.get("latest_announced_period") or "")
    quarterly_period = str(quarterly_result.get("report_period") or "") if quarterly_score is not None else ""
    current_quarterly = bool(
        quarterly_period
        and scored_period == quarterly_period
        and announced_period == quarterly_period
        and source.get("update_status") == "up_to_date"
    )
    if annual_score is not None and quarterly_score is not None and current_quarterly:
        composite_score = round(annual_score * 0.7 + quarterly_score * 0.3, 1)
        composite_mode = "sector_blended"
    elif annual_score is not None:
        composite_score = annual_score
        composite_mode = "sector_annual_only"
    elif quarterly_score is not None and current_quarterly:
        composite_score = quarterly_score
        composite_mode = "sector_quarterly_only"
    else:
        composite_score = None
        composite_mode = "unavailable"
    red_flags = list(annual_result.get("red_flags") or [])
    quality_reasons: list[str] = []
    if annual_score is None or annual_score < 70:
        quality_reasons.append("annual_score_below_70")
    if annual_coverage is None or annual_coverage < 85:
        quality_reasons.append("annual_coverage_below_85")
    model = source.get("financial_model") if isinstance(source.get("financial_model"), dict) else {
        "code": source.get("sector_model"), "label": source.get("sector_model")
    }
    using_previous = bool(
        source.get("latest_announced_period")
        and source.get("latest_scored_period")
        and source.get("latest_announced_period") != source.get("latest_scored_period")
    )
    quarterly_announced_period = str(source.get("latest_announced_period") or "")
    if quarterly_announced_period.endswith("A"):
        quarterly_announced_period = ""
    update = {
        "status": source.get("update_status") or "not_started",
        "latest_announced_period": source.get("latest_announced_period"),
        "latest_valid_period": source.get("latest_valid_period"),
        "latest_scored_period": source.get("latest_scored_period"),
        "using_previous_score": using_previous,
        "previous_quarterly_period": source.get("previous_quarterly_period"),
        "previous_quarterly_score": _number(source.get("previous_quarterly_score")),
        "last_error": source.get("last_error"),
    }
    return {
        "financial_model": model,
        "financial_update": update,
        "composite": {
            "version": "sector-composite-health-v1",
            "mode": composite_mode,
            "score": composite_score,
            "annual_score": annual_score,
            "quarterly_score": quarterly_score if current_quarterly else None,
            "annual_weight": 0.7 if composite_mode == "sector_blended" else 1.0 if annual_score is not None else 0.0,
            "quarterly_weight": 0.3 if composite_mode == "sector_blended" else 1.0 if composite_mode == "sector_quarterly_only" else 0.0,
        },
        "good_stock_quality": {
            "version": "sector-quality-gate-v1",
            "status": "QUALITY_ELIGIBLE" if not quality_reasons else "INSUFFICIENT_EVIDENCE" if annual_score is None else "NOT_QUALITY_ELIGIBLE",
            "eligible": not quality_reasons,
            "reasons": quality_reasons,
            "annual_score": annual_score,
            "annual_coverage_weight": annual_coverage,
        },
        "quarterly_momentum": {
            "version": "sector-quarterly-momentum-v1",
            "status": quarterly_result.get("status") if current_quarterly else "pending_update",
            "eligible": current_quarterly and quarterly_score is not None,
        },
        "annual": {
            "anchor_period": source.get("annual_period") or annual_anchor,
            "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"],
            "assessment_track": "five_year",
            "score_version": annual_result.get("score_version"),
            "score_basis_track": str(source.get("sector_model") or "") + "_sector_model",
            "score_comparable": annual_score is not None,
            "score_comparability": annual_result.get("score_comparability"),
            "score": annual_score,
            "coverage_weight": annual_coverage,
            "score_coverage_status": annual_result.get("status"),
            "dimensions": {
                str(code): _number(item.get("score"))
                for code, item in (annual_result.get("dimensions") or {}).items()
                if isinstance(item, dict)
            },
            "derived": dict(source.get("annual_inputs") or {}),
            "red_flags": red_flags,
            "reason": None if annual_score is not None else "sector_annual_score_unavailable",
        },
        "quarterly": {
            "anchor_period": quarterly_announced_period or quarterly_anchor,
            "anchor_period_global": quarterly_anchor,
            "period": quarterly_period if current_quarterly else None,
            "score": quarterly_score if current_quarterly else None,
            "coverage_weight": quarterly_coverage if current_quarterly else None,
            "score_coverage_status": quarterly_result.get("status") if current_quarterly else "pending_update",
            "dimensions": {
                str(code): _number(item.get("score"))
                for code, item in (quarterly_result.get("parts") or {}).items()
                if isinstance(item, dict)
            } if current_quarterly else {},
            "quality": {},
            "profit_comparisons": {},
            "triggered_red_flag_count": 0,
            "reason": None if current_quarterly else "sector_quarterly_update_pending",
        },
    }


def build_strict_financial_record(
    reports: list[dict[str, Any]], *, industry_level_1: str | None,
    annual_anchor: str, quarterly_anchor: str,
) -> dict[str, Any]:
    """Build one stock's strict annual + quarterly records from supplied reports."""
    annual_reports = [row for row in reports if str(row.get("period") or "").endswith("A")]
    health = build_financial_health(annual_reports, industry_level_1=industry_level_1)
    monitor = build_quarterly_financial_monitor(reports, industry_level_1=industry_level_1)
    composite = build_composite_financial_health(health, monitor)
    annual_reason = health.get("reason") or (None if health.get("score") is not None else "annual_score_unavailable")
    realtime = monitor.get("realtime_score") or {}
    quarterly_reason = monitor.get("reason") or realtime.get("reason") or (None if realtime.get("score") is not None else "quarterly_score_unavailable")
    return {
        "composite": composite,
        # Annual quality and quarterly operating momentum are deliberately emitted
        # as separate tracks: the latter never overrides the annual gate.
        "good_stock_quality": evaluate_quality_gate(health),
        "quarterly_momentum": evaluate_quarterly_momentum(monitor),
        "annual": {
            "anchor_period": annual_anchor,
            "periods": list(health.get("periods") or []),
            "assessment_track": health.get("assessment_track"),
            "score_version": health.get("score_version"),
            "score_basis_track": health.get("score_basis_track"),
            "score_comparable": health.get("score_comparable"),
            "growth_quality_basis": health.get("growth_quality_basis"),
            "cash_quality_basis": health.get("cash_quality_basis"),
            "score": _number(health.get("score")),
            "coverage_weight": _number(health.get("coverage_weight")),
            "score_coverage_status": health.get("status"),
            "dimensions": _annual_dimensions(health),
            "derived": dict(health.get("derived") or {}),
            "reason": annual_reason,
        },
        "quarterly": {
            # Per-stock latest disclosed quarter: a company that already filed 2026Q3
            # must not be shown (or scored) as 2026Q2 just because others were slower.
            "anchor_period": monitor.get("latest_period") or quarterly_anchor,
            "anchor_period_global": quarterly_anchor,
            "period": monitor.get("latest_period"),
            "score": _number(realtime.get("score")),
            "coverage_weight": _number(realtime.get("coverage_weight")),
            "score_coverage_status": realtime.get("status") or monitor.get("status"),
            "dimensions": _quarterly_dimensions(monitor),
            "quality": _quarterly_quality(monitor),
            "profit_comparisons": monitor.get("profit_comparisons") or {},
            "triggered_red_flag_count": len(monitor.get("alerts") or []),
            "reason": quarterly_reason,
        },
    }
