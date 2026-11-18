"""The single-stock API must disclose exactly published QFQ evidence."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app import swing_api
from app import stock_filter


def test_swing_api_uses_same_snapshot_and_real_qfq_bars(tmp_path: Path):
    source=tmp_path/'SH#600000.txt'; source.write_text('verified')
    digest=swing_api._digest(source)
    day='2026-10-30'
    record={'name':'测试股','status':'ok','state':'上涨突破','reason':'突破最近峰',
            'last_bar_date':day,'source_sha256':digest,
            'last_10_peaks':[{'date':'2026-10-28','confirmed':day,'price':10.5}],
            'last_10_valleys':[]}
    snapshot={'as_of_date':day,'price_basis':'tdx_export_qfq',
              'rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8','stocks':{'sh:600000':record}}
    bars=pd.DataFrame({'open':[9.,10.,11.], 'high':[10.,11.,12.],
                       'low':[8.,9.,10.], 'close':[9.5,10.5,11.5],
                       'volume':[100.,101.,102.]}, index=pd.date_range('2026-10-28',periods=3,freq='B'))
    with patch.object(swing_api,'DEFAULT_EXPORT_DIR',tmp_path), \
         patch.object(swing_api,'_source_day',return_value=day), \
         patch.object(swing_api,'_swing_snapshot',return_value=snapshot), \
         patch.object(swing_api,'state_run',return_value={'state':'上涨突破','start_date':'2026-10-29',
                      'through_date':day,'trading_days':2,'start_confirmed':True,
                      'previous_state':'上涨回撤','previous_date':'2026-10-28'}), \
         patch.object(swing_api,'load_tdx_qfq_daily',return_value=bars):
        response=swing_api.swing_response('600000', as_of_date=day)
        assert response['ok']
        data=response['data']
        assert data['as_of_date']==day and data['price_basis']=='tdx_export_qfq'
        assert data['observation']['stars']=='★★★'
        assert data['bars'][-1]['date']==day
        assert data['bars'][-1]['close']==11.5
        assert data['state_duration']['start_date']=='2026-10-29'
        assert data['state_duration']['trading_days']==2
        source.write_text('changed')
        assert swing_api.swing_response('600000', as_of_date=day)['error']['code']=='swing_source_changed'
    assert swing_api.swing_response('bad')['error']['code']=='invalid_symbol'


def test_swing_api_discloses_risk_event_and_both_close_dates(tmp_path: Path):
    source = tmp_path / 'SZ#300990.txt'; source.write_text('verified')
    day = '2026-11-11'
    event = {'date': '2026-11-06', 'low': 62.5,
             'confirmed_valley_date': '2026-10-09', 'confirmed_valley_low': 86.57,
             'waiting_bars': 3, 'break_day_close_below_confirmed_valley': True,
             'close_below_confirmed_valley': False}
    record = {'name':'同名股', 'status':'ok', 'state':'低点抬升型上行',
              'last_bar_date': day, 'source_sha256': swing_api._digest(source),
              'new_low_risk': event, 'last_10_peaks': [], 'last_10_valleys': []}
    published = {'schema_version':'swing-structure-v8',
                 'rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8',
                 'price_basis':'tdx_export_qfq', 'completeness':'complete',
                 'as_of_date':day, 'stocks':{'sz:300990':record}}
    bars = pd.DataFrame({'open':[85.0], 'high':[90.0], 'low':[80.0],
                         'close':[87.0], 'volume':[100.0]}, index=pd.to_datetime([day]))
    with patch.object(stock_filter, 'FINAL', tmp_path), \
         patch.object(swing_api, 'DEFAULT_EXPORT_DIR', tmp_path), \
         patch.object(swing_api, '_source_day', return_value=day), \
         patch.object(swing_api, 'load_tdx_qfq_daily', return_value=bars):
        archive = tmp_path / 'swing_structure_v8' / f'{day}.json'
        archive.parent.mkdir()
        archive.write_text(__import__('json').dumps(published))
        response = swing_api.swing_response('300990', as_of_date=day)
    assert response['ok'], response
    assert response['data']['observation']['tendency'] == 'caution'
    assert response['data']['observation']['new_low_risk'] == event
    assert response['data']['observation']['underlying_rating'] == {'tendency':'bull', 'star_count':2}


def test_default_single_stock_uses_latest_qfq_without_waiting_for_snapshot(tmp_path: Path):
    source = tmp_path / 'SZ#000001.txt'
    source.write_text('new export content')
    day = '2026-11-12'
    bars = pd.DataFrame({'open': [9., 10., 11.], 'high': [10., 11., 12.],
                         'low': [8., 9., 10.], 'close': [9.5, 10.5, 11.5],
                         'volume': [100., 101., 102.]},
                        index=pd.to_datetime(['2026-11-10', '2026-11-11', day]))
    with patch.object(swing_api, 'DEFAULT_EXPORT_DIR', tmp_path), \
         patch.object(swing_api, '_source_day', return_value=day), \
         patch.object(swing_api, '_swing_snapshot', side_effect=AssertionError('snapshot should not be needed')), \
         patch.object(swing_api, 'load_tdx_qfq_daily', return_value=bars):
        response = swing_api.swing_response('000001')
    assert response['ok'], response
    data = response['data']
    assert data['source_type'] == 'live_qfq'
    assert data['as_of_date'] == day
    assert data['observation']['last_bar_date'] == day
    assert data['observation']['source_sha256'] == swing_api._digest(source)
    assert data['bars'][-1]['date'] == day
    assert data['state_duration']['through_date'] == day


def test_default_single_stock_does_not_require_global_sync_manifest(tmp_path: Path):
    source = tmp_path / 'SZ#000001.txt'; source.write_text('valid local export')
    bars = pd.DataFrame({'open':[9.], 'high':[10.], 'low':[8.],
                         'close':[9.5], 'volume':[100.]},
                        index=pd.to_datetime(['2026-11-13']))
    with patch.object(swing_api, 'DEFAULT_EXPORT_DIR', tmp_path), \
         patch.object(swing_api, '_source_day', side_effect=FileNotFoundError('manifest absent')), \
         patch.object(swing_api, 'load_tdx_qfq_daily', return_value=bars):
        response = swing_api.swing_response('000001')
    assert response['ok'], response
    assert response['data']['as_of_date'] == '2026-11-13'
    assert response['data']['source_as_of_date'] is None


def test_default_single_stock_advances_to_new_qfq_bar_without_republishing(tmp_path: Path):
    source = tmp_path / 'SH#600000.txt'; source.write_text('newer qfq export')
    published = {'as_of_date':'2026-11-06', 'stocks':{'sh:600000':{'source_sha256':'prior-file-digest'}}}
    (tmp_path / 'swing_structure_v8_current.json').write_text(__import__('json').dumps(published))
    bars = pd.DataFrame({'open':[9.,10.], 'high':[10.,11.], 'low':[8.,9.],
                         'close':[9.5,10.5], 'volume':[100.,101.]},
                        index=pd.to_datetime(['2026-11-06','2026-11-09']))
    with patch.object(stock_filter,'FINAL',tmp_path), \
         patch.object(swing_api,'DEFAULT_EXPORT_DIR',tmp_path), \
         patch.object(swing_api,'_source_day',return_value='2026-11-09'), \
         patch.object(swing_api,'load_tdx_qfq_daily',return_value=bars):
        response = swing_api.swing_response('600000')
    assert response['ok'], response
    data = response['data']
    assert data['as_of_date'] == '2026-11-09'
    assert data['source_type'] == 'live_qfq'
    assert data['snapshot_lagged'] is False
    assert data['observation']['source_sha256'] == swing_api._digest(source)
    assert data['bars'][-1]['date'] == '2026-11-09'


def test_single_stock_rejects_future_published_swing(tmp_path: Path):
    published={'schema_version':'swing-structure-v8','rule_version':'swing-confirmed-5x5-pressure-line-ceiling-v8',
               'price_basis':'tdx_export_qfq','completeness':'complete','as_of_date':'2026-11-10',
               'stocks':{'sh:600000':{'status':'ok','state':'上涨突破'}}}
    archive = tmp_path/'swing_structure_v8'/'2026-11-09.json'
    archive.parent.mkdir()
    archive.write_text(__import__('json').dumps(published))
    with patch.object(stock_filter,'FINAL',tmp_path):
        response=swing_api.swing_response('600000', as_of_date='2026-11-09')
    assert response['error']['code']=='swing_snapshot_unavailable'
