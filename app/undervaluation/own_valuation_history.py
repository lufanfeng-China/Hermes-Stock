"""Announcement-date-correct own valuation history on raw closes."""
from __future__ import annotations

from bisect import bisect_right
from typing import Any


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def build_own_valuation_history(
    *, bars: list[dict[str, Any]], disclosures: list[dict[str, Any]], as_of_date: str,
) -> dict[str, Any]:
    """Value raw-price bars with only the latest report announced on that date.

    `ttm_eps`, `ttm_revenue`, and `total_shares` must use mutually compatible
    per-share / currency units.  Invalid or loss-making observations remain in
    the audit series but never count as valid PE/PS comparable observations.
    """
    cutoff = str(as_of_date or "")
    ordered_disclosures = sorted(
        (row for row in disclosures if str(row.get("announce_date") or "") <= cutoff),
        key=lambda row: str(row.get("announce_date") or ""),
    )
    dates = [str(row.get("announce_date") or "") for row in ordered_disclosures]
    series: list[dict[str, Any]] = []
    for bar in sorted(bars, key=lambda row: str(row.get("trading_day") or "")):
        day = str(bar.get("trading_day") or "")
        if not day or day > cutoff:
            continue
        disclosure_index = bisect_right(dates, day) - 1
        if disclosure_index < 0:
            continue
        disclosure = ordered_disclosures[disclosure_index]
        close = _number(bar.get("close"))
        eps = _number(disclosure.get("ttm_eps"))
        revenue = _number(disclosure.get("ttm_revenue"))
        shares = _number(disclosure.get("total_shares"))
        pe = close / eps if close is not None and close > 0 and eps is not None and eps > 0 else None
        ps = close * shares / revenue if close is not None and close > 0 and shares is not None and shares > 0 and revenue is not None and revenue > 0 else None
        series.append({
            "trading_day": day, "raw_close": close, "announce_date": disclosure.get("announce_date"),
            "period": disclosure.get("period"), "pe_ttm": pe, "ps_ttm": ps,
            "pe_ttm_reason": None if pe is not None else "raw_close_or_positive_ttm_eps_unavailable",
            "ps_ttm_reason": None if ps is not None else "raw_close_or_ttm_revenue_or_shares_unavailable",
        })
    pe_values = [row["pe_ttm"] for row in series if row["pe_ttm"] is not None]
    ps_values = [row["ps_ttm"] for row in series if row["ps_ttm"] is not None]
    latest = series[-1] if series else {}
    return {
        "as_of_date": cutoff, "price_basis": "raw_unadjusted_close", "series": series,
        "pe_valid_trading_days": len(pe_values), "ps_valid_trading_days": len(ps_values),
        "latest_pe_ttm": latest.get("pe_ttm"), "latest_ps_ttm": latest.get("ps_ttm"),
        "latest_disclosed_period": latest.get("period"),
        "latest_announce_date": latest.get("announce_date"),
    }
