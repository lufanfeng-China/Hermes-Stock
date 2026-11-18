"""Causal recent-entry screening: one to five VALID QFQ sessions, full market before pagination."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app import stock_filter


def _bars(days=8):
    idx = pd.bdate_range('2026-10-19', periods=days)
    return pd.DataFrame({'open': [10.] * days, 'high': [11.] * days,
                         'low': [9.] * days, 'close': [10.] * days,
                         'volume': [100.] * days}, index=idx)


def test_recent_entry_counts_valid_sessions_and_requires_observed_transition():
    from app.swing_entry_snapshot import recent_run
    bars = _bars()
    bars.loc[bars.index[-2], ['open', 'high', 'low', 'close']] = 0
    with patch('app.swing_entry_snapshot.classify', side_effect=lambda b: {
        'state': '上涨突破' if len(b) >= 6 else '区间震荡'}):
        result = recent_run(bars, '上涨突破')
    assert result['start_confirmed'] is True
    assert result['trading_days'] == 2  # the zero-price row does not count
    assert result['start_date'] == str(bars.index[5].date())
    assert result['previous_state'] == '区间震荡'


def test_long_or_unconfirmed_run_never_qualifies_as_just_entered():
    from app.swing_entry_snapshot import recent_run
    with patch('app.swing_entry_snapshot.classify', return_value={'state': '上涨突破'}):
        long_run = recent_run(_bars(), '上涨突破')
        short_history = recent_run(_bars(3), '上涨突破')
    assert long_run['start_confirmed'] is False and long_run['trading_days'] is None
    assert short_history['start_confirmed'] is False and short_history['trading_days'] is None


def _rows():
    return [{'market':'sh', 'symbol':f'{600000+i:06d}', 'stock_name':f'股票{i}',
             'annual_dimensions':{}, 'quarterly_dimensions':{}, 'rps_total':80-i} for i in range(65)]


def _published(day='2026-10-30'):
    entries = {f"sh:{r['symbol']}": {'status':'ok', 'state':'上涨突破',
             'last_bar_date':day, 'source_sha256': f'hash-{r["symbol"]}'} for r in _rows()}
    swing = {'schema_version':'swing-structure-v8', 'rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8',
             'price_basis':'tdx_export_qfq', 'completeness':'complete', 'as_of_date':day,
             'stocks':entries}
    runs = {'schema_version':'swing-state-runs-v5', 'rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8',
            'price_basis':'tdx_export_qfq', 'completeness':'complete', 'as_of_date':day,
            'max_entry_days':5,
            'stocks':{key:{**value, 'state_run':{'state':'上涨突破',
                'start_date':day, 'through_date':day, 'trading_days':1,
                'start_confirmed':True, 'previous_state':'区间震荡', 'previous_date':'2026-10-29'}}
                for key,value in entries.items()}}
    return swing, runs


def _write(tmp_path, day='2026-10-30', historical=False):
    swing, runs = _published(day)
    if historical:
        (tmp_path/'swing_structure_v8').mkdir(exist_ok=True)
        (tmp_path/'swing_state_runs_v5').mkdir(exist_ok=True)
        (tmp_path/'swing_structure_v8'/f'{day}.json').write_text(json.dumps(swing,ensure_ascii=False))
        (tmp_path/'swing_state_runs_v5'/f'{day}.json').write_text(json.dumps(runs,ensure_ascii=False))
    else:
        (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(swing,ensure_ascii=False))
        (tmp_path/'swing_state_runs_v5_current.json').write_text(json.dumps(runs,ensure_ascii=False))
    return runs


def test_entry_filter_uses_full_pool_before_pagination_and_displays_evidence(tmp_path):
    runs = _write(tmp_path)
    for i in range(55):
        runs['stocks'][f'sh:{600000+i:06d}']['state_run']['trading_days'] = 6
    (tmp_path/'swing_state_runs_v5_current.json').write_text(json.dumps(runs,ensure_ascii=False))
    with patch.object(stock_filter, 'FINAL', tmp_path), patch.object(stock_filter, '_universe', return_value=(_rows(),'2026-10-30')):
        result = stock_filter.filter_response({'swing_state':['上涨突破'], 'swing_entry_days':['1'], 'page':['1']})
    assert result['ok'] and result['total_matched'] == 10
    assert result['rows'][0]['symbol'] == '600055'
    assert result['rows'][0]['swing_structure']['state_run']['start_date'] == '2026-10-30'
    assert result['swing_entry_snapshot']['as_of_date'] == '2026-10-30'


def test_entry_bounds_missing_publication_and_changed_parent_fail_closed(tmp_path):
    runs = _write(tmp_path)
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows(),'2026-10-30')):
        for value in ('0','6','1.5','oops'):
            assert stock_filter.filter_response({'swing_state':['上涨突破'],'swing_entry_days':[value]})['error']['code']=='invalid_filter'
        assert stock_filter.filter_response({'swing_entry_days':['1']})['error']['code']=='invalid_filter'
        runs['stocks']['sh:600000']['source_sha256'] = 'different'
        (tmp_path/'swing_state_runs_v5_current.json').write_text(json.dumps(runs,ensure_ascii=False))
        assert stock_filter.filter_response({'swing_state':['上涨突破'],'swing_entry_days':['1']})['error']['code']=='swing_entry_snapshot_unavailable'
        (tmp_path/'swing_state_runs_v5_current.json').unlink()
        assert stock_filter.filter_response({'swing_state':['上涨突破'],'swing_entry_days':['1']})['error']['code']=='swing_entry_snapshot_unavailable'


def test_insufficient_state_is_explicit_and_not_counted_as_eligible(tmp_path):
    from app.swing_entry_snapshot import build_snapshot
    parent, _ = _published()
    parent['stocks'] = {'sh:600000': {**parent['stocks']['sh:600000'], 'state':'证据不足'}}
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(parent,ensure_ascii=False))
    with patch('app.swing_entry_snapshot.load_tdx_qfq_daily', side_effect=AssertionError('should not load')):
        result = build_snapshot(output_dir=tmp_path)
    assert result['coverage']['insufficient_state'] == 1
    assert result['stocks']['sh:600000']['state_run'] is None
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_universe',return_value=(_rows()[:1],'2026-10-30')):
        response = stock_filter.filter_response({'swing_state':['证据不足'],'swing_entry_days':['1']})
    assert response['ok'] and response['total_matched'] == 0


def test_publisher_is_atomic_dated_and_rejects_changed_qfq(tmp_path):
    from app.swing_entry_snapshot import build_snapshot
    parent, _ = _published()
    parent['stocks'] = {'sh:600000': parent['stocks']['sh:600000']}
    (tmp_path/'swing_structure_v8_current.json').write_text(json.dumps(parent,ensure_ascii=False))
    with (patch('app.swing_entry_snapshot._digest', return_value='hash-600000'),
          patch('app.swing_entry_snapshot.load_tdx_qfq_daily', return_value=_bars()),
          patch('app.swing_entry_snapshot.recent_run', return_value={
              'state':'上涨突破','start_date':'2026-10-30','through_date':'2026-10-30',
              'trading_days':1,'start_confirmed':True,'previous_state':'区间震荡',
              'previous_date':'2026-10-29'})):
        # Fixture dates must match the parent trading day.
        bars = _bars()
        bars.index = pd.bdate_range(end='2026-10-30', periods=len(bars))
        with patch('app.swing_entry_snapshot.load_tdx_qfq_daily', return_value=bars):
            result = build_snapshot(output_dir=tmp_path)
    assert result['coverage']['symbols_total'] == 1
    assert (tmp_path/'swing_state_runs_v5'/'2026-10-30.json').exists()
    assert json.loads((tmp_path/'swing_state_runs_v5_current.json').read_text()) == result
    assert not (tmp_path/'.swing_state_runs.building').exists()
    (tmp_path/'swing_state_runs_v5_current.json').unlink()
    with patch('app.swing_entry_snapshot._digest', return_value='changed'):
        import pytest
        with pytest.raises(ValueError, match='source changed'):
            build_snapshot(output_dir=tmp_path)
    assert not (tmp_path/'swing_state_runs_v5_current.json').exists()


def test_pipeline_registers_entry_after_swing_and_allows_independent_retry():
    from app.pipeline.commands import _data_update_commands
    from app.handler import DATA_UPDATE_TASK_PLAN
    tasks = [name for name,_ in _data_update_commands('2026-10-30')]
    assert tasks.index('build_swing_state_runs') == tasks.index('build_swing_snapshot') + 1
    assert 'build_swing_state_runs' in dict(_data_update_commands(None,retry_failed=True))
    assert tasks == [row['id'] for row in DATA_UPDATE_TASK_PLAN]


def test_ui_offers_real_entry_control_and_evidence():
    root=Path(__file__).resolve().parents[1]
    html=(root/'web/stock-filter.html').read_text()
    js=(root/'web/stock-filter.js').read_text()
    assert 'name="swing_entry_days"' in html and 'value="1"' in html and 'value="5"' in html
    assert 'swing_entry_snapshot' in js and 'swing.state_run.start_date' in js


def test_entry_filter_history_never_uses_current_publication(tmp_path):
    _write(tmp_path)
    _write(tmp_path,'2026-10-28',historical=True)
    with patch.object(stock_filter,'FINAL',tmp_path), patch.object(stock_filter,'_historical_universe',return_value=(_rows(),'2026-10-28')):
        result=stock_filter.filter_response({'as_of_date':['2026-10-28'],'swing_state':['上涨突破'],'swing_entry_days':['2']})
        assert result['ok'] and result['total_matched']==65
        (tmp_path/'swing_state_runs_v5'/'2026-10-28.json').unlink()
        missing=stock_filter.filter_response({'as_of_date':['2026-10-28'],'swing_state':['上涨突破'],'swing_entry_days':['2']})
        assert missing['error']['code']=='swing_entry_snapshot_unavailable'
