from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path

from .classifier import classify_relative_valuation_stock
from .industry_snapshot import build_industry_day_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDUSTRY_VALUATION_CURRENT_PATH = PROJECT_ROOT / "data" / "derived" / "datasets" / "final" / "dataset_industry_valuation_current.json"


def compute_ttm_metric_from_rows(
    *,
    period: str,
    field_name: str,
    current_row,
    previous_quarter_rows: list[object] | tuple[object, ...] | None = None,
    prev_annual_row=None,
    prev_same_row=None,
) -> float | None:
    current_value = _pick_from_row(current_row, field_name)
    text = str(period or "").strip()
    if not text:
        return None
    if isinstance(previous_quarter_rows, (list, tuple)):
        prior_values: list[float] = []
        for row in previous_quarter_rows:
            value = _pick_from_row(row, field_name)
            if value is None:
                continue
            prior_values.append(value)
            if len(prior_values) >= 3:
                break
        if text.endswith("A"):
            if current_value is not None and len(prior_values) >= 3:
                return current_value + sum(prior_values[:3])
            return current_value
        if current_value is not None and len(prior_values) >= 3:
            return current_value + sum(prior_values[:3])
    if text.endswith("A"):
        return current_value
    if not (len(text) >= 6 and text[:4].isdigit() and text[4] == "Q" and text[5] in {"1", "2", "3"}):
        return current_value
    prev_annual_value = _pick_from_row(prev_annual_row, field_name)
    prev_same_value = _pick_from_row(prev_same_row, field_name)
    if current_value is not None and prev_annual_value is not None and prev_same_value is not None:
        return current_value + prev_annual_value - prev_same_value
    return current_value


def pick_free_float_shares(financial_row) -> float | None:
    search_index = _search_index_module()
    value = search_index._pick(financial_row.get("自由流通股(股)")) if financial_row is not None else None
    if value is None:
        value = search_index._pick(financial_row.get("已上市流通A股")) if financial_row is not None else None
    return value


def pick_total_shares(financial_row) -> float | None:
    search_index = _search_index_module()
    value = search_index._pick(financial_row.get("总股本")) if financial_row is not None else None
    if value is None:
        value = search_index._pick(financial_row.get("实收资本（或股本）")) if financial_row is not None else None
    return value


def load_stock_relative_valuation_inputs(market: str, symbol: str) -> dict[str, object] | None:
    search_index = _search_index_module()
    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"} or len(symbol) != 6:
        return None

    industry_row = _industry_row_lookup().get((market, symbol))
    if industry_row is None:
        return None

    latest_period = search_index._snapshot_latest_period(market, symbol)
    if not latest_period:
        return None

    current_row = search_index._load_financial_quarter_row(latest_period, symbol)
    if current_row is None:
        return None

    year = int(str(latest_period)[:4]) if str(latest_period)[:4].isdigit() else None
    previous_quarter_rows = [
        search_index._load_financial_quarter_row(previous_period, symbol)
        for previous_period in _latest_three_previous_periods(latest_period)
    ]
    prev_annual_row = search_index._load_financial_quarter_row(f"{year - 1}A", symbol) if year else None
    prev_same_row = search_index._load_financial_quarter_row(f"{year - 1}{str(latest_period)[4:]}", symbol) if year and str(latest_period)[4:] else None

    basic_info = search_index._load_stock_basic_info(market, symbol)
    daily_snapshot = search_index._load_latest_daily_snapshot(market, symbol)
    current_price = _to_float((basic_info or {}).get("current_price"))
    if current_price is None:
        current_price = _to_float((daily_snapshot or {}).get("latest_close"))

    free_float_shares_raw = pick_free_float_shares(current_row)
    total_shares_raw = pick_total_shares(current_row)
    free_float_market_cap = None
    total_market_cap = None
    if current_price is not None and free_float_shares_raw is not None:
        free_float_market_cap = compute_market_cap_yi(current_price, free_float_shares_raw)
    elif current_price is not None and _to_float((basic_info or {}).get("float_shares")) is not None:
        free_float_market_cap = current_price * _to_float((basic_info or {}).get("float_shares"))
    if current_price is not None and total_shares_raw is not None:
        total_market_cap = compute_market_cap_yi(current_price, total_shares_raw)
    elif current_price is not None and _to_float((basic_info or {}).get("total_shares")) is not None:
        total_market_cap = current_price * _to_float((basic_info or {}).get("total_shares"))

    ttm_net_profit = normalize_amount_to_yi(compute_ttm_metric_from_rows(
        period=latest_period,
        field_name="归属于母公司所有者的净利润",
        current_row=current_row,
        previous_quarter_rows=previous_quarter_rows,
        prev_annual_row=prev_annual_row,
        prev_same_row=prev_same_row,
    ))
    ttm_revenue = normalize_amount_to_yi(compute_ttm_metric_from_rows(
        period=latest_period,
        field_name="营业收入",
        current_row=current_row,
        previous_quarter_rows=previous_quarter_rows,
        prev_annual_row=prev_annual_row,
        prev_same_row=prev_same_row,
    ))

    revenue_yoy = _normalize_percent(search_index._pick(current_row.get("营业收入增长率(%)")))
    gross_margin = _extract_gross_margin(search_index, current_row)
    book_value_per_share = first_non_null(
        search_index._pick(current_row.get("每股净资产")),
        search_index._pick(current_row.get("每股净资产(调整后)")),
    )
    listed_days = _load_listed_days(market, symbol)
    pe_ttm = None
    if total_market_cap is not None and ttm_net_profit not in (None, 0):
        pe_ttm = total_market_cap / ttm_net_profit
    else:
        pe_ttm = _to_float((basic_info or {}).get("dynamic_pe"))
    ps_ttm = compute_ps_ttm(total_market_cap, ttm_revenue)

    stock_name = str(industry_row.get("stock_name") or _stock_name_lookup().get((market, symbol)) or "").strip()
    return {
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "industry_level_1_name": str(industry_row.get("industry_level_1_name") or "").strip(),
        "industry_level_2_name": str(industry_row.get("industry_level_2_name") or "").strip(),
        "listed_days": listed_days,
        "current_price": current_price,
        "total_market_cap": total_market_cap,
        "free_float_market_cap": free_float_market_cap,
        "ttm_net_profit": ttm_net_profit,
        "ttm_revenue": ttm_revenue,
        "revenue_yoy": revenue_yoy,
        "gross_margin": gross_margin,
        "book_value_per_share": book_value_per_share,
        "pe_ttm": pe_ttm,
        "ps_ttm": ps_ttm,
        "is_suspended": False,
    }


def load_industry_valuation_snapshot(industry_level_2_name: str) -> dict[str, object] | None:
    lookup = _industry_valuation_current_lookup()
    cached = lookup.get(industry_level_2_name)
    if (
        cached
        and cached.get("temperature_history_since_2022")
        and isinstance(cached.get("percentile_samples"), dict)
    ):
        return dict(cached)
    rebuilt = _rebuild_industry_snapshot(
        industry_level_2_name,
        tuple(_freeze_temperature_history(cached.get("temperature_history_since_2022")) if isinstance(cached, dict) else []),
    )
    if rebuilt:
        return dict(rebuilt)
    if cached:
        return dict(cached)
    return None


def load_industry_percentile_sample(
    industry_level_2_name: str,
    metric: str,
    classification: str,
    sub_classification: str | None = None,
) -> list[float]:
    sample_key = _percentile_sample_key(metric, classification, sub_classification)

    snapshot = {}
    try:
        snapshot = load_industry_valuation_snapshot(industry_level_2_name) or {}
    except Exception:
        snapshot = {}
    cached_sample = _extract_snapshot_percentile_sample(snapshot, sample_key)
    if cached_sample is not None:
        return cached_sample

    cached = _industry_valuation_current_lookup().get(industry_level_2_name) or {}
    cached_sample = _extract_snapshot_percentile_sample(cached, sample_key)
    if cached_sample is not None:
        return cached_sample

    threshold = _to_float(snapshot.get("pe_invalid_threshold"))
    members = _industry_members(industry_level_2_name)
    samples: list[float] = []
    for member in members:
        stock = load_stock_relative_valuation_inputs(member["market"], member["symbol"])
        if not stock:
            continue
        classified = classify_relative_valuation_stock(
            ttm_net_profit=_to_float(stock.get("ttm_net_profit")),
            pe_ttm=_to_float(stock.get("pe_ttm")),
            dynamic_pe_invalid_threshold=threshold,
            ttm_revenue=_to_float(stock.get("ttm_revenue")),
            revenue_yoy=_to_float(stock.get("revenue_yoy")),
            gross_margin=_to_float(stock.get("gross_margin")),
            book_value_per_share=_to_float(stock.get("book_value_per_share")),
            listed_days=_to_int(stock.get("listed_days")),
        )
        if classified.is_new_listing:
            continue
        value = _to_float(stock.get(metric))
        if value is None or value <= 0:
            continue
        if classification == "A_NORMAL_EARNING":
            if classified.classification.value != classification:
                continue
        elif classification == "B_THIN_PROFIT_DISTORTED":
            if classified.classification.value not in {"A_NORMAL_EARNING", "B_THIN_PROFIT_DISTORTED"}:
                continue
        elif classification == "C_LOSS":
            if classified.classification.value != "C_LOSS":
                continue
            if sub_classification and (classified.sub_classification is None or classified.sub_classification.value != sub_classification):
                continue
            if classified.sub_classification and classified.sub_classification.value in {"C3_NO_REVENUE_CONCEPT", "C4_LIQUIDATION_RISK"}:
                continue
        samples.append(value)
    return samples


def build_industry_snapshot_for_industry(
    industry_level_2_name: str,
    temperature_history: list[dict[str, object]] | None = None,
) -> dict[str, object] | None:
    from app.relative_valuation.history import load_industry_temperature_history

    members = _industry_members(industry_level_2_name)
    if not members:
        return None
    stock_inputs = []
    for member in members:
        payload = load_stock_relative_valuation_inputs(member["market"], member["symbol"])
        if payload:
            stock_inputs.append(payload)
    if not stock_inputs:
        return None
    first = stock_inputs[0]
    if not isinstance(temperature_history, list):
        temperature_history = load_industry_temperature_history(industry_level_2_name)
    snapshot = build_industry_day_snapshot(
        trading_day=_latest_trading_day_for_industry(stock_inputs) or "",
        industry_level_1_name=str(first.get("industry_level_1_name") or ""),
        industry_level_2_code=str(first.get("industry_level_2_name") or industry_level_2_name),
        industry_level_2_name=industry_level_2_name,
        members=stock_inputs,
        historical_weighted_pe_series=[row["weighted_pe_ttm"] for row in temperature_history],
    )
    snapshot["temperature_history_since_2022"] = temperature_history
    snapshot["percentile_samples"] = _build_percentile_samples(stock_inputs, _to_float(snapshot.get("pe_invalid_threshold")))
    member_rows = []
    for stock in stock_inputs:
        row = {
            "market": str(stock.get("market") or "").strip().lower(),
            "symbol": str(stock.get("symbol") or "").strip(),
            "stock_name": stock.get("stock_name") or None,
            "current_price": _to_float(stock.get("current_price")),
            "pe_ttm": _to_float(stock.get("pe_ttm")),
            "ps_ttm": _to_float(stock.get("ps_ttm")),
        }
        total_market_cap = _to_float(stock.get("total_market_cap"))
        if total_market_cap is not None:
            row["total_market_cap"] = total_market_cap
        free_float_market_cap = _to_float(stock.get("free_float_market_cap"))
        if free_float_market_cap is not None:
            row["free_float_market_cap"] = free_float_market_cap
        member_rows.append(row)
    snapshot["member_valuation_rows"] = member_rows
    return snapshot


@lru_cache(maxsize=1)
def _search_index_module():
    return importlib.import_module("app.search.index")


@lru_cache(maxsize=1)
def _industry_row_lookup() -> dict[tuple[str, str], dict[str, object]]:
    search_index = _search_index_module()
    rows = search_index.load_industry_rows()
    lookup: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        market = str(row.get("market") or "").strip().lower()
        market = {"0": "sz", "1": "sh", "2": "bj"}.get(market, market)
        symbol = str(row.get("symbol") or "").strip()
        if market and symbol:
            lookup[(market, symbol)] = row
    return lookup


@lru_cache(maxsize=1)
def _stock_name_lookup() -> dict[tuple[str, str], str]:
    return _search_index_module()._stock_name_lookup()


@lru_cache(maxsize=1)
def _industry_valuation_current_lookup() -> dict[str, dict[str, object]]:
    if not INDUSTRY_VALUATION_CURRENT_PATH.exists():
        return {}
    rows = json.loads(INDUSTRY_VALUATION_CURRENT_PATH.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, object]] = {}
    for row in rows:
        name = str(row.get("industry_level_2_name") or "").strip()
        if name:
            lookup[name] = row
    return lookup


def _industry_members(industry_level_2_name: str) -> list[dict[str, str]]:
    out = []
    for (market, symbol), row in _industry_row_lookup().items():
        if str(row.get("industry_level_2_name") or "").strip() == industry_level_2_name:
            out.append({"market": market, "symbol": symbol})
    return out


@lru_cache(maxsize=512)
def _load_listed_days(market: str, symbol: str) -> int | None:
    search_index = _search_index_module()
    try:
        from mootdx.reader import Reader
    except Exception:
        return None
    try:
        reader = Reader.factory(market="std", tdxdir=search_index._TDX_DIR)
        daily = reader.daily(symbol=symbol)
        if daily is None or daily.empty:
            return None
        return int(len(daily))
    except Exception:
        return None


@lru_cache(maxsize=256)
def _rebuild_industry_snapshot(
    industry_level_2_name: str,
    frozen_temperature_history: tuple[tuple[str, float], ...],
) -> dict[str, object] | None:
    return build_industry_snapshot_for_industry(
        industry_level_2_name,
        temperature_history=[
            {"trading_day": trading_day, "weighted_pe_ttm": weighted_pe_ttm}
            for trading_day, weighted_pe_ttm in frozen_temperature_history
        ],
    )


def _freeze_temperature_history(value: object) -> list[tuple[str, float]]:
    if not isinstance(value, list):
        return []
    frozen: list[tuple[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        trading_day = _normalize_trading_day(item.get("trading_day"))
        weighted_pe_ttm = _to_float(item.get("weighted_pe_ttm"))
        if trading_day and weighted_pe_ttm is not None:
            frozen.append((trading_day, weighted_pe_ttm))
    return frozen


def _extract_gross_margin(search_index, current_row) -> float | None:
    direct = _normalize_percent(search_index._pick(current_row.get("销售毛利率(%)")))
    if direct is not None:
        return direct
    revenue = search_index._pick(current_row.get("营业收入"))
    op_cost = search_index._pick(current_row.get("营业成本"))
    if revenue not in (None, 0) and op_cost is not None:
        return (revenue - op_cost) / revenue
    return None


def _pick_from_row(row, field_name: str) -> float | None:
    if row is None:
        return None
    return _search_index_module()._pick(row.get(field_name))


def _normalize_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1:
        return value / 100.0
    return value


def _latest_trading_day_for_industry(stock_inputs: list[dict[str, object]]) -> str | None:
    search_index = _search_index_module()
    latest = None
    fallback = None
    for stock in stock_inputs:
        daily = search_index._load_latest_daily_snapshot(str(stock.get("market") or ""), str(stock.get("symbol") or ""))
        trading_day = _normalize_trading_day(daily.get("trading_day")) if isinstance(daily, dict) else None
        if trading_day:
            latest = max(latest, trading_day) if latest else trading_day
            continue
        latest_close = daily.get("latest_close") if isinstance(daily, dict) else None
        if latest_close is None:
            continue
        fallback = fallback or "latest"
    return latest or fallback


def _build_percentile_samples(
    stock_inputs: list[dict[str, object]],
    dynamic_threshold: float | None,
) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {}
    for stock in stock_inputs:
        classified = classify_relative_valuation_stock(
            ttm_net_profit=_to_float(stock.get("ttm_net_profit")),
            pe_ttm=_to_float(stock.get("pe_ttm")),
            dynamic_pe_invalid_threshold=dynamic_threshold,
            ttm_revenue=_to_float(stock.get("ttm_revenue")),
            revenue_yoy=_to_float(stock.get("revenue_yoy")),
            gross_margin=_to_float(stock.get("gross_margin")),
            book_value_per_share=_to_float(stock.get("book_value_per_share")),
            listed_days=_to_int(stock.get("listed_days")),
        )
        if classified.is_new_listing:
            continue

        pe_ttm = _to_float(stock.get("pe_ttm"))
        if classified.classification.value == "A_NORMAL_EARNING" and pe_ttm is not None and pe_ttm > 0:
            samples.setdefault(_percentile_sample_key("pe_ttm", "A_NORMAL_EARNING"), []).append(pe_ttm)

        ps_ttm = _to_float(stock.get("ps_ttm"))
        if ps_ttm is None or ps_ttm <= 0:
            continue
        if classified.classification.value in {"A_NORMAL_EARNING", "B_THIN_PROFIT_DISTORTED"}:
            samples.setdefault(_percentile_sample_key("ps_ttm", "B_THIN_PROFIT_DISTORTED"), []).append(ps_ttm)
            continue
        if classified.sub_classification and classified.sub_classification.value not in {"C3_NO_REVENUE_CONCEPT", "C4_LIQUIDATION_RISK"}:
            samples.setdefault(
                _percentile_sample_key("ps_ttm", "C_LOSS", classified.sub_classification.value),
                [],
            ).append(ps_ttm)
    return samples


def _percentile_sample_key(metric: str, classification: str, sub_classification: str | None = None) -> str:
    parts = [str(metric or "").strip(), str(classification or "").strip()]
    if sub_classification:
        parts.append(str(sub_classification).strip())
    return "|".join(parts)


def _extract_snapshot_percentile_sample(snapshot: dict[str, object], sample_key: str) -> list[float] | None:
    raw_samples = snapshot.get("percentile_samples")
    if not isinstance(raw_samples, dict):
        return None
    raw_sample = raw_samples.get(sample_key)
    if not isinstance(raw_sample, list):
        return None
    values = [_to_float(item) for item in raw_sample]
    return [value for value in values if value is not None]


def _normalize_trading_day(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def normalize_amount_to_yi(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1e8


def compute_ps_ttm(free_float_market_cap: float | None, ttm_revenue: float | None) -> float | None:
    if free_float_market_cap is None or ttm_revenue in (None, 0):
        return None
    return free_float_market_cap / ttm_revenue


def compute_market_cap_yi(current_price: float | None, shares_raw: float | None) -> float | None:
    if current_price is None or shares_raw is None:
        return None
    return current_price * shares_raw / 1e8


def first_non_null(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _latest_three_previous_periods(period: str) -> tuple[str, ...]:
    text = str(period or "").strip()
    if len(text) < 5 or not text[:4].isdigit():
        return tuple()
    year = int(text[:4])
    suffix = text[4:]
    if suffix == "Q1":
        return (f"{year - 1}A", f"{year - 1}Q3", f"{year - 1}Q2")
    if suffix == "Q2":
        return (f"{year}Q1", f"{year - 1}A", f"{year - 1}Q3")
    if suffix == "Q3":
        return (f"{year}Q2", f"{year}Q1", f"{year - 1}A")
    if suffix == "A":
        return (f"{year}Q3", f"{year}Q2", f"{year}Q1")
    return tuple()
