"""Auditable secondary-industry PE/PS evidence for the margin gate."""
from __future__ import annotations

from typing import Any

from app.relative_valuation.percentiles import compute_empirical_percentile

MIN_INDUSTRY_SAMPLE = 10


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def evaluate_industry_evidence(*, market: str, symbol: str, industry_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Calculate a stock's PE and PS position using same-day industry members.

    Both samples use only positive, finite values; loss-making/invalid PE rows
    are never silently treated as cheap PE observations.
    """
    snapshot = industry_snapshot or {}
    rows = snapshot.get("member_valuation_rows")
    if snapshot.get("sample_status") != "ok" or not isinstance(rows, list):
        return {"status": "UNAVAILABLE", "reasons": ["industry_snapshot_unavailable"]}
    target = next((row for row in rows if str(row.get("market")) == str(market) and str(row.get("symbol")).zfill(6) == str(symbol).zfill(6)), None)
    if target is None:
        return {"status": "UNAVAILABLE", "reasons": ["stock_absent_from_industry_snapshot"]}
    target_pe, target_ps = _number(target.get("pe_ttm")), _number(target.get("ps_ttm"))
    comparable_rows = [
        row for row in rows
        if (_number(row.get("pe_ttm")) or 0) > 0 and (_number(row.get("ps_ttm")) or 0) > 0
    ]
    pe_sample = [float(_number(row.get("pe_ttm")) or 0.0) for row in comparable_rows]
    ps_sample = [float(_number(row.get("ps_ttm")) or 0.0) for row in comparable_rows]
    if target_pe is None or target_pe <= 0 or target_ps is None or target_ps <= 0:
        return {"status": "UNAVAILABLE", "reasons": ["target_pe_or_ps_not_positive"]}
    if len(pe_sample) < MIN_INDUSTRY_SAMPLE or len(ps_sample) < MIN_INDUSTRY_SAMPLE:
        return {
            "status": "INSUFFICIENT_EVIDENCE", "pe_sample_size": len(pe_sample), "ps_sample_size": len(ps_sample),
            "reasons": ["industry_pe_or_ps_sample_below_10"],
        }
    return {
        "status": "AVAILABLE", "industry_level_2_name": snapshot.get("industry_level_2_name"),
        "trading_day": snapshot.get("trading_day"), "pe_ttm": target_pe, "ps_ttm": target_ps,
        "pe_percentile": compute_empirical_percentile(target_pe, pe_sample),
        "ps_percentile": compute_empirical_percentile(target_ps, ps_sample),
        "pe_sample_size": len(pe_sample), "ps_sample_size": len(ps_sample),
        "sample_basis": "positive_pe_and_positive_ps_member_rows",
    }
