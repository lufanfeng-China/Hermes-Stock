"""Recent 3-year financial report loading."""
import importlib
import json
import re
from datetime import datetime
from functools import lru_cache

from app.financial.health import build_financial_health
from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.financial.industry_position import build_industry_financial_position
from app.financial.composite_health import build_composite_financial_health


def _cash_profit_ratio(metrics: dict[str, object] | None) -> float | None:
    """Operating cash flow ÷ deducted profit; missing/zero denominator stays unavailable."""
    if not isinstance(metrics, dict):
        return None
    try:
        ocf, profit = float(metrics.get("ocf")), float(metrics.get("ex_net_profit"))
    except (TypeError, ValueError):
        return None
    return ocf / profit if profit != 0 else None


def build_cash_profit_peer_values(reports: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Materialize annual, reported-quarter, and TTM cash-profit ratios for one stock."""
    by_period = {str(row.get("period") or ""): row for row in reports if isinstance(row, dict) and row.get("period")}

    def value(period: str) -> float | None:
        row = by_period.get(period) or {}
        return _cash_profit_ratio(row.get("metrics") if isinstance(row, dict) else None)

    def growth(current: float | None, prior: float | None) -> float | None:
        return (current / prior - 1) * 100 if current is not None and prior not in (None, 0) else None

    annual_periods = sorted(period for period in by_period if period.endswith("A"))
    annual_period = annual_periods[-1] if annual_periods else None
    annual_value = value(annual_period) if annual_period else None
    annual_prior = f"{int(annual_period[:4]) - 1}A" if annual_period else None

    quarter_periods = sorted(period for period in by_period if len(period) == 6 and period[4:] in {"Q1", "Q2", "Q3"})
    quarter_period = quarter_periods[-1] if quarter_periods else None
    quarter_value = value(quarter_period) if quarter_period else None
    prior_quarter = f"{int(quarter_period[:4]) - 1}{quarter_period[4:]}" if quarter_period else None

    ttm_value = ttm_prior_value = None
    if quarter_period:
        year, suffix = int(quarter_period[:4]), quarter_period[4:]
        prior_annual, prior_same = f"{year - 1}A", f"{year - 1}{suffix}"
        current_row, annual_row, same_row = by_period.get(quarter_period), by_period.get(prior_annual), by_period.get(prior_same)
        def ttm_ratio(current_row, annual_row, same_row):
            try:
                cm, am, sm = current_row["metrics"], annual_row["metrics"], same_row["metrics"]
                ocf = float(cm["ocf"]) + float(am["ocf"]) - float(sm["ocf"])
                profit = float(cm["ex_net_profit"]) + float(am["ex_net_profit"]) - float(sm["ex_net_profit"])
                return ocf / profit if profit != 0 else None
            except (TypeError, ValueError, KeyError):
                return None
        ttm_value = ttm_ratio(current_row, annual_row, same_row)
        ttm_prior_value = ttm_ratio(same_row, by_period.get(f"{year - 2}A"), by_period.get(f"{year - 2}{suffix}"))

    return {
        "annual": {"period": annual_period, "value": annual_value, "yoy_pct": growth(annual_value, value(annual_prior) if annual_prior else None)},
        "quarter": {"period": quarter_period, "value": quarter_value, "yoy_pct": growth(quarter_value, value(prior_quarter) if prior_quarter else None)},
        "ttm": {"period": quarter_period, "value": ttm_value, "yoy_pct": growth(ttm_value, ttm_prior_value)},
    }


def build_financial_reversal_indicator(health: dict[str, object], monitor: dict[str, object]) -> dict[str, object]:
    """Evaluate the stock-analysis payload against the filter page's strict reversal rule."""
    from app.stock_filter import matches_financial_reversal

    realtime = monitor.get("realtime_score") if isinstance(monitor.get("realtime_score"), dict) else {}
    yoy = monitor.get("yoy") if isinstance(monitor.get("yoy"), dict) else {}
    ttm = monitor.get("ttm") if isinstance(monitor.get("ttm"), dict) else {}
    dimensions = monitor.get("dimensions") if isinstance(monitor.get("dimensions"), list) else []
    profitability = next((item for item in dimensions if isinstance(item, dict) and item.get("code") == "profitability"), {})
    alerts = monitor.get("alerts") if isinstance(monitor.get("alerts"), list) else []
    evidence = {
        "annual_total": health.get("score"),
        "annual_assessment_track": health.get("assessment_track"),
        "annual_coverage_weight": health.get("coverage_weight"),
        "quarterly_total": realtime.get("score"),
        "quarterly_coverage_weight": realtime.get("coverage_weight"),
        "quarterly_revenue_yoy": yoy.get("revenue"),
        "quarterly_ex_net_profit_yoy": yoy.get("ex_net_profit"),
        "quarterly_ttm_fcf_margin": ttm.get("fcf_margin"),
        "quarterly_profitability_status": profitability.get("status"),
        "quarterly_high_or_critical_alert": any(isinstance(item, dict) and item.get("severity") in {"high", "critical"} for item in alerts),
    }
    return {
        "matched": matches_financial_reversal(evidence),
        "rule_version": "financial-reversal-v1",
        "annual_score": evidence["annual_total"],
        "quarterly_score": evidence["quarterly_total"],
        "quarterly_period": monitor.get("latest_period"),
    }


def _normalize_announce_date(value: object) -> str | None:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(re.findall(r"\d", text))
    if len(digits) == 6:
        year = int(digits[:2])
        digits = f"{2000 + year if year < 50 else 1900 + year:04d}{digits[2:]}"
    if len(digits) != 8:
        return None
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return None
    return digits


def build_report_release_price_performance(
    *, announce_date: object, daily_bars: list[dict[str, object]], current_price: object, current_price_as_of: object,
) -> dict[str, object]:
    """Return raw-price performance from the first trading day strictly after publication."""
    normalized_announce = _normalize_announce_date(announce_date)
    result: dict[str, object] = {
        "available": False,
        "basis": "raw_unadjusted",
        "announce_date": normalized_announce,
        "entry_trading_day": None,
        "entry_open": None,
        "current_price": None,
        "current_price_as_of": str(current_price_as_of or "").strip() or None,
        "return_pct": None,
        "reason": None,
    }
    if normalized_announce is None:
        result["reason"] = "announce_date_unavailable"
        return result
    try:
        normalized_bars = sorted(
            (
                ("".join(re.findall(r"\d", str(item.get("trading_day") or "")))[:8], float(item.get("open")))
                for item in daily_bars
                if isinstance(item, dict) and item.get("open") is not None
            ),
            key=lambda item: item[0],
        )
    except (TypeError, ValueError):
        normalized_bars = []
    entry = next((item for item in normalized_bars if len(item[0]) == 8 and item[0] > normalized_announce and item[1] > 0), None)
    if entry is None:
        result["reason"] = "t_plus_one_open_unavailable"
        return result
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        result["reason"] = "current_price_unavailable"
        return result
    entry_day, entry_open = entry
    result.update({
        "available": True,
        "entry_trading_day": f"{entry_day[:4]}-{entry_day[4:6]}-{entry_day[6:]}",
        "entry_open": round(entry_open, 4),
        "current_price": round(price, 4),
        "return_pct": round((price / entry_open - 1) * 100, 2),
    })
    return result


def build_report_release_price_trend(
    *, performance: dict[str, object], daily_bars: list[dict[str, object]],
) -> dict[str, object]:
    """Build an audit-friendly raw-price line series starting at the report T+1 open."""
    result: dict[str, object] = {"available": False, "basis": "raw_unadjusted", "points": [], "markers": {}, "reason": None}
    entry_day = "".join(re.findall(r"\d", str(performance.get("entry_trading_day") or "")))[:8]
    if performance.get("available") is not True or len(entry_day) != 8:
        result["reason"] = "performance_unavailable"
        return result
    points: list[dict[str, object]] = []
    high_candidates: list[tuple[str, float]] = []
    low_candidates: list[tuple[str, float]] = []
    for item in daily_bars:
        if not isinstance(item, dict):
            continue
        day = "".join(re.findall(r"\d", str(item.get("trading_day") or "")))[:8]
        if len(day) != 8 or day < entry_day:
            continue
        try:
            close = float(item.get("close"))
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        point = {"trading_day": f"{day[:4]}-{day[4:6]}-{day[6:]}", "close": round(close, 4)}
        points.append(point)
        for field, candidates in (("high", high_candidates), ("low", low_candidates)):
            try:
                value = float(item.get(field))
            except (TypeError, ValueError):
                continue
            if value > 0:
                candidates.append((point["trading_day"], value))
    if not points or not high_candidates or not low_candidates:
        result["reason"] = "raw_daily_series_unavailable"
        return result
    high_day, high_price = max(high_candidates, key=lambda item: item[1])
    low_day, low_price = min(low_candidates, key=lambda item: item[1])
    entry_day_iso = f"{entry_day[:4]}-{entry_day[4:6]}-{entry_day[6:]}"
    try:
        entry_open = float(performance.get("entry_open"))
        current_price = float(performance.get("current_price"))
    except (TypeError, ValueError):
        result["reason"] = "price_marker_unavailable"
        return result
    if entry_open <= 0 or current_price <= 0:
        result["reason"] = "price_marker_unavailable"
        return result
    current_day = str(performance.get("current_price_as_of") or points[-1]["trading_day"])
    result.update({
        "available": True,
        "points": points,
        "markers": {
            "entry_open": {"trading_day": entry_day_iso, "price": round(entry_open, 4)},
            "high": {"trading_day": high_day, "price": round(high_price, 4)},
            "low": {"trading_day": low_day, "price": round(low_price, 4)},
            "current": {"trading_day": current_day, "price": round(current_price, 4)},
        },
    })
    return result


def _load_raw_daily_bars(search_index, symbol: str) -> list[dict[str, object]]:
    """Read unadjusted local TDX daily bars; never substitute front-adjusted prices."""
    try:
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir=search_index._TDX_DIR)
        daily = reader.daily(symbol=symbol)
    except Exception:
        return []
    if daily is None or daily.empty:
        return []
    bars: list[dict[str, object]] = []
    for index, row in daily.sort_index().iterrows():
        try:
            bars.append({
                "trading_day": index.strftime("%Y-%m-%d"),
                "open": float(row.get("open")),
                "high": float(row.get("high")),
                "low": float(row.get("low")),
                "close": float(row.get("close")),
            })
        except (AttributeError, TypeError, ValueError):
            continue
    return bars


def build_latest_report_release_price_performance(search_index, market: str, symbol: str, latest_report: dict[str, object] | None) -> dict[str, object]:
    latest_report = latest_report or {}
    basic_info = search_index._load_stock_basic_info(market, symbol) or {}
    daily_snapshot = search_index._load_latest_daily_snapshot(market, symbol) or {}
    daily_bars = _load_raw_daily_bars(search_index, symbol)
    performance = build_report_release_price_performance(
        announce_date=latest_report.get("announce_date"),
        daily_bars=daily_bars,
        current_price=basic_info.get("current_price"),
        current_price_as_of=daily_snapshot.get("trading_day"),
    )
    return {
        "performance": performance,
        "trend": build_report_release_price_trend(performance=performance, daily_bars=daily_bars),
    }


def load_recent_three_year_financial_reports(market: str, symbol: str, years: int = 6) -> dict[str, object]:
    """Load annual/quarterly reports covering the most recent ``years`` fiscal years."""
    search_index = importlib.import_module("app.search.index")

    try:
        years = int(years)
    except (TypeError, ValueError) as exc:
        raise ValueError("years must be an integer") from exc
    if not 1 <= years <= 6:
        raise ValueError("years must be between 1 and 6")

    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"}:
        raise ValueError("market must be sh, sz or bj")
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    def row_matches(row_symbol: str) -> bool:
        row_symbol = str(row_symbol).strip()
        if row_symbol != symbol:
            return False
        if market == "sh":
            return row_symbol.startswith(("5", "6", "9"))
        if market == "sz":
            return row_symbol.startswith(("0", "1", "2", "3", "4", "8"))
        return row_symbol.startswith(("4", "8", "9"))

    # User requests must never parse full-market raw CW archives.  The update
    # pipeline normalizes those archives into period Parquet files; retain only
    # the selected stock's rows here and leave all scoring formulas unchanged.
    from app.financial.warehouse_reports import load_symbol_financial_rows

    matched_reports: list[dict[str, object]] = []
    stock_name = search_index._stock_name_lookup().get((market, symbol), "")
    for warehouse_row in load_symbol_financial_rows(symbol, years=years):
        matched_row = warehouse_row["row"]
        period_label = str(warehouse_row["period"])
        if not row_matches(str(getattr(matched_row, "name", symbol))):
            continue
        announce_raw = None
        if hasattr(matched_row, "get"):
            for announce_field in ("announce_date", "财报公告日期"):
                candidate = search_index._pick(matched_row.get(announce_field))
                if candidate is not None:
                    announce_raw = candidate
                    break
        announce_date = _normalize_announce_date(announce_raw) or ""
        report_date = str(matched_row.get("report_date") or "")
        if not report_date:
            suffix_date = {"Q1": "0331", "Q2": "0630", "Q3": "0930", "A": "1231"}.get(period_label[4:], "")
            report_date = f"{period_label[:4]}{suffix_date}"
        matched_reports.append({
            "report_date": report_date,
            "announce_date": announce_date,
            "year": period_label[:4],
            "period": period_label,
            "row": matched_row,
        })

    if not matched_reports:
        raise ValueError(f"no recent financial reports found for {market}:{symbol}")

    matched_reports.sort(key=lambda row: str(row.get("report_date") or ""), reverse=True)
    latest_report_seed = matched_reports[0]
    latest_period_label = str(latest_report_seed.get("period") or "")
    latest_year = int(str(latest_report_seed.get("year") or "0")[:4] or "0")
    earliest_year = latest_year - years + 1 if latest_year else 0
    filtered_rows = [
        row for row in matched_reports
        if int(str(row.get("year") or "0")[:4] or "0") >= earliest_year
    ]
    reports = [_materialize_financial_report(search_index, row) for row in filtered_rows]
    reports.sort(key=lambda row: str(row.get("report_date") or ""))
    latest_report = reports[-1] if reports else None
    industry_row = next(
        (row for row in search_index.load_industry_rows() if str(row.get("market") or "").lower() == market and str(row.get("symbol") or "").zfill(6) == symbol),
        {},
    )
    industry = {
        "level_1": str(industry_row.get("industry_level_1_name") or "").strip() or None,
        "level_2": str(industry_row.get("industry_level_2_name") or "").strip() or None,
    }
    health = build_financial_health(
        reports,
        industry_level_1=industry["level_1"],
        industry_level_2=industry["level_2"],
    )

    quarterly_monitor = build_quarterly_financial_monitor(
        reports,
        industry_level_1=industry["level_1"],
    )
    composite_financial_health = build_composite_financial_health(health, quarterly_monitor)
    financial_reversal = build_financial_reversal_indicator(health, quarterly_monitor)
    report_release_price = build_latest_report_release_price_performance(search_index, market, symbol, latest_report)
    report_release_price_performance = report_release_price["performance"]
    report_release_price_trend = report_release_price["trend"]
    industry_position = build_industry_financial_position(market, symbol, search_index._load_financial_snapshot() or {})

    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "latest_report": latest_report,
        "latest_period_label": latest_period_label,
        "reports": reports,
        "industry": industry,
        "health": health,
        "quarterly_monitor": quarterly_monitor,
        "composite_financial_health": composite_financial_health,
        "financial_reversal": financial_reversal,
        "report_release_price_performance": report_release_price_performance,
        "report_release_price_trend": report_release_price_trend,
        "industry_financial_position": industry_position,
    }



def _report_date_to_period_label(report_date: str) -> str:
    text = str(report_date or "").strip()
    if len(text) != 8 or not text.isdigit():
        return text
    year = text[:4]
    month_day = text[4:]
    mapping = {
        "0331": "Q1",
        "0630": "Q2",
        "0930": "Q3",
        "1231": "A",
    }
    suffix = mapping.get(month_day)
    if not suffix:
        return text
    return f"{year}{suffix}"



def _extract_period_quarter(period_label: str) -> str:
    text = str(period_label or "").strip().upper()
    match = re.match(r"^\d{4}(Q[1-4]|A)$", text)
    return match.group(1) if match else ""


def _materialize_financial_report(search_index, seed: dict[str, object]) -> dict[str, object]:
    matched_row = seed.get("row")
    derived = search_index._derive_sub_fields(matched_row, None)
    # TDX exposes ``营业收入`` as a period-only value in some reports (notably Q4),
    # while ``其中：营业收入`` is the cumulative statutory line comparable across years.
    getter = getattr(matched_row, "get", lambda _key: None)
    revenue = search_index._pick(getter("其中：营业收入"))
    if revenue is None:
        revenue = search_index._pick(getter("营业收入"))
    capex = search_index._pick(getter("购建固定资产、无形资产和其他长期资产支付的现金"))
    ocf = search_index._pick(getter("经营活动产生的现金流量净额"))
    metrics = {
        "revenue": revenue,
        "profit": search_index._pick(getter("净利润")),
        "net_profit": search_index._pick(getter("归属于母公司所有者的净利润")),
        "ex_net_profit": search_index._pick(getter("扣除非经常性损益后的净利润")),
        "gross_margin": search_index._pick(getter("销售毛利率(%)(非金融类指标)")),
        "net_margin": search_index._pick(getter("销售净利率(%)")),
        "roe_ex": derived.get("roe_ex"),
        "debt_ratio": search_index._pick(getter("资产负债率(%)")),
        "ocf": ocf,
        # Free cash flow uses the same report-period cumulative cash flows:
        # operating cash flow minus capital expenditure.
        "free_cf": ocf - capex if ocf is not None and capex is not None else None,
        "capex": capex,
        "goodwill": search_index._pick(getter("商誉")),
        "equity": search_index._pick(getter("归属于母公司股东权益(资产负债表)")),
        "total_assets": search_index._pick(getter("资产总计")),
        "accounts_receivable": search_index._pick(getter("应收账款")),
        "inventory": search_index._pick(getter("存货")),
    }
    return {
        "report_date": seed.get("report_date"),
        "announce_date": seed.get("announce_date"),
        "year": seed.get("year"),
        "period": seed.get("period"),
        "metrics": metrics,
    }


@lru_cache(maxsize=128)
def build_industry_financial_health_peers(market: str, symbol: str) -> dict[str, object]:
    """Return an industry view by filtering the published per-stock health snapshot.

    This route is intentionally read-only: all full-universe financial scoring runs
    during data maintenance, never while a user waits on the dialog.
    """
    market, symbol = str(market or "").strip().lower(), str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"} or not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("market must be sh, sz or bj and symbol must be a 6-digit code")
    from app.financial.health_peer_snapshot import build_industry_health_peer_response
    return build_industry_health_peer_response(market, symbol)

