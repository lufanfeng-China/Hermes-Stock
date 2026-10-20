"""Read-only all-market filtering for the stock-filter page.

This is intentionally independent from the removed legacy screener/strategy modules.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from datetime import datetime
import subprocess
import sys

import pandas as pd

from app.stock_filter_history_progress import read_progress

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
HISTORICAL_FUNDAMENTALS = FINAL / "stock_filter_fundamental_history"
PAGE_SIZE = 50
SORT_FIELDS = {"rps_total", "composite_total", "annual_total", "quarterly_total", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "ps_ttm", "return_pct", "turnover_sum"}


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


def matches_financial_reversal(row: dict[str, Any]) -> bool:
    """Return whether a row meets the auditable standard financial-reversal preset.

    The long-term annual score must be a comparable five-year assessment.  The
    latest-quarter score must clear the standard-reversal threshold and the
    improvement must be supported by profitable growth, non-negative TTM FCF,
    no profitability deterioration, and no high/critical quarterly alert.
    """
    annual, quarterly = _num(row.get("annual_total")), _num(row.get("quarterly_total"))
    if annual is None or quarterly is None:
        return False
    if row.get("annual_assessment_track") != "five_year":
        return False
    if (_num(row.get("annual_coverage_weight")) or 0) < 85 or (_num(row.get("quarterly_coverage_weight")) or 0) < 85:
        return False
    if not (annual <= 55 and quarterly >= 70 and quarterly - annual >= 25):
        return False
    if not all((_num(row.get(key)) or 0) > 0 for key in ("quarterly_revenue_yoy", "quarterly_ex_net_profit_yoy")):
        return False
    if (_num(row.get("quarterly_ttm_fcf_margin")) or -float("inf")) < 0:
        return False
    if str(row.get("quarterly_profitability_status") or "") not in {"stable", "improving"}:
        return False
    return row.get("quarterly_high_or_critical_alert") is False


def matches_blowup_break(row: dict[str, Any]) -> bool:
    """Return whether the QFQ volume/price signal and both daily trends pass."""
    allowed = {"strong_bullish", "bullish", "recovering"}
    return bool(row.get("blowup_break_volume_price_ok")) and str(row.get("trend_daily") or "") in allowed and str(row.get("short_trend") or "") in allowed


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
def _qfq_latest() -> dict[tuple[str, str], dict[str, Any]]:
    """Load precomputed per-symbol QFQ metrics; never aggregate daily bars in HTTP requests."""
    payload = _read_json(FINAL / "stock_filter_market_metrics_current.json")
    metrics = payload.get("metrics") if isinstance(payload, dict) else {}
    if not isinstance(metrics, dict):
        return {}
    result = {}
    for key, value in metrics.items():
        if not isinstance(value, dict) or ":" not in str(key):
            continue
        market, symbol = str(key).split(":", 1)
        result[(market.lower(), symbol.zfill(6))] = value
    return result


@lru_cache(maxsize=1)
def _niche_leaders() -> dict[tuple[str, str], str]:
    """Read verified niche-leader tags once for the filter universe."""
    path = FINAL / "dataset_niche_leaders.parquet"
    if not path.is_file():
        return {}
    try:
        frame = pd.read_parquet(path, columns=["market", "symbol", "is_niche_leader", "niche_category"])
    except (OSError, ValueError, KeyError):
        return {}
    result: dict[tuple[str, str], str] = {}
    for item in frame.to_dict("records"):
        if not bool(item.get("is_niche_leader")):
            continue
        category = str(item.get("niche_category") or "").strip()
        if category and category != "未明确":
            result[(str(item.get("market") or "").lower(), str(item.get("symbol") or "").zfill(6))] = category
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
    niche_leaders = _niche_leaders()
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
        composite = financial.get("composite") or {}
        release_performance = financial.get("report_release_price_performance") or {}
        q_quality = q.get("quality") or {}
        industry = industries.get((market, symbol), {})
        valuation = valuations.get((market, symbol), {})
        qfq = qfq_latest.get((market, symbol), {})
        total = sum(_num(r.get(k)) or 0 for k in ("rps_20", "rps_50", "rps_120", "rps_250"))
        rows.append({
            "market": market, "symbol": symbol, "stock_name": names.get((market, symbol), symbol),
            "niche_leader": niche_leaders.get((market, symbol), ""),
            "industry": industry.get("industry_level_2_name") or industry.get("industry_level_1_name") or "",
            "price": _num(valuation.get("current_price")),
            "total_market_cap": _num(valuation.get("total_market_cap")),
            "free_float_market_cap": _num(valuation.get("free_float_market_cap")),
            "pe_ttm": _num(valuation.get("pe_ttm")), "ps_ttm": _num(valuation.get("ps_ttm")),
            "return_1d": qfq.get("return_1d"), "return_5d": qfq.get("return_5d"), "return_20d": qfq.get("return_20d"),
            "turnover_5_sum": qfq.get("turnover_5_sum"), "turnover_5_avg": qfq.get("turnover_5_avg"), "qfq_as_of": qfq.get("qfq_as_of"),
            "blowup_break_volume_price_ok": qfq.get("blowup_break_volume_price_ok"), "blowup_break_va": qfq.get("blowup_break_va"),
            "blowup_break_vol_ratios": qfq.get("blowup_break_vol_ratios") or [], "blowup_break_return_5d": qfq.get("blowup_break_return_5d"),
            "rps_20": _num(r.get("rps_20")), "rps_50": _num(r.get("rps_50")),
            "rps_120": _num(r.get("rps_120")), "rps_250": _num(r.get("rps_250")), "rps_total": round(total, 2),
            "composite_total": _num(composite.get("score")), "composite_mode": composite.get("mode"),
            "annual_total": _num(a.get("score")), "annual_dimensions": a.get("dimensions") or {}, "annual_derived": a.get("derived") or {},
            "annual_assessment_track": a.get("assessment_track"), "annual_coverage_weight": _num(a.get("coverage_weight")),
            "quarterly_total": _num(q.get("score")), "quarterly_dimensions": q.get("dimensions") or {}, "quarterly_coverage_weight": _num(q.get("coverage_weight")),
            "quarterly_revenue_yoy": _num(q_quality.get("revenue_yoy")), "quarterly_ex_net_profit_yoy": _num(q_quality.get("ex_net_profit_yoy")),
            "quarterly_ttm_fcf_margin": _num(q_quality.get("ttm_fcf_margin")), "quarterly_profitability_status": q_quality.get("profitability_status"),
            "quarterly_high_or_critical_alert": q_quality.get("has_high_or_critical_alert"),
            "quarterly_triggered_red_flag_count": q.get("triggered_red_flag_count"),
            "report_release_return_pct": _num(release_performance.get("return_pct")),
            "report_release_entry_trading_day": release_performance.get("entry_trading_day"),
            "report_release_latest_close_as_of": release_performance.get("current_price_as_of"),
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


def _historical_universe(as_of_date: str) -> tuple[list[dict[str, Any]], str]:
    """Load one immutable point-in-time fundamental snapshot.

    The builder writes date-specific files, so this request never substitutes a
    current financial record for a historical date.
    """
    path = HISTORICAL_FUNDAMENTALS / f"{as_of_date}.json"
    payload = _read_json(path)
    if not payload or payload.get("as_of_date") != as_of_date or payload.get("schema_version") != "stock-filter-fundamental-history-v2":
        # Build only the requested trading date and cache it permanently.  A lock
        # prevents concurrent browser requests from launching duplicate scans.
        lock = HISTORICAL_FUNDAMENTALS / f"{as_of_date}.building"
        HISTORICAL_FUNDAMENTALS.mkdir(parents=True, exist_ok=True)
        if not lock.exists():
            try:
                lock.touch(exist_ok=False)
                log = open(HISTORICAL_FUNDAMENTALS / f"{as_of_date}.log", "a", encoding="utf-8")
                subprocess.Popen([sys.executable, str(ROOT / "scripts" / "build_stock_filter_fundamental_history.py"), "--trading-day", as_of_date], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except FileExistsError:
                pass
        raise ValueError(f"historical snapshot is building for {as_of_date}; retry after the build completes")
    stocks = payload.get("stocks") or {}
    if not isinstance(stocks, dict):
        raise ValueError(f"invalid historical fundamental snapshot for {as_of_date}")
    from app.search.index import _stock_name_lookup, load_industry_rows
    names = _stock_name_lookup()
    industries = {(str(row.get("market") or "").lower(), str(row.get("symbol") or "").zfill(6)): row for row in load_industry_rows()}
    rows = []
    for key, value in stocks.items():
        if not isinstance(value, dict) or ":" not in str(key):
            continue
        market, symbol = str(key).split(":", 1)
        industry = industries.get((market, symbol.zfill(6)), {})
        rows.append({"market": market, "symbol": symbol.zfill(6), **value,
                     "stock_name": names.get((market, symbol.zfill(6)), symbol.zfill(6)),
                     "industry": industry.get("industry_level_2_name") or industry.get("industry_level_1_name") or "", "rps_total": None,
                     "annual_dimensions": value.get("annual_dimensions") or {},
                     "quarterly_dimensions": value.get("quarterly_dimensions") or {}})
    return rows, as_of_date


def filter_response(params: dict[str, list[str]]) -> dict[str, Any]:
    """Apply server-side filters first, then sort and paginate 50 rows."""
    try:
        page = int((params.get("page") or ["1"])[0])
        if page < 1: raise ValueError("page must be >= 1")
        page_size = int((params.get("page_size") or [str(PAGE_SIZE)])[0])
        if page_size != PAGE_SIZE: raise ValueError("page_size is fixed at 50")
        sort = (params.get("sort") or ["rps_total"])[0]
        if sort not in SORT_FIELDS: raise ValueError("unsupported sort")
        preset = (params.get("preset") or [""])[0].strip()
        if preset not in {"", "financial_reversal", "blowup_break"}: raise ValueError("unsupported preset")
        as_of_date = (params.get("as_of_date") or [""])[0].strip()
        if as_of_date:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        niche_leader = (params.get("niche_leader") or [""])[0].strip().lower()
        if niche_leader not in {"", "yes", "no"}: raise ValueError("niche_leader must be yes or no")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_filter", "message": str(exc)}}
    try:
        ranges = {k: _range(params, k) for k in ("rps_20", "rps_50", "rps_120", "rps_250", "rps_total", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "ps_ttm", "return_1d", "return_5d", "return_20d", "turnover_5_sum", "turnover_5_avg", "composite_total", "annual_total", "quarterly_total")}
        annual_dimension_ranges = {name: _range(params, f"annual_{name}") for name in ("growth_quality", "profitability", "cash_quality", "working_capital", "reinvestment", "financial_risk")}
        quarterly_dimension_ranges = {name: _range(params, f"quarterly_{name}") for name in ("growth", "profitability", "cash", "working_capital", "reinvestment", "financial_risk")}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_filter", "message": str(exc)}}
    try:
        rows, data_date = _historical_universe(as_of_date) if as_of_date else _universe()
    except ValueError as exc:
        message = str(exc)
        code = "historical_snapshot_building" if message.startswith("historical snapshot is building") else "historical_snapshot_unavailable"
        error: dict[str, Any] = {"code": code, "message": message}
        if code == "historical_snapshot_building" and as_of_date:
            error["progress"] = read_progress(HISTORICAL_FUNDAMENTALS, as_of_date)
        return {"ok": False, "error": error}
    daily_trends = _selected(params, "trend_daily") or _selected(params, "trend")
    weekly_trends = _selected(params, "trend_weekly")
    monthly_trends = _selected(params, "trend_monthly")
    macds, crosses = _selected(params, "macd_cross"), _selected(params, "golden_cross")
    market = (params.get("market") or [""])[0].strip().lower()
    filtered = []
    excluded_missing = 0
    for row in rows:
        if market and row["market"] != market: continue
        if preset == "financial_reversal" and not matches_financial_reversal(row): continue
        if preset == "blowup_break" and not matches_blowup_break(row): continue
        is_niche_leader = bool(str(row.get("niche_leader") or "").strip())
        if niche_leader == "yes" and not is_niche_leader: continue
        if niche_leader == "no" and is_niche_leader: continue
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
    return {"ok": True, "data_as_of": data_date, "effective_trade_date": data_date, "is_historical": bool(as_of_date), "total_universe": len(rows), "total_matched": total,
            "page": page, "page_size": PAGE_SIZE, "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "rows": filtered[start:start + PAGE_SIZE], "excluded_missing": excluded_missing,
            "capabilities": {"available": ["rps", "financial_health", "trend", "macd", "ma_golden_cross"],
                             "pending_snapshot": ["basic_market", "annual_derived"]}}
