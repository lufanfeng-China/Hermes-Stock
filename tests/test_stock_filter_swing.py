"""Full-universe causal swing-state filtering; never substitute today's snapshot for history."""
import json
from typing import Any
from pathlib import Path
from unittest.mock import patch

from app import stock_filter


def _rows() -> list[dict[str, Any]]:
    return [dict(market='sh', symbol=f'{600000+i:06d}', stock_name=f'股票{i}',
                 annual_dimensions={}, quarterly_dimensions={}, rps_total=80-i)
            for i in range(65)]


def _snapshot(day='2026-10-30', *, complete=True) -> dict[str, Any]:
    return dict(schema_version='swing-structure-v8', rule_version='swing-confirmed-5x5-pressure-line-ceiling-v8',
                as_of_date=day, price_basis='tdx_export_qfq',
                completeness='complete' if complete else 'sample_only',
                stocks={f"{r['market']}:{r['symbol']}": {
                    'state': '上涨突破' if int(r['symbol']) >= 600055 else '区间震荡',
                    'status': 'ok', 'last_bar_date': day, 'reason': '独立样本'} for r in _rows()})


def test_new_low_observation_filters_full_universe_before_pagination_and_suspends_bull_stars(tmp_path: Path):
    snapshot = _snapshot()
    for number in range(55, 65):
        snapshot['stocks'][f'sh:6000{number:02d}']['new_low_risk'] = {
            'date': '2026-10-29', 'low': 8.0,
            'confirmed_valley_date': '2026-10-10', 'confirmed_valley_low': 9.0,
            'waiting_bars': 1, 'close_below_confirmed_valley': False,
        }
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot, ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        risk = stock_filter.filter_response({'swing_observation': ['new_low_risk']})
        bull = stock_filter.filter_response({'swing_star': ['bull:3']})
        both = stock_filter.filter_response({'swing_state': ['上涨突破'], 'swing_observation': ['new_low_risk']})
        wrong = stock_filter.filter_response({'swing_observation': ['unsupported']})
    assert risk['ok'] and risk['total_matched'] == 10
    assert risk['rows'][0]['symbol'] == '600055'
    assert risk['rows'][0]['swing_structure']['tendency'] == 'caution'
    assert risk['rows'][0]['swing_structure']['stars'] == '星级暂缓'
    assert bull['ok'] and bull['total_matched'] == 0
    assert both['ok'] and both['total_matched'] == 10
    assert wrong['error']['code'] == 'invalid_filter'
    snapshot['stocks']['sh:600055']['last_bar_date'] = '2026-10-29'
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot, ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        stale = stock_filter.filter_response({'swing_observation': ['new_low_risk']})
    assert stale['ok'] and stale['total_matched'] == 9
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        visible = stock_filter.filter_response({'page': ['2']})
    stale_row = next(row for row in visible['rows'] if row['symbol'] == '600055')
    assert stale_row['swing_structure']['status'] == 'stale_qfq'
    assert stale_row['swing_structure'].get('new_low_risk') is None


def test_higher_peaks_state_is_neutral_and_never_matched_by_bull_filters(tmp_path: Path):
    snapshot = _snapshot()
    snapshot['stocks']['sh:600000']['state'] = '高点上移型上行'
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot, ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        state = stock_filter.filter_response({'swing_state': ['高点上移型上行']})
        neutral = stock_filter.filter_response({'swing_tendency': ['neutral']})
        bullish = stock_filter.filter_response({'swing_tendency': ['bull']})
        two_stars = stock_filter.filter_response({'swing_star': ['bull:2']})
    assert state['ok'] and state['total_matched'] == 1
    assert state['rows'][0]['swing_structure']['stars'] == '—'
    assert state['rows'][0]['swing_structure']['tendency'] == 'neutral'
    assert any(row['symbol'] == '600000' for row in neutral['rows'])
    assert all(row['symbol'] != '600000' for row in bullish['rows'])
    assert all(row['symbol'] != '600000' for row in two_stars['rows'])


def test_pending_upturn_is_bull_one_star_and_pullback_is_neutral_in_full_universe(tmp_path: Path):
    snapshot = _snapshot()
    snapshot['stocks']['sh:600000']['state'] = '上涨止跌待确认'
    snapshot['stocks']['sh:600001']['state'] = '上涨回撤'
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot, ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        pending = stock_filter.filter_response({'swing_state': ['上涨止跌待确认']})
        pullback = stock_filter.filter_response({'swing_state': ['上涨回撤']})
        one_star = stock_filter.filter_response({'swing_star': ['bull:1']})
        neutral = stock_filter.filter_response({'swing_star': ['neutral:0']})
    assert pending['total_matched'] == 1 and pending['rows'][0]['symbol'] == '600000'
    assert pending['rows'][0]['swing_structure']['stars'] == '★'
    assert pullback['total_matched'] == 1 and pullback['rows'][0]['symbol'] == '600001'
    assert pullback['rows'][0]['swing_structure']['stars'] == '—'
    assert one_star['total_matched'] == 1 and one_star['rows'][0]['symbol'] == '600000'
    assert any(row['symbol'] == '600001' for row in neutral['rows'])
    assert all(row['symbol'] != '600000' for row in neutral['rows'])


def test_old_v5_publication_cannot_answer_new_observation_filter(tmp_path: Path):
    legacy = _snapshot()
    legacy['rule_version'] = 'swing-confirmed-5x5-v5'
    legacy['schema_version'] = 'swing-structure-v5'
    (tmp_path/'swing_structure_current.json').write_text(json.dumps(legacy, ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        response = stock_filter.filter_response({'swing_observation': ['new_low_risk']})
    assert response['error']['code'] == 'swing_snapshot_unavailable'


def test_swing_filter_before_page_and_evidence(tmp_path: Path):
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(_snapshot(), ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        response=stock_filter.filter_response({'swing_state':['上涨突破'], 'page':['1']})
    assert response['ok'] and response['total_matched']==10
    assert response['rows'][0]['symbol']=='600055'
    assert response['rows'][0]['swing_structure']['state']=='上涨突破'
    assert response['swing_snapshot']['as_of_date']=='2026-10-30'


def test_missing_stale_incomplete_or_missing_symbol_blocks_active_filter(tmp_path: Path):
    path=tmp_path/'swing_structure_v8_current.json'
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        assert stock_filter.filter_response({'swing_state':['区间震荡']})['error']['code']=='swing_snapshot_unavailable'
        assert stock_filter.filter_response({})['ok']
        variants=[_snapshot('2026-10-29'),_snapshot(complete=False),_snapshot(),_snapshot()]
        variants[2]['stocks'].pop('sh:600000')
        variants[3]['rule_version']='old'
        for payload in variants:
            path.write_text(json.dumps(payload,ensure_ascii=False))
            assert stock_filter.filter_response({'swing_state':['区间震荡']})['error']['code']=='swing_snapshot_unavailable'


def test_historical_filter_requires_its_own_snapshot(tmp_path: Path):
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(_snapshot()))
    historical=tmp_path/'swing_structure_v8'; historical.mkdir()
    historical_payload=_snapshot('2026-10-28')
    historical_payload['stocks']['sh:600000']['state']='上涨突破'
    (historical/'2026-10-28.json').write_text(json.dumps(historical_payload,ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_historical_universe', return_value=(_rows(), '2026-10-28')):
        r=stock_filter.filter_response({'as_of_date':['2026-10-28'], 'swing_state':['上涨突破']})
    assert r['ok'] and r['total_matched']==11


def test_lagged_qfq_not_mislabeled_and_invalid_states_rejected(tmp_path: Path):
    payload=_snapshot()
    payload['stocks']['sh:600000']['last_bar_date']='2026-10-29'
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(payload,ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(), '2026-10-30')):
        r=stock_filter.filter_response({'swing_state':['区间震荡']})
        assert r['ok'] and r['total_matched']==54
        assert r['swing_snapshot']['excluded_lagged']==1
        assert stock_filter.filter_response({'swing_state':['不存在的状态']})['error']['code']=='invalid_filter'


def test_outside_current_tnf_is_unknown_not_silent_drop(tmp_path: Path):
    snapshot=_snapshot()
    snapshot['stocks'].pop('sh:600064')
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot,ensure_ascii=False))
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')), \
         patch('app.swing_snapshot.discover_universe',return_value=[('sh','600000','A')]):
        data=stock_filter.filter_response({'swing_tendency':['unknown']})
        assert data['ok'] and data['swing_snapshot']['outside_current_tnf']==1
        assert '600064' in [r['symbol'] for r in data['rows']]
        out=next(r for r in data['rows'] if r['symbol']=='600064')['swing_structure']
        assert out['status']=='out_of_current_tnf' and out['tendency']=='unknown'


def test_unfiltered_list_can_show_same_day_evidence_but_missing_history_never_inherits_today(tmp_path: Path):
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(_snapshot(),ensure_ascii=False))
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')):
        result=stock_filter.filter_response({})
        assert result['ok'] and result['total_matched']==65
        assert result['rows'][0]['swing_structure']['stars']=='—'
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_historical_universe',return_value=(_rows(),'2026-10-28')):
        result=stock_filter.filter_response({'as_of_date':['2026-10-28']})
        assert result['ok'] and result['total_matched']==65
        assert 'swing_structure' not in result['rows'][0]


def test_swing_tendency_state_star_are_or_within_column_unknown_not_neutral(tmp_path: Path):
    snapshot=_snapshot()
    snapshot['stocks']['sh:600002']={'status':'stale_qfq','last_bar_date':'2026-10-29',
        'state':None,'reason':'前复权过期'}
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(snapshot,ensure_ascii=False))
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')):
        combined=stock_filter.filter_response({'swing_state':['上涨突破'],
            'swing_tendency':['unknown'],'swing_star':['neutral:0']})
        assert combined['ok'] and combined['total_matched']==65
        assert {r['swing_structure']['tendency'] for r in combined['rows']}=={'neutral','unknown'}
        next_page=stock_filter.filter_response({'swing_state':['上涨突破'],
            'swing_tendency':['unknown'],'swing_star':['neutral:0'],'page':['2']})
        assert any(r['swing_structure']['tendency']=='bull' for r in next_page['rows'])
        unknown=stock_filter.filter_response({'swing_tendency':['unknown']})
        assert unknown['total_matched']==1 and unknown['rows'][0]['symbol']=='600002'
        assert unknown['rows'][0]['swing_structure']['stars']=='未知'
        neutral=stock_filter.filter_response({'swing_star':['neutral:0']})
        assert neutral['total_matched']==54 and neutral['rows'][0]['swing_structure']['stars']=='—'

