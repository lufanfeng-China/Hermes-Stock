from __future__ import annotations

from datetime import date

from app.search import index as search_index

from .config import resolve_valuation_template_id


def _to_100m(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 1e8


def _pick_dict_value(mapping: object, *keys: str) -> float | None:
    if not hasattr(mapping, 'get'):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _quarter_period_from_report_date(report_date: str | None) -> str:
    text = str(report_date or '').strip()
    if len(text) != 8 or not text.isdigit():
        return ''
    month_day = text[4:]
    if month_day == '0331':
        return f'{text[:4]}Q1'
    if month_day == '0630':
        return f'{text[:4]}Q2'
    if month_day == '0930':
        return f'{text[:4]}Q3'
    if month_day == '1231':
        return f'{text[:4]}A'
    return ''


def _extract_100m_from_row(row: object, keys: tuple[str, ...]) -> float | None:
    if not hasattr(row, 'get'):
        return None
    for key in keys:
        value = _to_100m(search_index._pick(row.get(key)))
        if value is not None:
            return value
    return None


def _trailing_quarter_periods(period: str | None) -> list[str]:
    text = str(period or '').strip()
    if not text:
        return []
    if not (len(text) >= 6 and text[:4].isdigit() and text[4] == 'Q' and text[5] in {'1', '2', '3'}) and not text.endswith('A'):
        quarter = _quarter_period_from_report_date(text)
        if not quarter:
            return []
        text = quarter
    year = int(text[:4])
    quarter_num = 4 if text.endswith('A') else int(text[5])
    periods: list[str] = []
    for _ in range(4):
        periods.append(f'{year}A' if quarter_num == 4 else f'{year}Q{quarter_num}')
        quarter_num -= 1
        if quarter_num == 0:
            year -= 1
            quarter_num = 4
    return periods


def _ttm_metric_100m(period: str | None, symbol: str, current_row: object, keys: tuple[str, ...]) -> float | None:
    current_value = _extract_100m_from_row(current_row, keys)
    if current_value is None:
        return None
    periods = _trailing_quarter_periods(period)
    if not periods:
        return current_value
    values: list[float] = []
    for idx, quarter_period in enumerate(periods):
        row = current_row if idx == 0 else search_index._load_financial_quarter_row(quarter_period, symbol)
        value = _extract_100m_from_row(row, keys)
        if value is not None:
            values.append(value)
    if len(values) == 4:
        return sum(values)
    quarter_text = periods[0]
    quarter_num = 4 if quarter_text.endswith('A') else int(quarter_text[5])
    if len(values) >= 2:
        return sum(values)
    if quarter_num > 0:
        return current_value * (4.0 / quarter_num)
    return current_value


def load_valuation_inputs(market: str, symbol: str) -> dict[str, object]:
    market = str(market or '').strip().lower()
    symbol = str(symbol or '').strip()
    if market not in {'sh', 'sz', 'bj'}:
        raise ValueError('market must be sh, sz or bj')
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError('symbol must be a 6-digit code')

    industry_rows = search_index.load_industry_rows()
    industry_match = next((row for row in industry_rows if str(row.get('market', '')).strip() == market and str(row.get('symbol', '')).strip() == symbol), {})
    level1 = str(industry_match.get('industry_level_1_name', '') or '').strip()
    level2 = str(industry_match.get('industry_level_2_name', '') or '').strip()
    template_id = resolve_valuation_template_id(industry_match.get('valuation_template_id'), level1, level2)

    profile_response = search_index.stock_profile_response(symbol)
    profile = profile_response.get('profile', {}) if isinstance(profile_response, dict) else {}
    basic_info = profile.get('basic_info', {}) if isinstance(profile, dict) else {}

    financial_match = search_index._lookup_financial_row(market, symbol)
    latest_report_date = financial_match[0] if financial_match else None
    financial_row = financial_match[1] if financial_match else {}

    snapshot = search_index._load_financial_snapshot()
    snapshot_entry = {}
    if isinstance(snapshot, dict):
        snapshot_entry = snapshot.get('scores', {}).get(f'{market}:{symbol}', {})

    current_price = _pick_dict_value(basic_info, 'current_price')
    dynamic_pe = _pick_dict_value(basic_info, 'dynamic_pe')
    market_cap = _pick_dict_value(basic_info, 'a_share_market_cap')
    total_shares = _pick_dict_value(basic_info, 'total_shares')
    float_shares = _pick_dict_value(basic_info, 'float_shares')
    eps = _pick_dict_value(basic_info, 'eps')

    if total_shares is None and hasattr(financial_row, 'get'):
        total_shares = _to_100m(search_index._pick(financial_row.get('总股本')))
    if current_price not in (None, 0) and dynamic_pe not in (None, 0):
        eps = current_price / dynamic_pe

    quarter_period = str(snapshot_entry.get('latest_period') or '') if isinstance(snapshot_entry, dict) else ''
    if not quarter_period:
        quarter_period = _quarter_period_from_report_date(latest_report_date)

    revenue = None
    net_assets = None
    net_profit = None
    ex_net_profit = None
    ocf = None
    if hasattr(financial_row, 'get'):
        revenue = _ttm_metric_100m(quarter_period, symbol, financial_row, ('营业总收入', '营业收入', '其中：营业收入'))
        net_assets = _extract_100m_from_row(
            financial_row,
            (
                '归属于母公司股东权益合计',
                '归属于母公司所有者权益合计',
                '所有者权益（或股东权益）合计',
                '归属于母公司股东权益(资产负债表)',
            ),
        )
        net_profit = _extract_100m_from_row(financial_row, ('归属于母公司股东的净利润', '归属于母公司所有者的净利润'))
        ex_net_profit = _extract_100m_from_row(financial_row, ('扣除非经常性损益后的净利润',))
        ocf = _extract_100m_from_row(financial_row, ('经营活动产生的现金流量净额',))

    raw_sub = snapshot_entry.get('raw_sub_indicators', {}) if isinstance(snapshot_entry, dict) else {}
    valuation_date = str(date.today())
    short_history = bool((snapshot_entry or {}).get('short_history', False))

    return {
        'market': market,
        'symbol': symbol,
        'stock_name': str(profile.get('stock_name') or industry_match.get('stock_name') or symbol),
        'industry_level_1_name': level1,
        'industry_level_2_name': level2,
        'valuation_template_id': template_id,
        'valuation_date': valuation_date,
        'latest_report_date': latest_report_date,
        'current_price': current_price,
        'market_cap': market_cap,
        'dynamic_pe': dynamic_pe,
        'eps': eps,
        'total_shares': total_shares,
        'float_shares': float_shares,
        'revenue': revenue,
        'net_assets': net_assets,
        'net_profit': net_profit,
        'ex_net_profit': ex_net_profit,
        'ocf': ocf,
        'profit_growth': raw_sub.get('profit_growth'),
        'revenue_growth': raw_sub.get('revenue_growth'),
        'ocf_to_profit': raw_sub.get('ocf_to_profit'),
        'free_cf': raw_sub.get('free_cf'),
        'debt_ratio': raw_sub.get('debt_ratio'),
        'short_history': short_history,
        'structural_break_date': None,
        'rate_regime': 'neutral',
    }
