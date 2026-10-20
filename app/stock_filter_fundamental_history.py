"""Point-in-time financial records for historical stock-filter dates.

All records are selected by announcement date, never merely by report period.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    text = str(value or '').strip()
    if text.endswith('.0'):
        text = text[:-2]
    text = ''.join(char for char in text if char.isdigit())
    if len(text) == 6:
        text = f"20{text}"
    if len(text) != 8:
        return None
    try:
        return datetime.strptime(text, '%Y%m%d').strftime('%Y-%m-%d')
    except ValueError:
        return None


def _period_key(period: str) -> tuple[int, int]:
    suffix = period[4:]
    return int(period[:4]), {'Q1': 1, 'Q2': 2, 'Q3': 3, 'A': 4}.get(suffix, 0)


def _available_row(frame: pd.DataFrame, symbol: str, as_of_date: str) -> pd.Series | None:
    if symbol not in frame.index:
        return None
    row = frame.loc[symbol]
    # Warehouses are normalised to one latest row per report period.  An announce
    # date after the signal date makes that report unavailable, rather than falling
    # back to a later/current record.
    announce = _date(row.get('announce_date') if hasattr(row, 'get') else None)
    return row if announce and announce <= as_of_date else None


def valuation_from_available_report(*, raw_close: float | None, report_row: pd.Series | None, ttm_eps: float | None = None) -> dict[str, Any]:
    """Compute PE/PS from a signal-day raw close and an available report row."""
    price = _number(raw_close)
    eps = _number(ttm_eps if ttm_eps is not None else (report_row.get('基本每股收益') if report_row is not None else None))
    revenue_wan = _number(report_row.get('营业总收入TTM(万元)') if report_row is not None else None)
    shares = _number(report_row.get('总股本') if report_row is not None else None)
    result: dict[str, Any] = {'pe_ttm': None, 'ps_ttm': None, 'pe_ttm_reason': None, 'ps_ttm_reason': None}
    if price is not None and price > 0 and eps is not None and eps > 0:
        result['pe_ttm'] = round(price / eps, 4)
    else:
        result['pe_ttm_reason'] = 'ttm_eps_non_positive' if eps is None or eps <= 0 else 'raw_close_unavailable'
    if price is not None and price > 0 and revenue_wan is not None and revenue_wan > 0 and shares is not None and shares > 0:
        result['ps_ttm'] = round((price * shares) / (revenue_wan * 10_000.0), 4)
    else:
        result['ps_ttm_reason'] = 'ttm_revenue_or_share_capital_unavailable' if revenue_wan is None or revenue_wan <= 0 or shares is None or shares <= 0 else 'raw_close_unavailable'
    return result


def _ttm_eps(period: str, rows: dict[str, pd.Series]) -> float | None:
    current = rows.get(period)
    if current is None:
        return None
    current_eps = _number(current.get('基本每股收益'))
    if period.endswith('A'):
        return current_eps
    year, suffix = int(period[:4]), period[4:]
    prior_annual, prior_same = rows.get(f'{year - 1}A'), rows.get(f'{year - 1}{suffix}')
    values = (current_eps, _number(prior_annual.get('基本每股收益')) if prior_annual is not None else None, _number(prior_same.get('基本每股收益')) if prior_same is not None else None)
    if any(value is None for value in values):
        return None
    return float(values[0] + values[1] - values[2])


def _materialize_reports(rows: dict[str, pd.Series]) -> list[dict[str, Any]]:
    from app.financial.reports import _materialize_financial_report
    from app.search import index as search_index

    class Materializer:
        _derive_sub_fields = staticmethod(search_index._derive_sub_fields)
        _pick = staticmethod(search_index._pick)

    reports = []
    for period, row in sorted(rows.items(), key=lambda item: _period_key(item[0])):
        suffix = period[4:]
        report_date = f"{period[:4]}{'1231' if suffix == 'A' else {'Q1': '0331', 'Q2': '0630', 'Q3': '0930'}[suffix]}"
        reports.append(_materialize_financial_report(Materializer, {'report_date': report_date, 'announce_date': row.get('announce_date'), 'year': period[:4], 'period': period, 'row': row}))
    return reports


def build_historical_fundamental_snapshot(*, as_of_date: str, period_frames: dict[str, pd.DataFrame], raw_close_by_symbol: dict[str, float], market_by_symbol: dict[str, str], industry_by_key: dict[tuple[str, str], tuple[str | None, str | None]], market_metrics_by_key: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a per-stock historical fundamental snapshot for one trading day."""
    available: dict[str, dict[str, pd.Series]] = {}
    for period, frame in period_frames.items():
        normalized = frame.copy()
        normalized.index = normalized.index.map(lambda value: str(value).zfill(6))
        for symbol in normalized.index:
            row = _available_row(normalized, symbol, as_of_date)
            if row is not None:
                available.setdefault(symbol, {})[period] = row
    stocks: dict[str, dict[str, Any]] = {}
    market_metrics_by_key = market_metrics_by_key or {}
    for symbol, rows in available.items():
        market = market_by_symbol.get(symbol)
        if not market:
            continue
        ordered = sorted(rows, key=_period_key)
        annual_periods = [period for period in ordered if period.endswith('A')]
        latest_period = ordered[-1]
        latest_row = rows[latest_period]
        annual_anchor = annual_periods[-1] if annual_periods else None
        key = f'{market}:{symbol}'
        market_metrics = market_metrics_by_key.get(key) or {}
        annual = {'score': None, 'dimensions': {}, 'anchor_period': annual_anchor, 'reason': 'annual_score_unavailable'}
        quarterly = {'score': None, 'dimensions': {}, 'anchor_period': latest_period, 'quality': {}, 'reason': 'quarterly_score_unavailable'}
        if len(annual_periods) >= 5:
            try:
                from app.stock_filter_snapshot import build_strict_financial_record
                l1, _l2 = industry_by_key.get((market, symbol), (None, None))
                strict = build_strict_financial_record(_materialize_reports(rows), industry_level_1=l1, annual_anchor=annual_anchor or '', quarterly_anchor=latest_period)
                annual, quarterly = strict['annual'], strict['quarterly']
            except (KeyError, TypeError, ValueError):
                pass
        ttm_eps = _ttm_eps(latest_period, rows)
        valuation = valuation_from_available_report(raw_close=raw_close_by_symbol.get(symbol), report_row=latest_row, ttm_eps=ttm_eps)
        announce = _date(latest_row.get('announce_date'))
        stocks[key] = {
            'annual_total': annual.get('score'), 'annual_dimensions': annual.get('dimensions') or {}, 'annual_period': annual.get('anchor_period'), 'annual_reason': annual.get('reason'),
            'annual_assessment_track': annual.get('assessment_track'), 'annual_coverage_weight': annual.get('coverage_weight'),
            'quarterly_total': quarterly.get('score'), 'quarterly_dimensions': quarterly.get('dimensions') or {}, 'quarterly_period': quarterly.get('anchor_period'), 'quarterly_quality': quarterly.get('quality') or {}, 'quarterly_reason': quarterly.get('reason'),
            'quarterly_coverage_weight': quarterly.get('coverage_weight'),
            'quarterly_revenue_yoy': (quarterly.get('quality') or {}).get('revenue_yoy'),
            'quarterly_ex_net_profit_yoy': (quarterly.get('quality') or {}).get('ex_net_profit_yoy'),
            'quarterly_ttm_fcf_margin': (quarterly.get('quality') or {}).get('ttm_fcf_margin'),
            'quarterly_profitability_status': (quarterly.get('quality') or {}).get('profitability_status'),
            'quarterly_high_or_critical_alert': (quarterly.get('quality') or {}).get('has_high_or_critical_alert'),
            'latest_period': latest_period, 'latest_announce_date': announce, 'ttm_eps': round(ttm_eps, 6) if ttm_eps is not None else None,
            'price': _number(raw_close_by_symbol.get(symbol)), 'price_raw_close': _number(raw_close_by_symbol.get(symbol)),
            'trend_daily': market_metrics.get('trend_daily'), 'trend_daily_label': market_metrics.get('trend_daily_label'),
            'short_trend': market_metrics.get('short_trend'), 'short_trend_label': market_metrics.get('short_trend_label'),
            'blowup_break_volume_price_ok': bool(market_metrics.get('blowup_break_volume_price_ok')),
            'blowup_break_va': market_metrics.get('blowup_break_va'), 'blowup_break_vol_ratios': market_metrics.get('blowup_break_vol_ratios') or [],
            'blowup_break_return_5d': market_metrics.get('blowup_break_return_5d'), 'qfq_as_of': market_metrics.get('qfq_as_of'),
            **valuation,
        }
    return {'schema_version': 'stock-filter-fundamental-history-v2', 'as_of_date': as_of_date,
            'financial_information_cutoff': as_of_date,
            'revision_policy': 'conservative_current_warehouse_version',
            'valuation_price_basis': 'raw_unadjusted_close', 'stocks': stocks}
