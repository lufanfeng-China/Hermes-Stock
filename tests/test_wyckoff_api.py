"""Contracts for QFQ Wyckoff observation API (not legacy stage history)."""
from http import HTTPStatus
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from app.handler import StockDashboardHandler


def test_wyckoff_api_exposes_equal_volume_evidence_without_changing_event_contract():
    request = Mock()
    dates = pd.bdate_range('2026-01-01', periods=80)
    bars = pd.DataFrame({'open': [100.] * 80, 'high': [104.] * 80,
                         'low': [96.] * 80, 'close': [100.] * 60 + [102.] * 20,
                         'volume': [1000.] * 60 + [1100.] * 20}, index=dates)
    index = pd.DataFrame({'open': [100.] * 80, 'close': [100.] * 80}, index=dates)
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', return_value=bars), \
         patch('app.wyckoff_effort_response.load_sse_intraday_index', return_value=index), \
         patch('app.handler._latest_trading_day_for_refresh', return_value=str(dates[-1].date())):
        StockDashboardHandler.handle_wyckoff_observation(request, 'market=sh&symbol=600519')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.OK
    assert payload['equal_volume_response']['status'] == 'available'
    assert payload['equal_volume_response']['paired_days'] == 20
    assert payload['equal_volume_response']['median_excess_response_pct'] == pytest.approx(2.0)
    assert payload['events'] == []  # no invented phase/event from the descriptive metric


def test_wyckoff_api_rejects_bad_symbols_without_reading_data():
    request = Mock()
    StockDashboardHandler.handle_wyckoff_observation(request, 'symbol=../abc')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.BAD_REQUEST
    assert payload['error']['code'] == 'invalid_symbol'


def test_wyckoff_api_rejects_market_symbol_mismatch_before_loading_data():
    request = Mock()
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily') as loader:
        StockDashboardHandler.handle_wyckoff_observation(request, 'market=sh&symbol=000001')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert payload['error']['code'] == 'market_symbol_mismatch'
    loader.assert_not_called()


def test_wyckoff_api_uses_qfq_not_legacy_history():
    request = Mock()
    bars = pd.DataFrame({'close': [10.0]})
    bars.attrs['price_basis'] = 'tdx_export_qfq'
    result = {'ok': True, 'as_of_date': '2026-10-30', 'box': None, 'events': []}
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', return_value=bars) as loader, \
         patch('app.wyckoff_events.observe_wyckoff', return_value=result) as observer, \
         patch('app.handler._latest_trading_day_for_refresh', return_value='2026-10-30'):
        StockDashboardHandler.handle_wyckoff_observation(request, 'symbol=600519')
    loader.assert_called_once_with('600519')
    observer.assert_called_once_with(bars)
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.OK
    assert payload['symbol'] == '600519'
    assert payload['price_basis'] == 'tdx_export_qfq'
    assert payload['freshness'] == 'current'
    assert payload['reference_trading_day'] == '2026-10-30'


def test_wyckoff_api_blocks_stale_qfq_instead_of_returning_old_events_as_current():
    request = Mock()
    bars = pd.DataFrame({'close': [10.0]})
    result = {'ok': True, 'as_of_date': '2026-10-29', 'events': [{'type': 'Spring'}]}
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', return_value=bars), \
         patch('app.wyckoff_events.observe_wyckoff', return_value=result), \
         patch('app.handler._latest_trading_day_for_refresh', return_value='2026-10-30'):
        StockDashboardHandler.handle_wyckoff_observation(request, 'symbol=600519')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.CONFLICT
    assert payload['ok'] is False
    assert payload['freshness'] == 'stale'
    assert payload['as_of_date'] == '2026-10-29'
    assert payload['reference_trading_day'] == '2026-10-30'
    assert payload['events'] == []


def test_wyckoff_api_does_not_claim_freshness_without_reference_day():
    request = Mock()
    bars = pd.DataFrame({'close': [10.0]})
    result = {'ok': True, 'as_of_date': '2026-10-30', 'events': []}
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', return_value=bars), \
         patch('app.wyckoff_events.observe_wyckoff', return_value=result), \
         patch('app.handler._latest_trading_day_for_refresh', return_value=None):
        StockDashboardHandler.handle_wyckoff_observation(request, 'symbol=600519')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.OK
    assert payload['freshness'] == 'unverified'
    assert payload['reference_trading_day'] is None


def test_wyckoff_api_reports_missing_export_instead_of_raw_fallback():
    request = Mock()
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', side_effect=FileNotFoundError('missing QFQ')):
        StockDashboardHandler.handle_wyckoff_observation(request, 'symbol=600519')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.NOT_FOUND
    assert 'missing QFQ' in payload['error']['message']


def _chart_fixture():
    index = pd.bdate_range('2024-01-01', periods=110)
    frame = pd.DataFrame({'open': [100.] * 110, 'high': [100.5] * 110,
                          'low': [99.5] * 110, 'close': [100.] * 110,
                          'volume': [1000.] * 110}, index=index)
    frame.iloc[60, frame.columns.get_loc('low')] = 97.
    frame.loc[index[61], ['open', 'high', 'low', 'close']] = [100., 101.5, 99.5, 101.]
    frame.loc[index[95], ['open', 'high', 'low', 'close']] = [100., 100.5, 98.5, 99.]
    frame.loc[index[30], ['open', 'high', 'low', 'close', 'volume']] = [0.] * 5
    frame.loc[index[32], 'high'] = 90.  # inconsistent OHLC
    frame.loc[index[100], 'volume'] = 0.
    frame.loc[index[101], 'volume'] = float('nan')
    frame.attrs['price_basis'] = 'tdx_export_qfq'
    return frame, index


def _call_chart(query, frame, reference=None):
    request = Mock()
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily', return_value=frame) as loader, \
         patch('app.handler._latest_trading_day_for_refresh', return_value=reference):
        StockDashboardHandler.handle_wyckoff_observation(request, query)
    return request.respond_json.call_args.args, loader


def test_wyckoff_chart_uses_selected_real_event_and_valid_qfq_window():
    frame, dates = _chart_fixture()
    event_date = str(dates[60].date())
    (status, payload), loader = _call_chart(
        f'market=sh&symbol=600519&chart_event_date={event_date}&chart_event_type=Spring',
        frame, str(dates[-1].date()))
    loader.assert_called_once_with('600519')
    assert status == HTTPStatus.OK
    event = next(e for e in payload['events'] if e['date'] == event_date and e['type'] == 'Spring')
    assert event['invalidated_by']['date'] == str(dates[95].date())
    chart = payload['chart_bars']
    assert chart[0]['trading_day'] == str(dates[23].date())  # 35 valid bars before event
    assert chart[-1]['trading_day'] == str(dates[105].date())  # 8 valid bars after invalidation; two zero-volume rows skipped
    assert next(b for b in chart if b['trading_day'] == event_date)['low'] == 97.
    assert len([b for b in chart if b['trading_day'] < event_date]) == 35
    assert all(set(b) == {'trading_day', 'open', 'high', 'low', 'close', 'volume'} for b in chart)
    assert {str(dates[i].date()) for i in (30, 32, 100, 101)}.isdisjoint(b['trading_day'] for b in chart)
    assert payload['price_basis'] == 'tdx_export_qfq'


@pytest.mark.parametrize('suffix', [
    'chart_event_date=2024-03-01', 'chart_event_type=Spring',
    'chart_event_date=&chart_event_type=Spring',
    'chart_event_date=2024-02-30&chart_event_type=Spring',
    'chart_event_date=20240301&chart_event_type=Spring',
    'chart_event_date=2024-03-01&chart_event_type=Noise',
])
def test_wyckoff_chart_rejects_bad_pair_without_loading_export(suffix):
    request = Mock()
    with patch('app.tdx.qfq_kline.load_tdx_qfq_daily') as loader:
        StockDashboardHandler.handle_wyckoff_observation(request, f'market=sh&symbol=600519&{suffix}')
    status, payload = request.respond_json.call_args.args
    assert status == HTTPStatus.BAD_REQUEST
    assert payload['ok'] is False
    assert 'chart_bars' not in payload
    loader.assert_not_called()


@pytest.mark.parametrize('event_date,event_type', [('2024-03-01', 'Spring'), ('2024-03-25', 'UT')])
def test_wyckoff_chart_rejects_nonexistent_event(event_date, event_type):
    frame, dates = _chart_fixture()
    (status, payload), _ = _call_chart(
        f'market=sh&symbol=600519&chart_event_date={event_date}&chart_event_type={event_type}',
        frame, str(dates[-1].date()))
    assert status in (HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND)
    assert payload['ok'] is False
    assert 'chart_bars' not in payload


def test_wyckoff_chart_stale_export_never_exposes_chart_or_events():
    frame, dates = _chart_fixture()
    (status, payload), _ = _call_chart(
        f'market=sh&symbol=600519&chart_event_date={dates[60].date()}&chart_event_type=Spring',
        frame, '2024-07-01')
    assert status == HTTPStatus.CONFLICT
    assert payload['events'] == []
    assert 'chart_bars' not in payload


def test_wyckoff_chart_requires_verifiable_freshness():
    frame, dates = _chart_fixture()
    (status, payload), _ = _call_chart(
        f'market=sh&symbol=600519&chart_event_date={dates[60].date()}&chart_event_type=Spring',
        frame, None)
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert 'chart_bars' not in payload
    assert payload.get('events', []) == []


def test_wyckoff_chart_unresolved_event_extends_to_latest_bar():
    frame, dates = _chart_fixture()
    frame = frame.iloc[:90].copy()
    frame.loc[dates[61]:, ['open', 'high', 'low', 'close']] = [100., 100.5, 99.5, 100.]
    (status, payload), _ = _call_chart(
        f'market=sh&symbol=600519&chart_event_date={dates[60].date()}&chart_event_type=Spring',
        frame, str(dates[89].date()))
    assert status == HTTPStatus.OK
    assert payload['chart_bars'][-1]['trading_day'] == str(dates[89].date())
