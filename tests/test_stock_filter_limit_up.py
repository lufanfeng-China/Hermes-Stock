from pathlib import Path
import struct
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import (
    _limit_up_metrics_from_raw_bars,
    build_market_metrics,
    load_raw_limit_up_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-19'
RECORD = struct.Struct('<IIIIIfII')


def _dates(count: int) -> list[int]:
    return [20261001 + i for i in range(count)]


def _row(index: int, *, days_ago: int | None = 4, raw_as_of: str | None = DAY,
         status: str | None = 'ok') -> dict:
    return {
        'market': 'sz', 'symbol': f'{index:06d}', 'stock_name': f'S{index}',
        'rps_total': float(index), 'annual_dimensions': {}, 'quarterly_dimensions': {},
        'qfq_as_of': DAY, 'limit_up_raw_as_of': raw_as_of,
        'limit_up_status': status, 'limit_up_recent_days_ago': days_ago,
        'limit_up_recent_date': '2026-11-15' if days_ago is not None else None,
        'limit_up_recent_band_pct': 10 if days_ago is not None else None,
        'limit_up_price_basis': 'raw_unadjusted',
    }


def _filter(rows, params):
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._swing_snapshot', side_effect=ValueError('not needed')):
        return filter_response(params)


def test_exact_raw_limit_up_detection_uses_price_bands_rounding_and_listing_guard():
    dates = _dates(30)
    closes = [1000] * 30
    closes[21] = 1100                         # 10% close limit, 8 days ago
    closes[22] = 1005
    closes[23] = 1106                         # 1005 * 1.10 = 1105.5 -> half-up 1106
    closes[24:] = [1090, 1080, 1070, 1060, 1050, 1040]
    result = _limit_up_metrics_from_raw_bars(list(zip(dates, closes)), '2026-12-31')
    assert result['limit_up_status'] == 'ok'
    assert result['limit_up_recent_days_ago'] == 6
    assert result['limit_up_recent_date'] == '2026-10-24'
    assert result['limit_up_recent_band_pct'] == 10
    assert result['limit_up_price_basis'] == 'raw_unadjusted'
    assert result['limit_up_definition'] == 'close_equals_exact_board_specific_limit_price'

    not_limit = [1000] * 30
    not_limit[25] = 1099                     # 9.9% is not exact 10% limit
    assert _limit_up_metrics_from_raw_bars(list(zip(dates, not_limit)), '2026-12-31')['limit_up_recent_date'] is None

    listing_guard = [1000] * 30
    listing_guard[10] = 1100                 # first 20 bars are not trusted
    assert _limit_up_metrics_from_raw_bars(list(zip(dates, listing_guard)), '2026-12-31')['limit_up_recent_date'] is None


def test_raw_day_loader_reads_market_file_and_truncates_at_snapshot_date(tmp_path):
    path = tmp_path / 'vipdoc' / 'sz' / 'lday' / 'sz000001.day'
    path.parent.mkdir(parents=True)
    records = []
    for i, day in enumerate(_dates(30)):
        close = 1100 if i == 25 else 1000
        records.append(RECORD.pack(day, close, close, close, close, 0.0, 100, 0))
    path.write_bytes(b''.join(records))
    result = load_raw_limit_up_metrics(tmp_path, {'sz:000001': str(_dates(30)[-1])})['sz:000001']
    assert result['limit_up_status'] == 'ok', result.get('limit_up_error')
    assert result['limit_up_raw_as_of'] == '2026-10-30'
    assert result['limit_up_recent_days_ago'] == 4
    assert result['limit_up_recent_date'] == '2026-10-26'

    bj_path = tmp_path / 'vipdoc' / 'bj' / 'lday' / 'bj920001.day'
    bj_path.parent.mkdir(parents=True)
    bj_path.write_bytes(b''.join(
        RECORD.pack(day, close, close, close, close, 0.0, 100, 0)
        for day, close in zip(_dates(30), [1100 if i == 25 else 1000 for i in range(30)])
    ))
    bj = load_raw_limit_up_metrics(tmp_path, {'bj:920001': str(_dates(30)[-1])})['bj:920001']
    assert bj['limit_up_status'] == 'ok'
    assert bj['limit_up_recent_date'] is None  # 北交所只认30%，不能把+10%当涨停


def test_market_snapshot_merges_raw_limit_up_evidence_and_advances_schema():
    frame = pd.DataFrame({
        'date': pd.bdate_range('2026-10-01', periods=25), 'market': ['sz'] * 25,
        'symbol': ['000001'] * 25, 'open': [10.0] * 25, 'close': [10.0] * 25,
        'volume': [100.0] * 25, 'free_float_shares': [10000.0] * 25,
    })
    raw = {'sz:000001': {
        'limit_up_raw_as_of': DAY, 'limit_up_status': 'ok',
        'limit_up_recent_days_ago': 3, 'limit_up_recent_date': '2026-11-16',
        'limit_up_recent_band_pct': 10, 'limit_up_price_basis': 'raw_unadjusted',
        'limit_up_definition': 'close_equals_exact_board_specific_limit_price',
        'limit_up_history_bars': 25,
    }}
    payload = build_market_metrics(frame, annual_eps={}, raw_limit_up=raw)
    assert payload['schema_version'] == 'stock-filter-market-metrics-v7'
    assert payload['metrics']['sz:000001']['limit_up_recent_days_ago'] == 3


def test_limit_up_filter_runs_before_pagination_and_returns_audit_evidence():
    rows = [_row(i, days_ago=4 if i < 52 else 5) for i in range(53)]
    first = _filter(rows, {'limit_up_n_days': ['5']})
    second = _filter(rows, {'limit_up_n_days': ['5'], 'page': ['2']})
    assert first['ok'] and first['total_matched'] == 52 and len(first['rows']) == 50
    assert second['ok'] and second['total_matched'] == 52 and len(second['rows']) == 2
    assert first['limit_up_filter'] == {
        'days': 5, 'price_basis': 'raw_unadjusted',
        'definition': 'at_least_one_exact_close_limit_up_in_latest_N_valid_trading_days',
        'window_includes_as_of_day': True,
    }
    assert all(row['limit_up_recent_days_ago'] < 5 for row in first['rows'] + second['rows'])


def test_limit_up_filter_includes_today_for_n1_and_excludes_no_event():
    rows = [_row(1, days_ago=0), _row(2, days_ago=1), _row(3, days_ago=None)]
    result = _filter(rows, {'limit_up_n_days': ['1']})
    assert result['total_matched'] == 1
    assert result['rows'][0]['symbol'] == '000001'


def test_limit_up_filter_excludes_same_day_lagged_stock_without_blocking_current_pool():
    current = _row(1, days_ago=0)
    lagged = _row(2, days_ago=0, raw_as_of='2026-11-18')
    lagged['qfq_as_of'] = '2026-11-18'
    missing = _row(3, days_ago=None, raw_as_of=None, status=None)
    missing['qfq_as_of'] = None
    result = _filter([current, lagged, missing], {'limit_up_n_days': ['1']})
    assert result['ok'] and result['total_matched'] == 1
    assert result['rows'][0]['symbol'] == '000001'
    assert result['excluded_missing'] == 2


def test_limit_up_filter_rejects_invalid_historical_or_incomplete_snapshots():
    for raw in ('0', '251', '2.5', '-1', 'abc'):
        result = _filter([_row(1)], {'limit_up_n_days': [raw]})
        assert result['error']['code'] == 'invalid_filter', raw
    historical = _filter([_row(1)], {'limit_up_n_days': ['20'], 'as_of_date': [DAY]})
    assert historical['error']['code'] == 'invalid_filter'
    stale = _filter([_row(1, raw_as_of='2026-11-18')], {'limit_up_n_days': ['20']})
    assert stale['error']['code'] == 'limit_up_unavailable'
    missing = _filter([_row(1, status='missing_file')], {'limit_up_n_days': ['20']})
    assert missing['error']['code'] == 'limit_up_unavailable'


def test_page_exposes_limit_up_n_control_and_disables_it_for_historical_dates():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')
    market = html.split('data-filter-group="market"', 1)[1].split('</fieldset>', 1)[0]
    assert '涨停过滤（收盘封板）' in market and '日内有过涨停' in market
    assert 'name="limit_up_n_days"' in market
    assert 'class="range-pair limit-up-range"' in market
    assert '.limit-up-range' in html and 'white-space:nowrap' in html
    assert 'min="1"' in market and 'max="250"' in market
    historical = (ROOT / 'web/stock-filter-history-capabilities.js').read_text(encoding='utf-8')
    assert "'limit_up_n_days'" in historical
    page_test = (ROOT / 'tests/test_stock_filter_page.py').read_text(encoding='utf-8')
    assert '"limit_up_n_days"' in page_test


def test_build_script_reads_raw_tdx_for_limit_up_snapshot():
    source = (ROOT / 'scripts/build_stock_filter_market_snapshot.py').read_text(encoding='utf-8')
    assert '--tdx-dir' in source
    assert 'load_raw_limit_up_metrics' in source
    assert 'raw_limit_up=raw_limit_up' in source
