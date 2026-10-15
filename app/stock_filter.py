"""Read-only all-market filtering for the stock-filter page.

This is intentionally independent from the removed legacy screener/strategy modules.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
PAGE_SIZE = 50
SORT_FIELDS = {"rps_total", "annual_total", "quarterly_total", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "ps_ttm", "return_pct", "turnover_sum"}


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _range(params: dict[str, list[str]], key: str) -> tuple[float | None, float | None]:
    lo, hi = _num((params.get(f"{key}_min") or [None])[0]), _num((params.get(f"{key}_max") or [None])[0])
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"{key}_min must not exceed {key}_max")
    return lo, hi


def _passes(value: Any, bounds: tuple[float | None, float | None]) -> bool:
    lo, hi = bounds
    if lo is None and hi is None:
        return True
    number = _num(value)
    return number is not None and (lo is None or number >= lo) and (hi is None or number <= hi)


def classify_timeframe_trend(closes: list[float]) -> str | None:
    """Classify one homogeneous price timeframe from fast/mid/slow moving averages.

    The caller is responsible for supplying only daily, weekly, or monthly closes;
    this prevents a trend label from mixing periods.
    """
    values = [float(value) for value in closes if _num(value) is not None]
    if len(values) < 20:
        return None
    series = pd.Series(values, dtype=float)
    fast, middle, slow = (series.rolling(window).mean().iloc[-1] for window in (5, 10, 20))
    latest = values[-1]
    if latest > fast > middle > slow:
        return "strong_bullish"
    if latest > fast > middle:
        return "bullish"
    if latest < fast < middle:
        return "bearish"
    return "neutral"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def _qfq_latest() -> dict[tuple[str, str], dict[str, float | None]]:
    """Latest QFQ returns and fixed 5-day turnover from the prebuilt daily snapshot."""
    path = FINAL / "stock_filter_qfq_daily.parquet"
    if not path.exists(): return {}
    frame = pd.read_parquet(path, columns=["market", "symbol", "date", "close", "volume", "free_float_shares"])
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["date"] = pd.to_datetime(frame["date"])
    result = {}
    trend_labels = {"strong_bullish": "强多头", "bullish": "多头", "bearish": "空头", "neutral": "震荡"}
    for key, group in frame.groupby(["market", "symbol"], sort=False):
        group = group.sort_values("date")
        close = group["close"].astype(float).tolist()
        weekly_close = group.set_index("date")["close"].resample("W-FRI").last().dropna().astype(float).tolist()
        monthly_close = group.set_index("date")["close"].resample("ME").last().dropna().astype(float).tolist()
        latest = close[-1] if close else None
        weekly_trend = classify_timeframe_trend(weekly_close)
        monthly_trend = classify_timeframe_trend(monthly_close)
        item = {"return_1d": None, "return_5d": None, "return_20d": None, "qfq_as_of": str(group.iloc[-1]["date"].date()) if len(group) else None,
                "trend_weekly": weekly_trend, "trend_weekly_label": trend_labels.get(weekly_trend or ""),
                "trend_monthly": monthly_trend, "trend_monthly_label": trend_labels.get(monthly_trend or "")}
        for days in (1, 5, 20):
            if len(close) > days and close[-1-days] != 0:
                item[f"return_{days}d"] = round((close[-1] / close[-1-days] - 1) * 100, 4)
        shares = _num(group.iloc[-1]["free_float_shares"]) if len(group) else None
        if shares and shares > 0 and len(group) >= 5:
            total = float(group.tail(5)["volume"].sum()) / shares * 100
            item["turnover_5_sum"] = round(total, 4); item["turnover_5_avg"] = round(total / 5, 4)
        else:
            item["turnover_5_sum"] = item["turnover_5_avg"] = None
        result[(str(key[0]), str(key[1]).zfill(6))] = item
    return result


@lru_cache(maxsize=1)
def _universe() -> tuple[list[dict[str, Any]], str]:
    """Merge existing authoritative snapshots into one light-weight query universe."""
    from app.search.index import _stock_name_lookup, load_industry_rows

    tech_raw = _read_json(FINAL / "dataset_technical_eval.json")
    tech_rows = tech_raw.get("stocks", {}) if isinstance(tech_raw, dict) else {}
    strict_financial = _read_json(FINAL / "strict_financial_health_snapshot_2025A__2026Q2.json").get("stocks", {})
    rps_path = FINAL / "dataset_stock_rps_history.parquet"
    rps: dict[tuple[str, str], dict[str, Any]] = {}
    data_date = str(tech_raw.get("data_date") or "")
    if rps_path.exists():
        frame = pd.read_parquet(rps_path, columns=["trading_day", "market", "symbol", "rps_20", "rps_50", "rps_120", "rps_250"])
        frame["trading_day"] = frame["trading_day"].astype(str)
        latest = frame[frame["trading_day"] == frame["trading_day"].max()]
        data_date = str(latest.iloc[0]["trading_day"]) if len(latest) else data_date
        for item in latest.to_dict("records"):
            rps[(str(item["market"]), str(item["symbol"]).zfill(6))] = item

    names = _stock_name_lookup()
    industries = {(str(x.get("market") or "").lower(), str(x.get("symbol") or "").zfill(6)): x for x in load_industry_rows()}
    valuation_rows = _read_json(FINAL / "dataset_industry_valuation_current.json")
    valuations: dict[tuple[str, str], dict[str, Any]] = {}
    qfq_latest = _qfq_latest()
    if isinstance(valuation_rows, list):
        for group in valuation_rows:
            if not isinstance(group, dict):
                continue
            for member in group.get("member_valuation_rows") or []:
                if isinstance(member, dict):
                    valuations[(str(member.get("market") or "").lower(), str(member.get("symbol") or "").zfill(6))] = member
    rows: list[dict[str, Any]] = []
    # Use RPS as the live A-share universe; it has market disambiguation.
    for (market, symbol), r in rps.items():
        key = f"{market}:{symbol}"
        tech = tech_rows.get(symbol, {})
        financial = strict_financial.get(key, {})
        a, q = financial.get("annual", {}), financial.get("quarterly", {})
        industry = industries.get((market, symbol), {})
        valuation = valuations.get((market, symbol), {})
        qfq = qfq_latest.get((market, symbol), {})
        total = sum(_num(r.get(k)) or 0 for k in ("rps_20", "rps_50", "rps_120", "rps_250"))
        rows.append({
            "market": market, "symbol": symbol, "stock_name": names.get((market, symbol), symbol),
            "industry": industry.get("industry_level_2_name") or industry.get("industry_level_1_name") or "",
            "price": _num(valuation.get("current_price")),
            "total_market_cap": _num(valuation.get("total_market_cap")),
            "free_float_market_cap": _num(valuation.get("free_float_market_cap")),
            "pe_ttm": _num(valuation.get("pe_ttm")), "ps_ttm": _num(valuation.get("ps_ttm")),
            "return_1d": qfq.get("return_1d"), "return_5d": qfq.get("return_5d"), "return_20d": qfq.get("return_20d"),
            "turnover_5_sum": qfq.get("turnover_5_sum"), "turnover_5_avg": qfq.get("turnover_5_avg"), "qfq_as_of": qfq.get("qfq_as_of"),
            "rps_20": _num(r.get("rps_20")), "rps_50": _num(r.get("rps_50")),
            "rps_120": _num(r.get("rps_120")), "rps_250": _num(r.get("rps_250")), "rps_total": round(total, 2),
            "annual_total": _num(a.get("score")), "annual_dimensions": a.get("dimensions") or {}, "annual_derived": a.get("derived") or {},
            "quarterly_total": _num(q.get("score")), "quarterly_dimensions": q.get("dimensions") or {},
            "annual_period": a.get("anchor_period"), "quarterly_period": q.get("anchor_period"),
            "trend_daily": tech.get("trend"), "trend_daily_label": tech.get("trend_label"),
            "trend_weekly": qfq.get("trend_weekly"), "trend_weekly_label": qfq.get("trend_weekly_label"),
            "trend_monthly": qfq.get("trend_monthly"), "trend_monthly_label": qfq.get("trend_monthly_label"),
            "trend": tech.get("trend"), "trend_label": tech.get("trend_label"),
            "short_trend": tech.get("short_trend"), "short_trend_label": tech.get("short_trend_label"),
            "momentum": tech.get("momentum"), "momentum_label": tech.get("momentum_label"),
            "golden_cross": tech.get("golden_cross"), "golden_cross_label": tech.get("golden_cross_label"),
            "macd_cross": tech.get("macd_cross"), "macd_cross_label": tech.get("macd_cross_label"),
        })
    return rows, data_date


def _selected(params: dict[str, list[str]], key: str) -> set[str]:
    return {x.strip() for x in (params.get(key) or [""])[0].split(",") if x.strip()}


def filter_response(params: dict[str, list[str]]) -> dict[str, Any]:
    """Apply server-side filters first, then sort and paginate 50 rows."""
    try:
        page = int((params.get("page") or ["1"])[0])
        if page < 1: raise ValueError("page must be >= 1")
        page_size = int((params.get("page_size") or [str(PAGE_SIZE)])[0])
        if page_size != PAGE_SIZE: raise ValueError("page_size is fixed at 50")
        sort = (params.get("sort") or ["rps_total"])[0]
        if sort not in SORT_FIELDS: raise ValueError("unsupported sort")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_filter", "message": str(exc)}}
    try:
        ranges = {k: _range(params, k) for k in ("rps_20", "rps_50", "rps_120", "rps_250", "rps_total", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "ps_ttm", "return_1d", "return_5d", "return_20d", "turnover_5_sum", "turnover_5_avg", "annual_total", "quarterly_total")}
        annual_dimension_ranges = {name: _range(params, f"annual_{name}") for name in ("growth_quality", "profitability", "cash_quality", "working_capital", "reinvestment", "financial_risk")}
        quarterly_dimension_ranges = {name: _range(params, f"quarterly_{name}") for name in ("growth", "profitability", "cash", "working_capital", "reinvestment", "financial_risk")}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_filter", "message": str(exc)}}
    rows, data_date = _universe()
    daily_trends = _selected(params, "trend_daily") or _selected(params, "trend")
    weekly_trends = _selected(params, "trend_weekly")
    monthly_trends = _selected(params, "trend_monthly")
    macds, crosses = _selected(params, "macd_cross"), _selected(params, "golden_cross")
    market = (params.get("market") or [""])[0].strip().lower()
    filtered = []
    excluded_missing = 0
    for row in rows:
        if market and row["market"] != market: continue
        if not all(_passes(row.get(key), bound) for key, bound in ranges.items()):
            if any(bound != (None, None) and row.get(key) is None for key, bound in ranges.items()): excluded_missing += 1
            continue
        if not all(_passes(row["annual_dimensions"].get(name), bound) for name, bound in annual_dimension_ranges.items()): continue
        if not all(_passes(row["quarterly_dimensions"].get(name), bound) for name, bound in quarterly_dimension_ranges.items()): continue
        if daily_trends and str(row.get("trend_daily") or "") not in daily_trends: continue
        if weekly_trends and str(row.get("trend_weekly") or "") not in weekly_trends: continue
        if monthly_trends and str(row.get("trend_monthly") or "") not in monthly_trends: continue
        if macds and str(row.get("macd_cross") or "") not in macds: continue
        if crosses and str(row.get("golden_cross") or "") not in crosses: continue
        filtered.append(row)
    reverse = (params.get("order") or ["desc"])[0].lower() != "asc"
    filtered.sort(key=lambda row: (_num(row.get(sort)) is not None, _num(row.get(sort)) or -float("inf")), reverse=reverse)
    total = len(filtered); start = (page - 1) * PAGE_SIZE
    return {"ok": True, "data_as_of": data_date, "total_universe": len(rows), "total_matched": total,
            "page": page, "page_size": PAGE_SIZE, "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "rows": filtered[start:start + PAGE_SIZE], "excluded_missing": excluded_missing,
            "capabilities": {"available": ["rps", "financial_health", "trend", "macd", "ma_golden_cross"],
                             "pending_snapshot": ["basic_market", "annual_derived", "date_return", "turnover"]}}
