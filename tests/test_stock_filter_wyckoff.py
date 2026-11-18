"""PIT Wyckoff snapshot contract at the actual all-market stock-filter route."""
import json
from pathlib import Path
from unittest.mock import patch

from app import stock_filter


def _rows():
    return [dict(market='sh', symbol=f'{600000+i:06d}', stock_name=f'股票{i}',
                 annual_dimensions={}, quarterly_dimensions={}, rps_total=80-i)
            for i in range(65)]


def _event(kind='Spring', status='candidate', date='2026-10-29'):
    return dict(type=kind, status=status, date=date, confirmation_date=None,
                invalidated_by=None, evidence={'boundary': 10.0, 'volume_ratio_20': 1.1})


def _snapshot(day, stocks, *, full=True, **overrides):
    if full:
        base = {f"{r['market']}:{r['symbol']}": {'events': [], 'last_bar_date': day} for r in _rows()}
        base.update({key: {'last_bar_date': day, **stock} for key, stock in stocks.items()})
        stocks = base
    return {'schema_version': 'wyckoff-signals-v1',
            'rule_version': 'wyckoff-approved-20261103-v1',
            'as_of_date': day, 'price_basis': 'tdx_export_qfq',
            'completeness': 'complete', 'stocks': stocks, **overrides}


def test_wyckoff_filters_full_universe_before_pagination_and_returns_evidence(tmp_path: Path):
    stocks = {f'sh:{600000+i:06d}': {'events': [_event()]} for i in range(55, 65)}
    (tmp_path / 'wyckoff_signals_current.json').write_text(json.dumps(_snapshot('2026-10-30', stocks)))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        result = stock_filter.filter_response({'wyckoff_type': ['Spring'], 'wyckoff_status': ['candidate'], 'page': ['1']})
    assert result['ok'] and result['total_matched'] == 10
    assert result['rows'][0]['symbol'] == '600055'
    assert result['rows'][0]['wyckoff_signal']['date'] == '2026-10-29'
    assert result['wyckoff_snapshot']['as_of_date'] == '2026-10-30'


def test_wyckoff_type_status_since_are_or_within_type_and_date_as_of(tmp_path: Path):
    stocks = {'sh:600000': {'events': [_event('UT', 'invalidated', '2026-10-20'), _event('Spring', 'confirmed', '2026-10-29')]},
              'sh:600001': {'events': [_event('SOS', 'candidate', '2026-10-30')]}}
    (tmp_path / 'wyckoff_signals_current.json').write_text(json.dumps(_snapshot('2026-10-30', stocks)))
    params = {'wyckoff_type': ['Spring,SOS'], 'wyckoff_status': ['candidate,confirmed'], 'wyckoff_since': ['2026-10-29']}
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        result = stock_filter.filter_response(params)
    assert result['ok'] and result['total_matched'] == 2
    assert {r['wyckoff_signal']['type'] for r in result['rows']} == {'Spring', 'SOS'}


def test_historical_filter_uses_only_same_day_snapshot_and_does_not_use_current(tmp_path: Path):
    (tmp_path / 'wyckoff_signals_current.json').write_text(json.dumps(_snapshot('2026-10-30', {'sh:600000': {'events': [_event()]}})))
    historical = tmp_path / 'wyckoff_signals'
    historical.mkdir()
    (historical / '2026-10-28.json').write_text(json.dumps(_snapshot('2026-10-28', {'sh:600001': {'events': [_event('SOS', 'candidate', '2026-10-28')]}})))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_historical_universe', return_value=(_rows(), '2026-10-28')):
        result = stock_filter.filter_response({'as_of_date': ['2026-10-28'], 'wyckoff_type': ['Spring,SOS']})
    assert result['ok'] and result['total_matched'] == 1 and result['rows'][0]['symbol'] == '600001'


def test_missing_stale_or_incomplete_wyckoff_snapshot_blocks_active_filter(tmp_path: Path):
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        assert stock_filter.filter_response({'wyckoff_type': ['Spring']})['error']['code'] == 'wyckoff_snapshot_unavailable'
        assert stock_filter.filter_response({})['ok']  # no filter must remain usable
        for payload in (_snapshot('2026-10-29', {}), _snapshot('2026-10-30', {}, completeness='sample_only'),
                        _snapshot('2026-10-30', {}, rule_version='old'),
                        _snapshot('2026-10-30', {}, full=False)):
            (tmp_path / 'wyckoff_signals_current.json').write_text(json.dumps(payload))
            assert stock_filter.filter_response({'wyckoff_type': ['Spring']})['error']['code'] == 'wyckoff_snapshot_unavailable'


def test_lagged_qfq_security_is_excluded_with_explicit_coverage_disclosure(tmp_path: Path):
    stocks = {'sh:600000': {'events': [_event()], 'last_bar_date': '2026-10-29'},
              'sh:600001': {'events': [_event()], 'last_bar_date': '2026-10-30'}}
    (tmp_path / 'wyckoff_signals_current.json').write_text(json.dumps(_snapshot('2026-10-30', stocks)))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        result = stock_filter.filter_response({'wyckoff_type': ['Spring']})
    assert result['ok'] and result['total_matched'] == 1
    assert result['rows'][0]['symbol'] == '600001'
    assert result['wyckoff_snapshot']['excluded_lagged'] == 1
    assert result['wyckoff_snapshot']['lagged_symbols'] == ['sh:600000']


def test_stock_filter_page_exposes_wyckoff_filter_and_auditable_filter_status():
    root = Path(__file__).parents[1] / 'web'
    html = (root / 'stock-filter.html').read_text(encoding='utf-8')
    js = (root / 'stock-filter.js').read_text(encoding='utf-8')
    assert 'name="wyckoff_type"' in html and 'name="wyckoff_status"' in html
    assert 'name="wyckoff_since"' in html
    for kind in ('Spring', 'SOS', 'LPS'):
        assert f'value="{kind}"' in html
    from re import search, findall, S
    choices = search(r'<select name="wyckoff_type"[^>]*>(.*?)</select>', html, S)
    assert choices is not None
    assert findall(r'<option value="([^"]+)"', choices.group(1)) == ['Spring', 'SOS', 'LPS']
    statuses = search(r'<select name="wyckoff_status"[^>]*>(.*?)</select>', html, S)
    assert statuses is not None
    assert findall(r'<option value="([^"]+)"', statuses.group(1)) == ['candidate', 'confirmed']
    assert "query.set('wyckoff_status', 'candidate,confirmed')" in js
    assert "query.set('wyckoff_type', 'Spring,SOS,LPS')" in js
    assert 'name="wyckoff_since"' in html
    assert 'wyckoff_type: true' in js
    assert 'row.wyckoff_signal' not in js
    assert 'data.wyckoff_snapshot' in js
    assert 'wyckoff.excluded_lagged' in js and 'wyckoff.lagged_symbols' in js


def test_wyckoff_filter_remains_without_result_column_or_sticky_overlap():
    root = Path(__file__).parents[1] / 'web'
    html = (root / 'stock-filter.html').read_text(encoding='utf-8')
    js = (root / 'stock-filter.js').read_text(encoding='utf-8')
    header = html.split('<table class="filter-table"><thead><tr>', 1)[1].split('</tr></thead>', 1)[0]
    assert '威科夫事件' not in header
    assert 'wyckoffCell(' not in js
    assert 'name="wyckoff_type"' in html
    assert '.filter-table th:nth-last-child(2), .filter-table td:nth-last-child(2) { position:sticky' not in html
    assert '.filter-table th:nth-last-child(2), .filter-table td:nth-last-child(2) { min-width:160px;' not in html
    assert '.filter-table th:last-child, .filter-table td.swing-cell { position:sticky' not in html


def test_wyckoff_snapshot_cache_tracks_file_republication(tmp_path: Path):
    path = tmp_path / 'wyckoff_signals_current.json'
    path.write_text(json.dumps(_snapshot('2026-10-30', {'sh:600000': {'events': [_event()]}})))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_read_json', wraps=stock_filter._read_json) as load:
        first = stock_filter._wyckoff_snapshot('2026-10-30', False)
        again = stock_filter._wyckoff_snapshot('2026-10-30', False)
        assert first is again and load.call_count == 1
        replacement = path.with_suffix('.tmp')
        replacement.write_text(json.dumps(_snapshot('2026-10-30', {'sh:600001': {'events': [_event('SOS')]}})))
        replacement.replace(path)
        assert 'sh:600001' in stock_filter._wyckoff_snapshot('2026-10-30', False)['stocks']
        assert load.call_count == 2


def test_invalid_wyckoff_params_are_rejected_even_before_data_loading():
    for params in ({'wyckoff_type': ['BUY']}, {'wyckoff_status': ['buy']},
                   {'wyckoff_since': ['2026-02-31']}, {'wyckoff_type': ['Spring,BUY']}):
        assert stock_filter.filter_response(params)['error']['code'] == 'invalid_filter'
