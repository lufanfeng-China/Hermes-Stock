"""Read-only all-market filtering for the stock-filter page.

This is intentionally independent from the removed legacy screener/strategy modules.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any
from datetime import date, datetime
import subprocess
import sys

import pandas as pd

from app.stock_filter_history_progress import read_progress
from app.stock_filter_market_snapshot import (BASIC_MARKET_FIELDS, LIMIT_UP_FIELDS,
                                              PRICE_PERCENTILE_FIELDS, TREND_TEMPLATE_FIELDS)
from app.stock_filter_scope import filter_rows_by_scope, stock_scope_index
import math

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
HISTORICAL_FUNDAMENTALS = FINAL / "stock_filter_fundamental_history"
PE_PERCENTILE_SNAPSHOT = FINAL / "stock_filter_pe_percentile_current.json"
TURNOVER_PERCENTILE_SNAPSHOT = FINAL / "stock_filter_turnover_percentile_current.json"
PAGE_SIZE = 50
BASIC_MARKET_FILTERS = ("return_1d", "volume_ratio_5", "ma5_distance_pct",
                        "ma10_distance_pct", "ma20_distance_pct")
HISTORICAL_LATEST_ONLY_PARAMS = frozenset({
    "industry_l2_codes", "industry_temperature_levels", "concept_codes", "concept_temperature_levels",
    "rps_20_min", "rps_20_max", "rps_50_min", "rps_50_max", "rps_120_min", "rps_120_max",
    "rps_250_min", "rps_250_max", "rps_total_min", "rps_total_max",
    "return_n_days", "return_n_pct_min", "return_n_pct_max",
    "change_days_n", "up_days_min", "up_days_max", "down_days_min", "down_days_max",
    "limit_up_n_days", "eps_ratio_5y_min", "eps_ratio_5y_max",
    "total_market_cap_min", "total_market_cap_max",
    "free_float_market_cap_min", "free_float_market_cap_max",
    "niche_leader", "composite_total_min", "composite_total_max",
    "trend_weekly", "trend_monthly", "macd_cross", "golden_cross",
    "ma_alignment", "ma_alignment_days_min", "ma_alignment_days_max",
    "mrs_score_min", "mrs_score_max", "excess_return_5_pp_min", "excess_return_5_pp_max",
    "excess_return_20_pp_min", "excess_return_20_pp_max",
    "excess_return_50_pp_min", "excess_return_50_pp_max",
    "excess_return_120_pp_min", "excess_return_120_pp_max",
    "excess_return_250_pp_min", "excess_return_250_pp_max",
    "down_market_win_rate_20_min", "down_market_win_rate_20_max",
    "down_market_total_excess_pp_20_min", "down_market_total_excess_pp_20_max",
    "return_5d_min", "return_5d_max", "return_20d_min", "return_20d_max",
    "turnover_5_sum_min", "turnover_5_sum_max", "turnover_5_avg_min", "turnover_5_avg_max",
})
HISTORICAL_LATEST_ONLY_SORTS = frozenset({
    "rps_total", "mrs_score", "excess_return_20_pp", "composite_total",
    "total_market_cap", "free_float_market_cap", "eps_ratio_5y", "return_pct", "turnover_sum",
})
HISTORICAL_PARAM_LABELS = {
    "industry_l2_codes": "二级行业成员", "industry_temperature_levels": "行业温度",
    "concept_codes": "概念成员", "concept_temperature_levels": "概念温度",
}
SORT_FIELDS = {"eps_ratio_5y", "rps_total", "mrs_score", "excess_return_20_pp", "composite_total", "annual_total", "quarterly_total", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "pe_percentile_5y", "price_percentile_5y", "turnover_percentile_1y", "ps_ttm", "return_pct", "turnover_sum"}

# 01 股票范围：先锁定股票池，再套用其它筛选条件。
STOCK_SCOPE_LABELS = {
    "all": "全部",
    "csi300": "沪深300",
    "main_board": "沪深主板",
    "chinext": "创业板",
    "star": "科创板",
    # 双创 = 科创板 + 创业板
    "dual_creative": "双创（科创+创业）",
}


def board_of(market: str, symbol: str) -> str:
    """Classify a symbol into main / chinext / star / bj / other by market + code prefix."""
    market = str(market or "").strip().lower()
    code = str(symbol or "").strip().zfill(6)
    if market == "bj" or code.startswith(("92", "83", "87", "43", "82")):
        return "bj"
    if market == "sh":
        if code.startswith(("688", "689")):
            return "star"
        if code.startswith(("600", "601", "603", "605")):
            return "main"
        return "other"
    if market == "sz":
        if code.startswith(("300", "301", "302")):
            return "chinext"
        if code.startswith(("000", "001", "002", "003")):
            return "main"
        return "other"
    return "other"


@lru_cache(maxsize=1)
def csi300_codes() -> frozenset[str]:
    """Latest CSI300 constituent list, as bare 6-digit codes."""
    candidates = sorted(FINAL.glob("csi300_constituents_current*.json"))
    if not candidates:
        return frozenset()
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    codes = payload.get("constituents") if isinstance(payload, dict) else payload
    if not isinstance(codes, list):
        return frozenset()
    return frozenset(str(code).strip().zfill(6) for code in codes if str(code).strip())


def matches_scope(market: str, symbol: str, scope: str) -> bool:
    """True when the symbol belongs to the requested 01 股票范围."""
    if scope in ("", "all"):
        return True
    board = board_of(market, symbol)
    if scope == "csi300":
        return str(symbol or "").strip().zfill(6) in csi300_codes()
    if scope == "main_board":
        return board == "main"
    if scope == "chinext":
        return board == "chinext"
    if scope == "star":
        return board == "star"
    if scope == "dual_creative":
        return board in ("star", "chinext")
    return True


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


def _read_pe_percentile_snapshot() -> dict[str, Any]:
    """The publisher atomically replaces this file; never cache a missing version."""
    return _read_json(PE_PERCENTILE_SNAPSHOT)


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


def matches_trend_template(row: dict[str, Any]) -> bool:
    """Return whether the row satisfies the 7-leg Trend Template.

    The 8th leg of the published template (relative strength rating >= 70) is
    deliberately not part of this preset.
    """
    return bool(row.get("trend_template_ok"))


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


def _read_strict_financial_snapshot() -> dict:
    """Latest strict snapshot, with a fallback to the fixed-quarter file name."""
    for name in ("strict_financial_health_snapshot_2025A__latest_quarter.json",
                 "strict_financial_health_snapshot_2025A__2026Q2.json"):
        payload = _read_json(FINAL / name)
        if payload.get("stocks"):
            return payload.get("stocks", {})
    return {}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def _read_turnover_snapshot() -> dict:
    return _read_json(TURNOVER_PERCENTILE_SNAPSHOT)


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
def _relative_strengths() -> dict[tuple[str, str], dict[str, Any]]:
    from app.market_relative_strength import load_current_snapshot
    stocks = load_current_snapshot().get("stocks") or {}
    result = {}
    for key, value in stocks.items():
        if isinstance(value, dict) and ":" in str(key):
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
    strict_financial = _read_strict_financial_snapshot()
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
    relative_strengths = _relative_strengths()
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
        relative = relative_strengths.get((market, symbol), {})
        total = sum(_num(r.get(k)) or 0 for k in ("rps_20", "rps_50", "rps_120", "rps_250"))
        rows.append({
            "market": market, "symbol": symbol, "stock_name": names.get((market, symbol), symbol),
            "niche_leader": niche_leaders.get((market, symbol), ""),
            "industry": industry.get("industry_level_2_name") or industry.get("industry_level_1_name") or "",
            "industry_level_2_code": industry.get("industry_level_2_code") or "",
            "industry_level_2_name": industry.get("industry_level_2_name") or "",
            "price": _num(valuation.get("current_price")),
            "total_market_cap": _num(valuation.get("total_market_cap")),
            "free_float_market_cap": _num(valuation.get("free_float_market_cap")),
            "pe_ttm": _num(valuation.get("pe_ttm")), "ps_ttm": _num(valuation.get("ps_ttm")),
            **{key: qfq.get(key) for key in PRICE_PERCENTILE_FIELDS},
            "return_1d": qfq.get("return_1d"), "return_5d": qfq.get("return_5d"), "return_20d": qfq.get("return_20d"),
            **{key: qfq.get(key) for key in BASIC_MARKET_FIELDS},
            "ma_alignment": qfq.get("ma_alignment"),
            "ma_alignment_duration": qfq.get("ma_alignment_duration"),
            "ma_alignment_ma": qfq.get("ma_alignment_ma"),
            "turnover_5_sum": qfq.get("turnover_5_sum"), "turnover_5_avg": qfq.get("turnover_5_avg"), "qfq_as_of": qfq.get("qfq_as_of"),
            "eps_ratio_5y": _num(qfq.get("eps_ratio_5y")), "eps_ratio_5y_years": qfq.get("eps_ratio_5y_years"),
            "eps_ratio_5y_factor": qfq.get("eps_ratio_5y_factor"), "eps_ratio_5y_eps_sum": qfq.get("eps_ratio_5y_eps_sum"),
            "eps_ratio_5y_price": qfq.get("eps_ratio_5y_price"),
            "blowup_break_volume_price_ok": qfq.get("blowup_break_volume_price_ok"), "blowup_break_va": qfq.get("blowup_break_va"),
            "blowup_break_vol_ratios": qfq.get("blowup_break_vol_ratios") or [], "blowup_break_return_5d": qfq.get("blowup_break_return_5d"),
            **{key: qfq.get(key) for key in LIMIT_UP_FIELDS},
            **{key: qfq.get(key) for key in TREND_TEMPLATE_FIELDS},
            "rps_20": _num(r.get("rps_20")), "rps_50": _num(r.get("rps_50")),
            "rps_120": _num(r.get("rps_120")), "rps_250": _num(r.get("rps_250")), "rps_total": round(total, 2),
            "mrs_score": _num(relative.get("mrs_score")), "mrs_label": relative.get("mrs_label"), "relative_strength_state": relative.get("relative_strength_state"), "relative_strength_state_label": relative.get("relative_strength_state_label"),
            "excess_return_5_pp": _num(relative.get("excess_return_5_pp")), "excess_return_20_pp": _num(relative.get("excess_return_20_pp")), "excess_return_50_pp": _num(relative.get("excess_return_50_pp")), "excess_return_120_pp": _num(relative.get("excess_return_120_pp")), "excess_return_250_pp": _num(relative.get("excess_return_250_pp")),
            "down_market_days_20": _num(relative.get("down_market_days_20")), "down_market_win_rate_20": _num(relative.get("down_market_win_rate_20")), "down_market_total_excess_pp_20": _num(relative.get("down_market_total_excess_pp_20")), "anti_fall_status": relative.get("anti_fall_status"),
            "composite_total": _num(composite.get("score")), "composite_mode": composite.get("mode"),
            "annual_total": _num(a.get("score")), "annual_dimensions": a.get("dimensions") or {}, "annual_derived": a.get("derived") or {},
            "annual_assessment_track": a.get("assessment_track"), "annual_coverage_weight": _num(a.get("coverage_weight")),
            "annual_score_version": a.get("score_version"), "annual_score_basis_track": a.get("score_basis_track"),
            "annual_score_comparable": a.get("score_comparable"), "annual_growth_quality_basis": a.get("growth_quality_basis"),
            "annual_cash_quality_basis": a.get("cash_quality_basis"),
            "quarterly_total": _num(q.get("score")), "quarterly_dimensions": q.get("dimensions") or {}, "quarterly_coverage_weight": _num(q.get("coverage_weight")),
            "quarterly_revenue_yoy": _num(q_quality.get("revenue_yoy")), "quarterly_ex_net_profit_yoy": _num(q_quality.get("ex_net_profit_yoy")),
            "quarterly_ttm_fcf_margin": _num(q_quality.get("ttm_fcf_margin")), "quarterly_profitability_status": q_quality.get("profitability_status"),
            "quarterly_high_or_critical_alert": q_quality.get("has_high_or_critical_alert"),
            "quarterly_triggered_red_flag_count": q.get("triggered_red_flag_count"),
            "report_release_return_pct": _num(release_performance.get("return_pct")),
            "report_release_entry_trading_day": release_performance.get("entry_trading_day"),
            "report_release_latest_close_as_of": release_performance.get("current_price_as_of"),
            "annual_period": a.get("anchor_period"),
            # 展示该股实际的最近报告期，而不是全局锚点
            "quarterly_period": q.get("period") or q.get("anchor_period"),
            "trend_daily": tech.get("trend"), "trend_daily_label": tech.get("trend_label"),
            "trend_weekly": qfq.get("trend_weekly"), "trend_weekly_label": qfq.get("trend_weekly_label"),
            "trend_monthly": qfq.get("trend_monthly"), "trend_monthly_label": qfq.get("trend_monthly_label"),
            "trend": tech.get("trend"), "trend_label": tech.get("trend_label"),
            "short_trend": tech.get("short_trend"), "short_trend_label": tech.get("short_trend_label"),
            "momentum": tech.get("momentum"), "momentum_label": tech.get("momentum_label"),
            "golden_cross": qfq.get("golden_cross"),
            "golden_cross_as_of": qfq.get("qfq_as_of") if qfq.get("golden_cross") is not None else None,
            "macd_cross": qfq.get("macd_cross"), "macd_cross_label": qfq.get("macd_cross_label"),
            "macd_cross_as_of": qfq.get("qfq_as_of") if qfq.get("macd_cross") is not None else None,
            "macd_cross_dif": qfq.get("macd_cross_dif"), "macd_cross_dea": qfq.get("macd_cross_dea"),
            "macd_cross_prev_dif": qfq.get("macd_cross_prev_dif"),
            "macd_cross_prev_dea": qfq.get("macd_cross_prev_dea"),
        })
    return rows, data_date


def _selected(params: dict[str, list[str]], key: str) -> set[str]:
    return {x.strip() for x in (params.get(key) or [""])[0].split(",") if x.strip()}

WYCKOFF_TYPES = {"Spring", "UT", "SOS", "SOW", "LPS", "LPSY"}
WYCKOFF_STATUSES = {"candidate", "confirmed", "invalidated"}
from app.swing_presentation import STARS_BY_STATE, presentation as swing_presentation
SWING_STATES = set(STARS_BY_STATE)
SWING_SCHEMA = 'swing-structure-v8'
SWING_RULE = 'swing-confirmed-5x5-pressure-line-ceiling-v8'
WYCKOFF_SCHEMA = "wyckoff-signals-v1"
WYCKOFF_RULE = "wyckoff-approved-20261103-v1"


@lru_cache(maxsize=1)
def _read_wyckoff_published(path: Path, file_identity: tuple[int, int, int]) -> dict[str, Any]:
    # One decoded publication per process; atomic replace changes inode even if timestamp granularity is coarse.
    return _read_json(path)


def _wyckoff_snapshot(day: str, historical: bool) -> dict[str, Any]:
    """Read only a complete, same-day QFQ publication of the approved rule."""
    path = FINAL / "wyckoff_signals" / f"{day}.json" if historical else FINAL / "wyckoff_signals_current.json"
    try:
        stat = path.stat()
        identity = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        identity = (-1, -1, -1)
    payload = _read_wyckoff_published(path, identity)
    if (payload.get("schema_version") != WYCKOFF_SCHEMA or
            payload.get("rule_version") != WYCKOFF_RULE or
            payload.get("price_basis") != "tdx_export_qfq" or
            payload.get("completeness") != "complete" or
            payload.get("as_of_date") != day or
            not isinstance(payload.get("stocks"), dict)):
        raise ValueError(f"威科夫 {day} 前复权全市场快照缺失、口径不一致或尚未完整发布；请先构建并核验该日期快照。")
    return payload


def _swing_snapshot(day: str, historical: bool, *, allow_lagged: bool = False) -> dict[str, Any]:
    """Filters require same-day QFQ; single-stock display may use a prior publication."""
    path = FINAL / 'swing_structure_v8' / f'{day}.json' if historical else FINAL / 'swing_structure_v8_current.json'
    try:
        stat = path.stat()
        identity = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        identity = (-1, -1, -1)
    payload = _read_wyckoff_published(path, identity)
    published_day = payload.get('as_of_date')
    try:
        valid_day = isinstance(published_day, str) and date.fromisoformat(published_day).isoformat() == published_day
    except ValueError:
        valid_day = False
    publication_date: str = published_day if isinstance(published_day, str) and valid_day else ''
    if (payload.get('schema_version') != SWING_SCHEMA or payload.get('rule_version') != SWING_RULE
        or payload.get('price_basis') != 'tdx_export_qfq'
        or not valid_day or (publication_date > day if allow_lagged and not historical else publication_date != day)
        or payload.get('completeness') != 'complete'
        or not isinstance(payload.get('stocks'), dict)):
        raise ValueError(f'波峰波谷 {day} 前复权全市场快照不可用、版本不符或未完整发布；不能返回空池。')
    return payload


def _expected_entry_status(source: dict) -> str | None:
    if source.get('status') == 'ok' and source.get('state') in (None, '证据不足'):
        return 'insufficient_state'
    return source.get('status')


def _swing_entry_snapshot(day: str, historical: bool, parent: dict) -> dict[str, Any]:
    """Require same-day complete entry evidence for every parent swing security."""
    path = FINAL / 'swing_state_runs_v5' / f'{day}.json' if historical else FINAL / 'swing_state_runs_v5_current.json'
    try:
        stat = path.stat()
        identity = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        identity = (-1, -1, -1)
    payload = _read_wyckoff_published(path, identity)
    stocks = payload.get('stocks')
    if (payload.get('schema_version') != 'swing-state-runs-v5'
        or payload.get('rule_version') != SWING_RULE
        or payload.get('price_basis') != 'tdx_export_qfq'
        or payload.get('completeness') != 'complete'
        or payload.get('as_of_date') != day
        or payload.get('max_entry_days') != 5
        or not isinstance(stocks, dict)
        or stocks.keys() != parent['stocks'].keys()
        or any(not isinstance(stocks[key], dict) or any(
            stocks[key].get(field) != (_expected_entry_status(source) if field == 'status' else source.get(field))
            for field in ('status', 'state', 'last_bar_date', 'source_sha256'))
            for key, source in parent['stocks'].items())):
        raise ValueError(f'波峰波谷状态时长 {day} 同日完整快照缺失、版本不符或与主快照不匹配；不能返回空池。')
    return payload

def _wyckoff_match(events: list[dict], types: set[str], statuses: set[str], since: str, day: str) -> dict | None:
    """Latest matching observation known by day; no later lifecycle evidence."""
    eligible = [event for event in events if isinstance(event, dict)
                and isinstance(event.get("date"), str) and since <= event["date"] <= day
                and (not types or event.get("type") in types)
                and (not statuses or event.get("status") in statuses)
                and (not event.get("confirmation_date") or event["confirmation_date"] <= day)
                and (not (event.get("invalidated_by") or {}).get("date") or event["invalidated_by"]["date"] <= day)]
    return max(eligible, key=lambda event: event["date"], default=None)

def _historical_universe(as_of_date: str) -> tuple[list[dict[str, Any]], str]:
    """Load one immutable point-in-time fundamental snapshot.

    The builder writes date-specific files, so this request never substitutes a
    current financial record for a historical date.
    """
    path = HISTORICAL_FUNDAMENTALS / f"{as_of_date}.json"
    payload = _read_json(path)
    if not payload or payload.get("as_of_date") != as_of_date or payload.get("schema_version") != "stock-filter-fundamental-history-v7":
        # Build only the requested trading date and cache it permanently.  A lock
        # prevents concurrent browser requests from launching duplicate scans.
        lock = HISTORICAL_FUNDAMENTALS / f"{as_of_date}.building"
        HISTORICAL_FUNDAMENTALS.mkdir(parents=True, exist_ok=True)
        if not lock.exists():
            try:
                lock.touch(exist_ok=False)
                log = open(HISTORICAL_FUNDAMENTALS / f"{as_of_date}.log", "a", encoding="utf-8")
                subprocess.Popen([sys.executable, str(ROOT / "scripts" / "build_stock_filter_fundamental_history.py"), "--trading-day", as_of_date, "--adopt-lock"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
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
                     "industry": industry.get("industry_level_2_name") or industry.get("industry_level_1_name") or "",
                     "industry_level_2_code": industry.get("industry_level_2_code") or "",
                     "industry_level_2_name": industry.get("industry_level_2_name") or "", "rps_total": None,
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
        requested_sort = (params.get("sort") or [""])[0].strip()
        as_of_date = (params.get("as_of_date") or [""])[0].strip()
        if as_of_date:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        sort = requested_sort or "pe_ttm"
        if sort not in SORT_FIELDS: raise ValueError("unsupported sort")
        presets = {name.strip() for value in params.get("preset", []) for name in value.split(",") if name.strip()}
        if presets - {"financial_reversal", "blowup_break", "trend_template", "turnover_high"}: raise ValueError("unsupported preset")
        if as_of_date:
            active_unsupported = next((name for name in sorted(HISTORICAL_LATEST_ONLY_PARAMS)
                                       if any(str(value or "").strip() for value in params.get(name, []))), None)
            if active_unsupported:
                label = HISTORICAL_PARAM_LABELS.get(active_unsupported, "该筛选条件")
                raise ValueError(f"{active_unsupported}（{label}）仅支持最新日期，历史日期禁止使用")
            requested_scope = (params.get("stock_scope") or [""])[0].strip().lower()
            if requested_scope == "csi300":
                raise ValueError("stock_scope=csi300 only supports the latest constituent list")
            if requested_sort and sort in HISTORICAL_LATEST_ONLY_SORTS:
                raise ValueError(f"sort={sort} only supports the latest date")
        ma_alignments = _selected(params, "ma_alignment")
        if ma_alignments - {"5/10/20", "10/20/30", "10/30/60", "20/60/120"}:
            raise ValueError("unsupported ma_alignment")
        ma_days = []
        for suffix in ("min", "max"):
            text = str((params.get(f"ma_alignment_days_{suffix}") or [""])[0] or "").strip()
            if text and (not text.isascii() or not text.isdecimal() or int(text) < 1):
                raise ValueError(f"ma_alignment_days_{suffix} must be a positive integer")
            ma_days.append(int(text) if text else None)
        ma_days_min, ma_days_max = ma_days
        if ma_days_min is not None and ma_days_max is not None and ma_days_min > ma_days_max:
            raise ValueError("ma_alignment_days_min must not exceed ma_alignment_days_max")
        ma_duration_active = ma_days_min is not None or ma_days_max is not None
        if as_of_date and (ma_alignments or ma_duration_active):
            raise ValueError("ma_alignment and its duration are not supported for historical dates")
        return_n_text = str((params.get("return_n_days") or [""])[0] or "").strip()
        return_n_bound_texts = [str((params.get(f"return_n_pct_{suffix}") or [""])[0] or "").strip()
                                for suffix in ("min", "max")]
        return_n_requested = bool(return_n_text or any(return_n_bound_texts))
        if return_n_requested:
            if not return_n_text or not return_n_text.isascii() or not return_n_text.isdecimal():
                raise ValueError("return_n_days must be an integer in 1..250")
            return_n_days = int(return_n_text)
            if return_n_days not in range(1, 251):
                raise ValueError("return_n_days must be an integer in 1..250")
            if not any(return_n_bound_texts):
                raise ValueError("return_n_days requires at least one return percentage bound")
            return_n_bounds = [float(text) if text else None for text in return_n_bound_texts]
            if any(value is not None and not math.isfinite(value) for value in return_n_bounds):
                raise ValueError("return_n_pct bounds must be finite")
            return_n_min, return_n_max = return_n_bounds
            if return_n_min is not None and return_n_max is not None and return_n_min > return_n_max:
                raise ValueError("return_n_pct_min must not exceed return_n_pct_max")
            if as_of_date:
                raise ValueError("custom N-day return is not supported for historical dates")
        else:
            return_n_days = return_n_min = return_n_max = None
        change_days_n_text = str((params.get("change_days_n") or [""])[0] or "").strip()
        change_bound_names = ("up_days_min", "up_days_max", "down_days_min", "down_days_max")
        change_bound_texts = [str((params.get(name) or [""])[0] or "").strip()
                              for name in change_bound_names]
        change_days_requested = bool(change_days_n_text or any(change_bound_texts))
        if change_days_requested:
            if (not change_days_n_text or not change_days_n_text.isascii()
                    or not change_days_n_text.isdecimal()):
                raise ValueError("change_days_n must be an integer in 1..250")
            change_days_n = int(change_days_n_text)
            if change_days_n not in range(1, 251):
                raise ValueError("change_days_n must be an integer in 1..250")
            if not any(change_bound_texts):
                raise ValueError("change_days_n requires at least one up/down day-count bound")
            change_bounds = []
            for name, text in zip(change_bound_names, change_bound_texts):
                if text and (not text.isascii() or not text.isdecimal() or int(text) > change_days_n):
                    raise ValueError(f"{name} must be an integer in 0..N")
                change_bounds.append(int(text) if text else None)
            up_days_min, up_days_max, down_days_min, down_days_max = change_bounds
            if up_days_min is not None and up_days_max is not None and up_days_min > up_days_max:
                raise ValueError("up_days_min must not exceed up_days_max")
            if down_days_min is not None and down_days_max is not None and down_days_min > down_days_max:
                raise ValueError("down_days_min must not exceed down_days_max")
            if (up_days_min or 0) + (down_days_min or 0) > change_days_n:
                raise ValueError("minimum up days plus minimum down days must not exceed N")
            if as_of_date:
                raise ValueError("N-day up/down counts are not supported for historical dates")
        else:
            change_days_n = up_days_min = up_days_max = down_days_min = down_days_max = None
        limit_up_n_text = str((params.get("limit_up_n_days") or [""])[0] or "").strip()
        if limit_up_n_text:
            if (not limit_up_n_text.isascii() or not limit_up_n_text.isdecimal()
                    or int(limit_up_n_text) not in range(1, 251)):
                raise ValueError("limit_up_n_days must be an integer in 1..250")
            limit_up_n_days = int(limit_up_n_text)
            if as_of_date:
                raise ValueError("limit_up_n_days is not supported for historical dates")
        else:
            limit_up_n_days = None
        niche_leader = (params.get("niche_leader") or [""])[0].strip().lower()
        if niche_leader not in {"", "yes", "no"}: raise ValueError("niche_leader must be yes or no")
        stock_scope = (params.get("stock_scope") or [""])[0].strip().lower() or "all"
        if stock_scope not in STOCK_SCOPE_LABELS:
            raise ValueError("stock_scope must be one of " + ", ".join(STOCK_SCOPE_LABELS))
        industry_l2_codes = _selected(params, "industry_l2_codes")
        concept_codes = _selected(params, "concept_codes")
        temperature_texts = _selected(params, "concept_temperature_levels")
        industry_temperature_texts = _selected(params, "industry_temperature_levels")
        if any(not value.isascii() or not value.isdecimal()
               for value in temperature_texts | industry_temperature_texts):
            raise ValueError("temperature levels must contain integers 0..5")
        concept_temperature_levels = {int(value) for value in temperature_texts}
        industry_temperature_levels = {int(value) for value in industry_temperature_texts}
        if (concept_temperature_levels | industry_temperature_levels) - set(range(6)):
            raise ValueError("temperature levels must contain integers 0..5")
        if as_of_date and industry_temperature_levels:
            raise ValueError("历史日期不支持当前行业温度范围，不能回退使用当前快照")
        if as_of_date and (concept_codes or concept_temperature_levels):
            raise ValueError("历史日期不支持当前概念及概念温度范围，不能回退使用当前快照")
        wyckoff_types = _selected(params, "wyckoff_type")
        wyckoff_statuses = _selected(params, "wyckoff_status")
        wyckoff_since = (params.get("wyckoff_since") or [""])[0].strip()
        if wyckoff_types - WYCKOFF_TYPES or wyckoff_statuses - WYCKOFF_STATUSES:
            raise ValueError("unsupported wyckoff type or status")
        if wyckoff_since and datetime.strptime(wyckoff_since, "%Y-%m-%d").strftime("%Y-%m-%d") != wyckoff_since:
            raise ValueError("invalid wyckoff_since")
        swing_states = _selected(params, 'swing_state')
        swing_tendencies = _selected(params, 'swing_tendency')
        swing_stars = _selected(params, 'swing_star')
        swing_observations = _selected(params, 'swing_observation')
        entry_raw = (params.get('swing_entry_days') or [''])[0].strip()
        if entry_raw and (not entry_raw.isascii() or not entry_raw.isdecimal()
                          or int(entry_raw) not in range(1, 6) or not swing_states):
            raise ValueError('swing_entry_days requires selected swing_state and integer 1..5')
        entry_days = int(entry_raw) if entry_raw else None
        if swing_states - SWING_STATES:
            raise ValueError('unsupported swing_state')
        if swing_tendencies - {'bull', 'bear', 'neutral', 'unknown'}:
            raise ValueError('unsupported swing_tendency')
        if swing_stars - {'bull:1','bull:2','bull:3','bear:1','bear:2','bear:3','neutral:0','unknown'}:
            raise ValueError('unsupported swing_star')
        if swing_observations - {'new_low_risk', 'pressure_line'}:
            raise ValueError('unsupported swing_observation')
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_filter", "message": str(exc)}}
    try:
        ranges = {k: _range(params, k) for k in ("rps_20", "rps_50", "rps_120", "rps_250", "rps_total", "mrs_score", "excess_return_5_pp", "excess_return_20_pp", "excess_return_50_pp", "excess_return_120_pp", "excess_return_250_pp", "down_market_win_rate_20", "down_market_total_excess_pp_20", "price", "total_market_cap", "free_float_market_cap", "pe_ttm", "ps_ttm", "return_1d", "return_5d", "return_20d", "volume_ratio_5", "ma5_distance_pct", "ma10_distance_pct", "ma20_distance_pct", "turnover_5_sum", "turnover_5_avg", "composite_total", "annual_total", "quarterly_total", "eps_ratio_5y")}
        for key in BASIC_MARKET_FILTERS:
            for suffix in ("min", "max"):
                raw = str((params.get(f"{key}_{suffix}") or [""])[0] or "").strip()
                if raw and (not math.isfinite(float(raw))):
                    raise ValueError(f"{key}_{suffix} must be finite")
        percentile_bounds = []
        for suffix in ("min", "max"):
            raw = (params.get(f"price_percentile_5y_{suffix}") or [""])[0]
            text = str(raw or "").strip()
            value = float(text) if text else None
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError("price_percentile_5y bounds must be finite numbers in 0..100")
            percentile_bounds.append(value)
        lo, hi = percentile_bounds
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("price_percentile_5y_min must not exceed price_percentile_5y_max")
        ranges["price_percentile_5y"] = (lo, hi)
        turnover_bounds = []
        for suffix in ("min", "max"):
            text = str((params.get(f"turnover_percentile_1y_{suffix}") or [""])[0] or "").strip()
            value = float(text) if text else None
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError("turnover_percentile_1y bounds must be finite numbers in 0..100")
            turnover_bounds.append(value)
        if turnover_bounds[0] is not None and turnover_bounds[1] is not None and turnover_bounds[0] > turnover_bounds[1]:
            raise ValueError("turnover_percentile_1y_min must not exceed turnover_percentile_1y_max")
        ranges["turnover_percentile_1y"] = tuple(turnover_bounds)
        pe_bounds = []
        for suffix in ("min", "max"):
            raw = (params.get(f"pe_percentile_5y_{suffix}") or [""])[0]
            value = float(raw) if str(raw).strip() else None
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError("pe_percentile_5y bounds must be finite numbers in 0..100")
            pe_bounds.append(value)
        if pe_bounds[0] is not None and pe_bounds[1] is not None and pe_bounds[0] > pe_bounds[1]:
            raise ValueError("pe_percentile_5y_min must not exceed pe_percentile_5y_max")
        ranges["pe_percentile_5y"] = tuple(pe_bounds)
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
    dynamic_qfq = _qfq_latest() if (return_n_requested or change_days_requested) else {}
    return_n_qfq = dynamic_qfq if return_n_requested else {}
    if return_n_requested:
        assert isinstance(return_n_days, int)
    if return_n_requested and rows and not any(
        isinstance((metric := return_n_qfq.get((row["market"], row["symbol"]))), dict)
        and metric.get("qfq_as_of") == data_date
        and isinstance(metric.get("return_close_history"), list)
        and len(metric["return_close_history"]) > return_n_days
        for row in rows
    ):
        return {"ok": False, "error": {"code": "return_n_unavailable",
            "message": f"{data_date} 的前复权N日涨跌幅快照缺失、过期或历史不足，请重建同日行情快照"}}
    if change_days_requested:
        assert isinstance(change_days_n, int)
        change_n = change_days_n
    else:
        change_n = 0
    if change_days_requested and rows and not any(
        isinstance((metric := dynamic_qfq.get((row["market"], row["symbol"]))), dict)
        and metric.get("qfq_as_of") == data_date
        and isinstance(metric.get("return_close_history"), list)
        and len(metric["return_close_history"]) > change_n
        for row in rows
    ):
        return {"ok": False, "error": {"code": "change_days_unavailable",
            "message": f"{data_date} 的前复权涨跌天数快照缺失、过期或历史不足，请重建同日行情快照"}}
    turnover_active = ranges["turnover_percentile_1y"] != (None, None) or sort == "turnover_percentile_1y" or "turnover_high" in presets
    if as_of_date:
        # Historical rows are immutable date-specific publications, never today's snapshot.
        turnover_ready = bool(rows) and all(
            row.get("turnover_percentile_1y_as_of") == data_date for row in rows)
    else:
        turnover_payload = _read_turnover_snapshot()
        turnover_map = turnover_payload.get("stocks")
        turnover_ready = (turnover_payload.get("schema_version") == "stock-filter-turnover-percentile-v2"
                          and turnover_payload.get("as_of_date") == data_date
                          and isinstance(turnover_map, dict)
                          and all(f"{row['market']}:{row['symbol']}" in turnover_map for row in rows))
        if turnover_ready:
            rows = [{**row, **turnover_map[f"{row['market']}:{row['symbol']}"]} for row in rows]
        else:
            rows = [{**row, "turnover_percentile_1y": None,
                     "turnover_percentile_1y_status": "stale_snapshot"} for row in rows]
    if turnover_active and not turnover_ready:
        return {"ok": False, "error": {"code": "turnover_percentile_unavailable",
                                       "message": f"筛选日 {data_date} 换手率一年分位快照缺失、覆盖不完整或过期；请先构建同日快照"}}
    turnover_crosses = None
    if "turnover_high" in presets:
        from app.stock_filter_turnover_cross import crossing_keys
        turnover_crosses = crossing_keys(data_date, TURNOVER_PERCENTILE_SNAPSHOT.parent)
        if turnover_crosses is None:
            return {"ok": False, "error": {"code": "turnover_cross_unavailable",
                "message": f"{data_date} 缺少完整逐日换手分位证据或此前30个交易日覆盖，请先发布可审计快照"}}
        for row in rows:
            evidence = turnover_crosses.get(f"{row['market']}:{row['symbol']}")
            if evidence and _num(row.get('turnover_percentile_1y')) != evidence['percentile']:
                return {"ok": False, "error": {"code": "turnover_cross_unavailable",
                    "message": f"{data_date} 逐日换手证据与筛选日快照的分位不一致"}}
    if sort == "price_percentile_5y" and rows and not any(
        row.get("qfq_as_of") == data_date and _num(row.get("price_percentile_5y")) is not None
        for row in rows
    ):
        return {"ok": False, "error": {"code": "price_percentile_unavailable",
                                       "message": f"筛选日 {data_date} 无同日有效股价五年分位，不能排序"}}
    basic_active = [key for key in BASIC_MARKET_FILTERS if ranges[key] != (None, None)]
    if basic_active and rows and not any(
        row.get("qfq_as_of") == data_date and all(row.get(key) is not None for key in basic_active) for row in rows
    ):
        return {"ok": False, "error": {"code": "market_metrics_unavailable",
                                      "message": f"{data_date} 的前复权基础行情快照缺失或过期，请先重建同日快照"}}
    if (ma_alignments or ma_duration_active) and rows and not any(
        row.get("qfq_as_of") == data_date and isinstance(row.get("ma_alignment"), list)
        and (not ma_duration_active or isinstance(row.get("ma_alignment_duration"), dict))
        for row in rows
    ):
        return {"ok": False, "error": {"code": "ma_alignment_unavailable",
                                      "message": f"{data_date} 的前复权均线多头快照缺失或过期，请先构建同日行情快照"}}
    pe_status = "ready" if as_of_date else "stale"
    if as_of_date:
        if (ranges["pe_percentile_5y"] != (None, None) or sort == "pe_percentile_5y") and any(
            row.get("pe_percentile_5y") is not None and row.get("pe_percentile_5y_price_date") != data_date for row in rows
        ):
            return {"ok": False, "error": {"code": "pe_percentile_unavailable", "message": "历史PE分位的价格日期与所选筛选日不一致"}}
    else:
        pe_payload = _read_pe_percentile_snapshot()
        pe_map = pe_payload.get("stocks") if isinstance(pe_payload, dict) else None
        if (pe_payload.get("schema_version") == "stock-filter-pe-percentile-v1"
                and pe_payload.get("as_of_date") == data_date and isinstance(pe_map, dict)
                and all(f"{r['market']}:{r['symbol']}" in pe_map for r in rows)):
            pe_status = "ready"
            rows = [{**row, **pe_map.get(f"{row['market']}:{row['symbol']}", {})} for row in rows]
        else:
            if ranges["pe_percentile_5y"] != (None, None) or sort == "pe_percentile_5y":
                return {"ok": False, "error": {"code": "pe_percentile_unavailable", "message": f"PE-TTM五年分位快照缺失、覆盖不完整或不在筛选日 {data_date}；请先完成对应交易日构建"}}
            rows = [{**row, "pe_percentile_5y": None, "pe_percentile_5y_status": "stale_snapshot"} for row in rows]
    if sort == "pe_percentile_5y" and (
        not any(_num(row.get("pe_percentile_5y")) is not None for row in rows)
        or any(_num(row.get("pe_percentile_5y")) is not None
               and row.get("pe_percentile_5y_price_date") != data_date for row in rows)
    ):
        return {"ok": False, "error": {"code": "pe_percentile_unavailable",
                                       "message": f"筛选日 {data_date} 无同日有效PE五年分位，不能排序"}}
    wyckoff_snapshot = None
    if wyckoff_types or wyckoff_statuses or wyckoff_since:
        try:
            wyckoff_snapshot = _wyckoff_snapshot(data_date, bool(as_of_date))
        except ValueError as exc:
            return {"ok": False, "error": {"code": "wyckoff_snapshot_unavailable", "message": str(exc)}}
    if wyckoff_snapshot is not None:
        stock_map = wyckoff_snapshot["stocks"]
        missing_wyckoff = [f"{row['market']}:{row['symbol']}" for row in rows
                           if not isinstance(stock_map.get(f"{row['market']}:{row['symbol']}"), dict)]
        if missing_wyckoff:
            return {"ok": False, "error": {"code": "wyckoff_snapshot_unavailable",
                                         "message": f"威科夫快照缺少筛选池证券 {len(missing_wyckoff)} 只（例如 {missing_wyckoff[0]}），不能将缺口当作无信号。"}}
    swing_snapshot = None
    if swing_states or swing_tendencies or swing_stars or swing_observations or entry_days is not None:
        try:
            swing_snapshot = _swing_snapshot(data_date, bool(as_of_date))
        except ValueError as exc:
            return {'ok': False, 'error': {'code': 'swing_snapshot_unavailable', 'message': str(exc)}}
        missing = [f"{row['market']}:{row['symbol']}" for row in rows
                   if not isinstance(swing_snapshot['stocks'].get(f"{row['market']}:{row['symbol']}"), dict)]
        if missing:
            from app.swing_snapshot import discover_universe
            current_tnf = {f'{market}:{code}' for market, code, _ in discover_universe()}
            broken = [symbol for symbol in missing if symbol in current_tnf]
            if broken:
                return {'ok': False, 'error': {'code': 'swing_snapshot_unavailable',
                    'message': f'波峰波谷完整快照缺少当前TNF证券 {len(broken)} 只（例如 {broken[0]}），不能当作无匹配。'}}
            outside_swing_tnf = missing
        else:
            outside_swing_tnf = []
    else:
        outside_swing_tnf = []
    entry_snapshot = None
    if entry_days is not None:
        assert swing_snapshot is not None
        try:
            entry_snapshot = _swing_entry_snapshot(data_date, bool(as_of_date), swing_snapshot)
        except ValueError as exc:
            return {'ok': False, 'error': {'code': 'swing_entry_snapshot_unavailable', 'message': str(exc)}}
    if "trend_template" in presets and rows and all(
            row.get("trend_template_status") is None for row in rows):
        # 老的历史快照没有趋势模版字段；不能静默返回空池
        return {"ok": False, "error": {
            "code": "trend_template_unavailable",
            "message": "该日期的历史快照未包含趋势模版指标，请先重建该日期的历史基本面快照",
        }}
    daily_trends = _selected(params, "trend_daily") or _selected(params, "trend")
    weekly_trends = _selected(params, "trend_weekly")
    monthly_trends = _selected(params, "trend_monthly")
    macds, crosses = _selected(params, "macd_cross"), _selected(params, "golden_cross")
    if macds and as_of_date:
        return {"ok": False, "error": {"code": "macd_cross_unavailable",
                                      "message": "历史日期 MACD 金叉尚无同日有效前复权快照，不能使用旧技术标记"}}
    if macds and rows and not any(
        row.get("macd_cross_as_of") == data_date and row.get("qfq_as_of") == data_date
        and isinstance(row.get("macd_cross"), str) for row in rows
    ):
        return {"ok": False, "error": {"code": "macd_cross_unavailable",
                                      "message": f"{data_date} 前复权 MACD 金叉快照缺失或过期，请重建同日行情快照"}}
    if crosses and as_of_date:
        return {"ok": False, "error": {"code": "golden_cross_unavailable",
                                      "message": "历史日期均线金叉尚无同日有效前复权快照，不能使用当前快照代替"}}
    if crosses and rows and not any(
        row.get("golden_cross_as_of") == data_date and row.get("qfq_as_of") == data_date
        and isinstance(row.get("golden_cross"), str) for row in rows
    ):
        return {"ok": False, "error": {"code": "golden_cross_unavailable",
                                      "message": f"{data_date} 前复权均线金叉快照缺失或过期，请重建同日行情快照"}}
    market = (params.get("market") or [""])[0].strip().lower()
    # 01 股票范围先锁定股票池，再套用其余条件。
    scoped_rows = [row for row in rows if matches_scope(row.get("market"), row.get("symbol"), stock_scope)]
    effective_industry_codes: set[str] = set()
    effective_concept_codes: set[str] = set()
    if industry_l2_codes or industry_temperature_levels or concept_codes or concept_temperature_levels:
        try:
            scope_index = stock_scope_index()
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "error": {"code": "scope_snapshot_unavailable", "message": f"行业/概念范围快照不可用：{exc}"}}
        known_industries = set(scope_index.get("industry_members") or {})
        known_concepts = set(scope_index.get("concept_members") or {})
        if industry_l2_codes - known_industries:
            return {"ok": False, "error": {"code": "invalid_filter", "message": "包含未知二级行业代码"}}
        if concept_codes - known_concepts:
            return {"ok": False, "error": {"code": "invalid_filter", "message": "包含未知概念代码"}}
        scoped_rows, effective_industry_codes, effective_concept_codes = filter_rows_by_scope(
            scoped_rows,
            scope_index,
            industry_codes=industry_l2_codes,
            industry_temperature_levels=industry_temperature_levels,
            concept_codes=concept_codes,
            temperature_levels=concept_temperature_levels,
        )
    if limit_up_n_days is not None:
        missing_limit_up = [f"{row['market']}:{row['symbol']}" for row in scoped_rows
                            if (row.get('qfq_as_of') is not None and (
                                row.get('limit_up_raw_as_of') != row.get('qfq_as_of')
                                or row.get('limit_up_status') != 'ok'
                                or row.get('limit_up_price_basis') != 'raw_unadjusted'
                                or (row.get('limit_up_recent_days_ago') is not None
                                    and type(row.get('limit_up_recent_days_ago')) is not int)))]
        if missing_limit_up:
            return {"ok": False, "error": {"code": "limit_up_unavailable",
                "message": f"{data_date} 的原始价涨停快照缺失、过期或覆盖不完整（例如 {missing_limit_up[0]}），请重建同日行情快照"}}
    lagged_wyckoff = []
    if wyckoff_snapshot is not None:
        lagged_wyckoff = [f"{row['market']}:{row['symbol']}" for row in scoped_rows
                          if wyckoff_snapshot["stocks"][f"{row['market']}:{row['symbol']}"].get("last_bar_date") != data_date]
    lagged_set = set(lagged_wyckoff)
    lagged_swing = ([f"{row['market']}:{row['symbol']}" for row in scoped_rows
                     if (swing_snapshot['stocks'].get(f"{row['market']}:{row['symbol']}") or {}).get('last_bar_date') not in (None, data_date)]
                    if swing_snapshot is not None else [])
    lagged_swing_set = set(lagged_swing)
    filtered = []
    excluded_missing = 0
    excluded_entry = 0
    for row in scoped_rows:
        if wyckoff_snapshot is not None and f"{row['market']}:{row['symbol']}" in lagged_set: continue
        if limit_up_n_days is not None:
            if row.get('limit_up_raw_as_of') != data_date:
                excluded_missing += 1
                continue
            days_ago = row.get('limit_up_recent_days_ago')
            if days_ago is None or days_ago >= limit_up_n_days:
                continue
            row = {**row, 'limit_up_filter_n_days': limit_up_n_days}
        if return_n_requested:
            metric = return_n_qfq.get((row["market"], row["symbol"])) or {}
            history = metric.get("return_close_history")
            if (metric.get("qfq_as_of") != data_date or not isinstance(history, list)
                    or len(history) <= return_n_days):
                excluded_missing += 1
                continue
            start_price, end_price = _num(history[-1-return_n_days]), _num(history[-1])
            if start_price is None or end_price is None or start_price <= 0 or end_price <= 0:
                excluded_missing += 1
                continue
            return_n_pct = (end_price / start_price - 1.0) * 100.0
            if ((return_n_min is not None and return_n_pct < return_n_min)
                    or (return_n_max is not None and return_n_pct > return_n_max)):
                continue
            row = {**row, "return_n_days": return_n_days,
                   "return_n_pct": round(return_n_pct, 4),
                   "return_n_start_close": start_price, "return_n_end_close": end_price,
                   "return_n_as_of": data_date, "return_n_price_basis": "tdx_export_qfq"}
        if change_days_requested:
            metric = dynamic_qfq.get((row["market"], row["symbol"])) or {}
            history = metric.get("return_close_history")
            if (metric.get("qfq_as_of") != data_date or not isinstance(history, list)
                    or len(history) <= change_n):
                excluded_missing += 1
                continue
            window = [_num(value) for value in history[-1-change_n:]]
            if any(value is None or value <= 0 for value in window):
                excluded_missing += 1
                continue
            numeric_window = [float(value) for value in window if value is not None]
            up_days = sum(current > previous for previous, current in zip(numeric_window, numeric_window[1:]))
            down_days = sum(current < previous for previous, current in zip(numeric_window, numeric_window[1:]))
            flat_days = change_n - up_days - down_days
            if ((up_days_min is not None and up_days < up_days_min)
                    or (up_days_max is not None and up_days > up_days_max)
                    or (down_days_min is not None and down_days < down_days_min)
                    or (down_days_max is not None and down_days > down_days_max)):
                continue
            row = {**row, "change_days_n": change_n, "up_days": up_days,
                   "down_days": down_days, "flat_days": flat_days,
                   "change_days_as_of": data_date,
                   "change_days_price_basis": "tdx_export_qfq"}
        if basic_active and row.get("qfq_as_of") != data_date:
            excluded_missing += 1
            continue
        if ma_alignments or ma_duration_active:
            if (row.get("qfq_as_of") != data_date or not isinstance(row.get("ma_alignment"), list)
                    or (ma_duration_active and not isinstance(row.get("ma_alignment_duration"), dict))):
                excluded_missing += 1
                continue
            current_groups = set(row["ma_alignment"])
            if ma_alignments and not ma_alignments.issubset(current_groups):
                continue
            eligible_groups = ma_alignments if ma_alignments else current_groups
            if not eligible_groups:
                continue
            if ma_duration_active:
                durations = row["ma_alignment_duration"]
                duration_matches = [
                    type(durations.get(group)) is int
                    and (ma_days_min is None or durations[group] >= ma_days_min)
                    and (ma_days_max is None or durations[group] <= ma_days_max)
                    for group in eligible_groups
                ]
                if not (all(duration_matches) if ma_alignments else any(duration_matches)):
                    continue
        if turnover_active and row.get("turnover_percentile_1y_as_of") != data_date:
            excluded_missing += 1
            continue
        if market and row["market"] != market: continue
        if "financial_reversal" in presets and not matches_financial_reversal(row): continue
        if "blowup_break" in presets and not matches_blowup_break(row): continue
        if "trend_template" in presets and not matches_trend_template(row): continue
        if "turnover_high" in presets:
            evidence = turnover_crosses.get(f"{row['market']}:{row['symbol']}")
            if evidence is None: continue
            gain_5d = _num(row.get('blowup_break_return_5d'))
            if row.get('qfq_as_of') != data_date or gain_5d is None:
                excluded_missing += 1
                continue
            if not 0 < gain_5d < 20: continue
            row = {**row, 'turnover_first_cross_75_30d': evidence}
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
        if macds:
            if row.get("macd_cross_as_of") != data_date or row.get("qfq_as_of") != data_date:
                excluded_missing += 1
                continue
            row_macds = {value.strip() for value in str(row.get("macd_cross") or "").split(",") if value.strip()}
            if not macds.issubset(row_macds): continue
        if crosses:
            if row.get("golden_cross_as_of") != data_date or row.get("qfq_as_of") != data_date:
                excluded_missing += 1
                continue
            row_crosses = {value.strip() for value in str(row.get("golden_cross") or "").split(",") if value.strip()}
            if not crosses.issubset(row_crosses): continue
        if wyckoff_snapshot is not None:
            stock = wyckoff_snapshot["stocks"].get(f"{row['market']}:{row['symbol']}") or {}
            event = _wyckoff_match(stock.get("events") or [], wyckoff_types, wyckoff_statuses,
                                   wyckoff_since, data_date)
            if event is None: continue
            # Only filtered rows receive event evidence; the source snapshot is never mutated.
            row = {**row, "wyckoff_signal": event}
        if swing_snapshot is not None:
            stock = swing_snapshot['stocks'].get(f"{row['market']}:{row['symbol']}")
            if stock is None:
                stock = {'status':'out_of_current_tnf', 'state':None, 'last_bar_date':None,
                         'reason':'筛选基础池含该证券，但当前TNF研究清单不覆盖；不推断峰谷状态'}
            elif stock.get('last_bar_date') != data_date:
                stock = {**stock, 'state': None, 'status': 'stale_qfq',
                         'new_low_risk': None, 'pressure_line': None,
                         'reason': f"前复权最新有效日 {stock.get('last_bar_date')} 与筛选日 {data_date} 不符"}
            view = swing_presentation(stock)
            star = (f"{view['tendency']}:{view['star_count']}" if view['star_count'] is not None
                    else 'unknown' if view['tendency'] == 'unknown' else 'caution')
            selected = (not (swing_states or swing_tendencies or swing_stars)
                        or (stock.get('state') in swing_states and stock.get('status') == 'ok')
                        or view['tendency'] in swing_tendencies or star in swing_stars)
            if not selected or (swing_observations and not (
                stock.get('status') == 'ok' and (
                    ('new_low_risk' in swing_observations and stock.get('new_low_risk')) or
                    ('pressure_line' in swing_observations and
                     isinstance(stock.get('pressure_line'), dict) and
                     stock['pressure_line'].get('status') in ('triggered', 'sustained')))
            )):
                continue
            if entry_snapshot is not None:
                # Entry is an AND gate on the explicitly selected complete state,
                # never an OR escape via a tendency/star on a different state.
                run = entry_snapshot['stocks'].get(f"{row['market']}:{row['symbol']}", {}).get('state_run')
                if (stock.get('status') != 'ok' or stock.get('state') not in swing_states
                    or not isinstance(run, dict) or run.get('state') != stock['state']
                    or run.get('through_date') != data_date
                    or run.get('start_confirmed') is not True
                    or type(run.get('trading_days')) is not int
                    or not 1 <= run['trading_days'] <= entry_days):
                    excluded_entry += 1
                    continue
                stock = {**stock, 'state_run': run}
            row = {**row, 'swing_structure': {**stock, **view}}
        filtered.append(row)
    industry_counts: dict[tuple[str, str], int] = {}
    unknown_industry = 0
    for row in filtered:
        industry_code = str(row.get("industry_level_2_code") or "").strip()
        industry_name = str(row.get("industry_level_2_name") or row.get("industry") or "").strip()
        if not industry_name:
            industry_code, industry_name = "", "未分类"
            unknown_industry += 1
        key = (industry_code, industry_name)
        industry_counts[key] = industry_counts.get(key, 0) + 1
    distribution_total = len(filtered)
    try:
        distribution_scope_index = stock_scope_index()
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        distribution_scope_index = {}
    temperature_lookup = distribution_scope_index.get("industry_temperature") or {}
    industry_distribution_rows = []
    for (code, name), count in industry_counts.items():
        temperature = temperature_lookup.get(code) or {}
        industry_distribution_rows.append({
            "industry_code": code, "industry_name": name, "count": count,
            "pct": round(count / distribution_total * 100.0, 2) if distribution_total else 0.0,
            "temperature": temperature.get("temperature"),
            "temperature_label": temperature.get("temperature_label") or "数据不足",
            "temperature_previous": temperature.get("temperature_previous"),
            "temperature_previous_label": temperature.get("temperature_previous_label") or "数据不足",
            "temperature_change": temperature.get("temperature_change"),
            "temperature_trend": temperature.get("temperature_trend") or "unknown",
            "temperature_trend_label": temperature.get("temperature_trend_label") or "数据不足",
            "temperature_previous_gap_days": temperature.get("temperature_previous_gap_days"),
        })
    industry_distribution_rows.sort(
        key=lambda item: (item["industry_name"] == "未分类", -item["count"], item["industry_name"], item["industry_code"])
    )
    industry_distribution = {
        "total": distribution_total,
        "classified": distribution_total - unknown_industry,
        "unknown": unknown_industry,
        "membership_basis": "current_industry_membership",
        "temperature_as_of": distribution_scope_index.get("industry_temperature_as_of"),
        "temperature_window": distribution_scope_index.get("industry_temperature_window"),
        "rows": industry_distribution_rows,
    }
    requested_order = (params.get("order") or [""])[0].lower()
    default_order = "asc" if sort in {"pe_ttm", "pe_percentile_5y", "price_percentile_5y"} else "desc"
    reverse = (requested_order or default_order) != "asc"
    def sort_key(row: dict[str, Any]) -> tuple[bool, float]:
        number = (_num(row.get(sort)) if sort not in {"price_percentile_5y", "turnover_percentile_1y"}
                  or row.get("qfq_as_of" if sort == "price_percentile_5y" else "turnover_percentile_1y_as_of") == data_date
                  else None)
        return number is None, (-number if reverse else number) if number is not None else 0.0
    filtered.sort(key=sort_key)
    total = len(filtered); start = (page - 1) * PAGE_SIZE
    page_rows = filtered[start:start + PAGE_SIZE]
    if swing_snapshot is None:
        # Optional display enrichment never changes the selected universe. Historical
        # pages may show no state, but must never inherit the current publication.
        try:
            display_snapshot = _swing_snapshot(data_date, bool(as_of_date))
        except (ValueError, FileNotFoundError):
            display_snapshot = None
        if display_snapshot is not None:
            enriched = []
            for row in page_rows:
                stock = display_snapshot['stocks'].get(f"{row['market']}:{row['symbol']}")
                if stock is not None:
                    if stock.get('last_bar_date') != data_date:
                        stock = {**stock, 'state': None, 'status': 'stale_qfq',
                                 'new_low_risk': None, 'pressure_line': None, 'line_break_observation': None}
                    row = {**row, 'swing_structure': {**stock, **swing_presentation(stock)}}
                enriched.append(row)
            page_rows = enriched
    return {"ok": True, "data_as_of": data_date, "effective_trade_date": data_date, "is_historical": bool(as_of_date),
            "sort": sort,
            "pe_percentile_snapshot": {"status": pe_status, "as_of_date": data_date if pe_status == "ready" else None},
            "stock_scope": stock_scope, "stock_scope_label": STOCK_SCOPE_LABELS[stock_scope],
            "industry_distribution": industry_distribution,
            "scope_selection": {"industry_l2_codes": sorted(industry_l2_codes),
                                "industry_temperature_levels": sorted(industry_temperature_levels),
                                "effective_industry_codes": sorted(effective_industry_codes),
                                "concept_codes": sorted(concept_codes),
                                "concept_temperature_levels": sorted(concept_temperature_levels),
                                "effective_concept_codes": sorted(effective_concept_codes)},
            "return_n_filter": ({"days": return_n_days, "min_pct": return_n_min,
                                 "max_pct": return_n_max, "price_basis": "tdx_export_qfq",
                                 "definition": "close_today/close_N_valid_trading_days_ago-1"}
                                if return_n_requested else None),
            "change_days_filter": ({"days": change_days_n, "up_min": up_days_min,
                                    "up_max": up_days_max, "down_min": down_days_min,
                                    "down_max": down_days_max, "price_basis": "tdx_export_qfq",
                                    "definition": "compare_each_valid_close_with_previous_valid_close"}
                                   if change_days_requested else None),
            "limit_up_filter": ({"days": limit_up_n_days, "price_basis": "raw_unadjusted",
                                 "definition": "at_least_one_exact_close_limit_up_in_latest_N_valid_trading_days",
                                 "window_includes_as_of_day": True}
                                if limit_up_n_days is not None else None),
            "total_universe": len(scoped_rows), "universe_total": len(rows), "total_matched": total,
            "page": page, "page_size": PAGE_SIZE, "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "rows": page_rows, "excluded_missing": excluded_missing,
            "wyckoff_snapshot": ({**{key: wyckoff_snapshot.get(key) for key in ("schema_version", "rule_version", "as_of_date", "price_basis", "completeness")},
                                   "excluded_lagged": len(lagged_wyckoff), "lagged_symbols": lagged_wyckoff}
                                 if wyckoff_snapshot is not None else None),
            'swing_snapshot': ({**{key: swing_snapshot.get(key) for key in ('schema_version','rule_version','as_of_date','price_basis','completeness')},
                                'excluded_lagged': len(lagged_swing), 'lagged_symbols': lagged_swing,
                                'outside_current_tnf': len(outside_swing_tnf)}
                               if swing_snapshot is not None else None),
            'swing_entry_snapshot': ({'schema_version': entry_snapshot['schema_version'],
                                     'as_of_date': entry_snapshot['as_of_date'],
                                     'max_entry_days': entry_snapshot['max_entry_days'],
                                     'coverage': entry_snapshot.get('coverage') or {},
                                     'selected_days': entry_days, 'excluded_after_other_filters': excluded_entry}
                                    if entry_snapshot is not None else None),
            "capabilities": {"available": ["rps", "financial_health", "trend", "macd", "ma_golden_cross", "ma_alignment_qfq", "limit_up_raw_snapshot", "wyckoff_qfq_snapshot", "swing_structure_qfq_snapshot"],
                             "pending_snapshot": ["basic_market", "annual_derived"]}}
