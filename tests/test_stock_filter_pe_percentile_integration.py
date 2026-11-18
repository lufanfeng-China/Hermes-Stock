"""Daily own-history PE percentile is an auditable, full-universe screener field."""
from pathlib import Path
from unittest.mock import patch

from app.stock_filter import filter_response
from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot
from app.pipeline.commands import _data_update_commands
from app.handler import DATA_UPDATE_TASK_PLAN

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-05'


def stock(symbol, rank):
    return {'market':'sz','symbol':symbol,'rps_total':rank,'annual_dimensions':{},'quarterly_dimensions':{},'pe_ttm':10}


def published(day=DAY):
    return {'schema_version':'stock-filter-pe-percentile-v1','as_of_date':day,'stocks':{
        'sz:000001':{'pe_percentile_5y':15.0,'pe_percentile_5y_basis':'five_years','pe_percentile_5y_sample_count':1200,'pe_percentile_5y_price_date':day,'pe_percentile_5y_current_pe':9.1},
        'sz:000002':{'pe_percentile_5y':65.0,'pe_percentile_5y_basis':'since_listing','pe_percentile_5y_sample_count':320,'pe_percentile_5y_price_date':day,'pe_percentile_5y_current_pe':11.1},
        'sz:000003':{'pe_percentile_5y':None,'pe_percentile_5y_status':'insufficient_history','pe_percentile_5y_sample_count':25,'pe_percentile_5y_price_date':day},
    }}


def test_current_pe_percentile_filters_whole_universe_before_pagination():
    rows = [stock('000001', 200), stock('000002', 100), stock('000003', 50)]
    with patch('app.stock_filter._universe',return_value=(rows,DAY)), patch('app.stock_filter._read_pe_percentile_snapshot',return_value=published()):
        result = filter_response({'pe_percentile_5y_min':['50']})
    assert result['ok'] is True
    assert result['total_matched'] == 1
    assert result['rows'][0]['symbol'] == '000002'
    assert result['rows'][0]['pe_percentile_5y_basis'] == 'since_listing'
    assert result['excluded_missing'] == 1


def test_historical_stale_price_with_null_percentile_is_excluded_not_whole_page_error():
    rows = [
        {'market':'sz','symbol':'000001','stock_name':'有效','annual_dimensions':{},'quarterly_dimensions':{},'pe_percentile_5y':15.0,'pe_percentile_5y_price_date':'2026-10-29'},
        {'market':'sz','symbol':'000002','stock_name':'停牌','annual_dimensions':{},'quarterly_dimensions':{},'pe_percentile_5y':None,'pe_percentile_5y_price_date':'2026-10-28','pe_percentile_5y_status':'stale_raw_price'},
    ]
    with patch('app.stock_filter._historical_universe', return_value=(rows,'2026-10-29')):
        result = filter_response({'as_of_date':['2026-10-29'],'pe_percentile_5y_max':['20']})
    assert result['ok'] and result['total_matched'] == 1 and result['excluded_missing'] == 1


def test_stale_current_pe_snapshot_fails_closed_only_when_filter_enabled():
    with patch('app.stock_filter._universe',return_value=([stock('000001',50)],DAY)), patch('app.stock_filter._read_pe_percentile_snapshot',return_value=published('2026-11-04')):
        enabled = filter_response({'pe_percentile_5y_max':['30']})
        display = filter_response({})
    assert enabled['ok'] is False and enabled['error']['code'] == 'pe_percentile_unavailable'
    assert display['ok'] is True
    assert display['rows'][0]['pe_percentile_5y'] is None
    assert display['pe_percentile_snapshot']['status'] == 'stale'


def test_invalid_pe_percentile_bounds_do_not_trigger_expensive_universe_load():
    with patch('app.stock_filter._universe',side_effect=AssertionError('should not load')):
        for params in ({'pe_percentile_5y_min':['101']},{'pe_percentile_5y_max':['nan']},{'pe_percentile_5y_min':['70'],'pe_percentile_5y_max':['20']}):
            assert filter_response(params)['error']['code'] == 'invalid_filter'


def test_historical_pe_percentile_comes_only_from_historical_row():
    row = {**stock('000001',50),'pe_percentile_5y':19.0,'pe_percentile_5y_basis':'five_years','pe_percentile_5y_price_date':'2025-04-18'}
    with patch('app.stock_filter._historical_universe',return_value=([row],'2025-04-18')), patch('app.stock_filter._read_pe_percentile_snapshot',side_effect=AssertionError('must not read current')):
        result = filter_response({'as_of_date':['2025-04-18'],'pe_percentile_5y_max':['20']})
    assert result['ok'] and result['total_matched'] == 1
    assert result['rows'][0]['pe_percentile_5y_price_date'] == '2025-04-18'


def test_historical_builder_projects_same_day_pe_evidence():
    import pandas as pd
    reports={'2024A':pd.DataFrame([{'announce_date':20250401,'基本每股收益':1.0,'营业总收入TTM(万元)':100,'总股本':100000000}],index=['000001'])}
    evidence={'sz:000001':{'pe_percentile_5y':25.0,'pe_percentile_5y_price_date':'2025-04-18','pe_percentile_5y_sample_count':600}}
    result=build_historical_fundamental_snapshot(as_of_date='2025-04-18',period_frames=reports,raw_close_by_symbol={'000001':10},market_by_symbol={'000001':'sz'},industry_by_key={},pe_by_key=evidence)
    assert result['stocks']['sz:000001']['pe_percentile_5y'] == 25.0
    assert result['stocks']['sz:000001']['pe_percentile_5y_price_date'] == '2025-04-18'
    assert result['schema_version'] == 'stock-filter-fundamental-history-v7'


def test_historical_raw_scan_retains_pre_window_bar_and_ignores_future_bar():
    from scripts.build_stock_filter_fundamental_history import _raw_closes
    observed = {}
    bars = [
        {'trading_day': '2020-04-17', 'close': 8.0},
        {'trading_day': '2025-04-17', 'close': 9.0},
        {'trading_day': '2025-04-18', 'close': 10.0},
        {'trading_day': '2025-04-21', 'close': 1000.0},
    ]
    with patch('scripts.build_stock_filter_fundamental_history._load_raw_daily_bars', return_value=bars):
        closes = _raw_closes('2025-04-18', ['000001'], on_bars=lambda symbol, history: observed.setdefault(symbol, history))
    assert closes == {'000001': 10.0}
    assert [day.isoformat() for day, _ in observed['000001']] == ['2020-04-17', '2025-04-17', '2025-04-18']


def test_daily_pe_builder_is_after_financial_update_and_retryable_and_visible():
    ids=[name for name,_ in _data_update_commands(DAY)]
    task='build_stock_filter_pe_percentile_snapshot'
    assert ids.index('update_financial_ts') < ids.index(task)
    assert ids.index('refresh_rps_daily') < ids.index(task)
    assert task in [name for name,_ in _data_update_commands(DAY,retry_failed=True)]
    assert ids == [row['id'] for row in DATA_UPDATE_TASK_PLAN]


def test_page_exposes_real_filter_and_auditable_pe_cell():
    html=(ROOT/'web/stock-filter.html').read_text(encoding='utf-8')
    js=(ROOT/'web/stock-filter.js').read_text(encoding='utf-8')
    assert 'name="pe_percentile_5y_min"' in html and 'name="pe_percentile_5y_max"' in html
    assert 'row.pe_percentile_5y' in js and 'row.pe_percentile_5y_price_date' in js
    assert 'pe_percentile_snapshot' in js


def test_real_current_universe_is_not_the_market_metrics_keyset():
    import json
    from app.stock_filter import FINAL, _universe
    rows, _ = _universe()
    metrics = json.loads((FINAL / 'stock_filter_market_metrics_current.json').read_text(encoding='utf-8'))['metrics']
    universe = {f"{row['market']}:{row['symbol']}" for row in rows}
    assert len(universe) > 5000
    assert universe - set(metrics), '真实基础池与技术快照不同；快照构建必须以基础池为准'
