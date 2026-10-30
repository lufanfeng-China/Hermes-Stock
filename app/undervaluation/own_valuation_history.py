"""Announcement-date-correct own valuation history on raw closes."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Any

from app.relative_valuation.percentiles import compute_empirical_percentile


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _row_for(period_frames: dict[str, Any], period: str, symbol: str) -> Any | None:
    frame = period_frames.get(period)
    if frame is None:
        return None
    # Warehouse indices are already security-code strings. Casting the full
    # index here rebuilt thousands of labels for each of the per-stock lookups.
    matches = frame.loc[str(symbol).zfill(6)] if str(symbol).zfill(6) in frame.index else None
    if matches is None:
        return None
    return matches.iloc[0] if getattr(matches, "ndim", 1) > 1 else matches


def build_pit_disclosures_from_period_frames(
    *, period_frames: dict[str, Any], symbol: str, as_of_date: str,
) -> list[dict[str, Any]]:
    """Adapt warehouse report rows into announcement-date-correct valuation inputs."""
    cutoff = str(as_of_date or "")
    disclosures: list[dict[str, Any]] = []
    for period in sorted(period_frames, key=lambda item: (int(item[:4]) if item[:4].isdigit() else 0, {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}.get(item[4:], 9))):
        row = _row_for(period_frames, period, symbol)
        if row is None:
            continue
        announce_date = _date_text(row.get("announce_date") if hasattr(row, "get") else None)
        if announce_date is None or announce_date > cutoff:
            continue
        eps = _number(row.get("基本每股收益"))
        if not period.endswith("A"):
            year, suffix = int(period[:4]), period[4:]
            prior_annual = _row_for(period_frames, f"{year - 1}A", symbol)
            prior_same = _row_for(period_frames, f"{year - 1}{suffix}", symbol)
            prior_annual_announce = _date_text(prior_annual.get("announce_date")) if prior_annual is not None else None
            prior_same_announce = _date_text(prior_same.get("announce_date")) if prior_same is not None else None
            prior_annual_eps = _number(prior_annual.get("基本每股收益")) if prior_annual is not None else None
            prior_same_eps = _number(prior_same.get("基本每股收益")) if prior_same is not None else None
            if (eps is None or prior_annual_eps is None or prior_same_eps is None
                    or prior_annual_announce is None or prior_same_announce is None
                    or prior_annual_announce > announce_date or prior_same_announce > announce_date):
                eps = None
            else:
                eps = eps + prior_annual_eps - prior_same_eps
        revenue_wan = _number(row.get("营业总收入TTM(万元)"))
        shares = _number(row.get("总股本"))
        disclosures.append({
            "period": period, "announce_date": announce_date, "ttm_eps": eps,
            "ttm_revenue": revenue_wan * 10_000 if revenue_wan is not None else None,
            "total_shares": shares,
        })
    return sorted(disclosures, key=lambda item: (str(item["announce_date"]), str(item["period"])))


def _three_years_before(as_of_date: str) -> str | None:
    try:
        value = date.fromisoformat(as_of_date)
        return value.replace(year=value.year - 3).isoformat()
    except ValueError:
        return None


def summarize_own_valuation_history(history: dict[str, Any] | None) -> dict[str, Any]:
    """Assess D8 coverage and calculate own-history PE/PS percentiles."""
    history = history or {}
    as_of = str(history.get("as_of_date") or "")
    series = [row for row in (history.get("series") or []) if isinstance(row, dict)]
    pe_values = [_number(row.get("pe_ttm")) for row in series]
    ps_values = [_number(row.get("ps_ttm")) for row in series]
    pe_values = [value for value in pe_values if value is not None]
    ps_values = [value for value in ps_values if value is not None]
    latest = series[-1] if series else {}
    latest_pe, latest_ps = _number(latest.get("pe_ttm")), _number(latest.get("ps_ttm"))
    required_start = _three_years_before(as_of)
    observed_start = min((str(row.get("trading_day")) for row in series if row.get("trading_day")), default=None)
    try:
        years = (date.fromisoformat(as_of) - date.fromisoformat(observed_start)).days / 365.2425 if observed_start else None
    except ValueError:
        years = None
    coverage_sufficient = bool(
        required_start and observed_start and observed_start <= required_start
        and len(pe_values) >= 500 and len(ps_values) >= 500
    )
    reasons = []
    if not required_start or not observed_start or observed_start > (required_start or ""):
        reasons.append("three_natural_year_history_unavailable")
    if len(pe_values) < 500:
        reasons.append("pe_valid_trading_days_below_500")
    if len(ps_values) < 500:
        reasons.append("ps_valid_trading_days_below_500")
    return {
        "status": "AVAILABLE" if coverage_sufficient else "INSUFFICIENT_EVIDENCE",
        "as_of_date": as_of, "required_history_start": required_start, "observed_history_start": observed_start,
        "years": years,
        "pe_valid_trading_days": len(pe_values), "ps_valid_trading_days": len(ps_values),
        "pe_percentile": compute_empirical_percentile(latest_pe, pe_values),
        "ps_percentile": compute_empirical_percentile(latest_ps, ps_values),
        "latest_pe_ttm": latest_pe, "latest_ps_ttm": latest_ps,
        "coverage_sufficient": coverage_sufficient, "reasons": reasons,
    }


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
