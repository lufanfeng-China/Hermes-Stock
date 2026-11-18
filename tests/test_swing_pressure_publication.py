"""New pressure observations require paired, versioned causal publications."""
import json
from unittest.mock import patch

from app import stock_filter, swing_entry_snapshot, swing_snapshot


def _rows():
    return [dict(market='sh', symbol=f'{600000+i:06d}', annual_dimensions={},
                 quarterly_dimensions={}, rps_total=70-i) for i in range(65)]


def _payload(day='2026-10-30'):
    return {'schema_version':'swing-structure-v8',
            'rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8',
            'price_basis':'tdx_export_qfq','completeness':'complete','as_of_date':day,
            'stocks':{f"sh:{r['symbol']}":{'status':'ok', 'state':'高点降低型下行',
                    'last_bar_date':day, 'pressure_line':({'status':'triggered'} if int(r['symbol']) >= 600055 else None),
                    'new_low_risk': ({'date':day} if int(r['symbol']) == 600001 else None)}
                    for r in _rows()}}


def test_pressure_filter_is_full_market_or_with_new_low_and_rejects_old_schema(tmp_path):
    path = tmp_path/'swing_structure_v8_current.json'
    path.write_text(json.dumps(_payload()))
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')):
        pressure = stock_filter.filter_response({'swing_observation':['pressure_line'], 'page':['1']})
        combined = stock_filter.filter_response({'swing_observation':['pressure_line,new_low_risk']})
        assert pressure['ok'] and pressure['total_matched'] == 10
        assert pressure['rows'][0]['symbol'] == '600055'
        assert combined['ok'] and combined['total_matched'] == 11
        assert stock_filter.filter_response({'swing_observation':['oops']})['error']['code'] == 'invalid_filter'
        legacy = _payload()
        legacy['schema_version'] = 'swing-structure-v6'
        legacy['rule_version'] = 'swing-confirmed-5x5-observations-v6'
        path.write_text(json.dumps(legacy))
        assert stock_filter.filter_response({'swing_observation':['pressure_line']})['error']['code'] == 'swing_snapshot_unavailable'
        path.unlink()
        assert stock_filter.filter_response({'swing_observation':['pressure_line']})['error']['code'] == 'swing_snapshot_unavailable'


def test_stale_pressure_evidence_never_appears_in_list_rows(tmp_path):
    payload = _payload()
    payload['stocks']['sh:600055']['last_bar_date'] = '2026-10-29'
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(payload))
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')):
        response = stock_filter.filter_response({'swing_observation':['pressure_line']})
        visible = stock_filter.filter_response({'page':['2']})
        unknown = stock_filter.filter_response({'swing_tendency':['unknown']})
    assert response['total_matched'] == 9
    stale = next(row for row in visible['rows'] if row['symbol'] == '600055')
    assert stale['swing_structure']['pressure_line'] is None
    assert unknown['rows'][0]['swing_structure']['pressure_line'] is None


def test_old_entry_child_cannot_claim_new_parent(tmp_path):
    parent = _payload()
    parent['stocks'] = {'sh:600000': {**parent['stocks']['sh:600000'], 'state':'证据不足'}}
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(parent))
    with patch('app.swing_entry_snapshot.load_tdx_qfq_daily',side_effect=AssertionError('unexpected load')):
        child = swing_entry_snapshot.build_snapshot(output_dir=tmp_path)
    assert child['schema_version'] == 'swing-state-runs-v5'
    assert (tmp_path/'swing_state_runs_v5_current.json').exists()
    assert child['rule_version'] == parent['rule_version']


def test_new_publisher_paths_do_not_overwrite_old_trusted_files():
    assert swing_snapshot.SCHEMA_VERSION == 'swing-structure-v8'
    assert swing_snapshot.RULE_VERSION == 'swing-confirmed-5x5-pressure-line-ceiling-v8'
    assert swing_entry_snapshot.SCHEMA_VERSION == 'swing-state-runs-v5'
