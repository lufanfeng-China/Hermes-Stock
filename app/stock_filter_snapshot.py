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
        "annual": {
            "anchor_period": annual_anchor,
            "periods": list(health.get("periods") or []),
            "assessment_track": health.get("assessment_track"),
            "score": _number(health.get("score")),
            "coverage_weight": _number(health.get("coverage_weight")),
            "score_coverage_status": health.get("status"),
            "dimensions": _annual_dimensions(health),
            "derived": dict(health.get("derived") or {}),
            "reason": annual_reason,
        },
        "quarterly": {
            "anchor_period": quarterly_anchor,
            "period": monitor.get("latest_period"),
            "score": _number(realtime.get("score")),
            "coverage_weight": _number(realtime.get("coverage_weight")),
            "score_coverage_status": realtime.get("status") or monitor.get("status"),
            "dimensions": _quarterly_dimensions(monitor),
            "quality": _quarterly_quality(monitor),
            "triggered_red_flag_count": len(monitor.get("alerts") or []),
            "reason": quarterly_reason,
        },
    }
