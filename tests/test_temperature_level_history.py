"""60-day absolute temperature levels reuse the already computed daily heat series."""
import re
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import build_concept_temperature as builder
from app.api.concept_temperature import handle_concept_temperature_trend

ROOT = Path(__file__).resolve().parents[1]


def test_window_payload_publishes_aligned_daily_levels_without_another_scan(monkeypatch):
    dates = pd.to_datetime(['2026-11-03', '2026-11-04', '2026-11-05'])
    frames = {'000001': pd.DataFrame(index=dates)}
    observed = []

    def fake_rows(mapping, frames, window, min_members, as_of=None, include_members=True, prepared=None):
        day = (as_of or dates[-1]).strftime('%Y-%m-%d')
        observed.append(day)
        levels = {'2026-11-03': 2, '2026-11-04': None, '2026-11-05': 4}
        return ([{'concept_code': 'C1', 'temperature': levels[day], 'heat_score': 52.0,
                  'concept_name': '样例'}], {})

    monkeypatch.setattr(builder, 'build_temperature_rows', fake_rows)
    payload = builder._window_payload(10, [], frames, dates[-1], 3)
    assert observed == ['2026-11-05', '2026-11-03', '2026-11-04']
    assert payload['heat_history']['C1'] == [
        {'date': '2026-11-03', 'heat_score': 52.0, 'temperature': 2},
        {'date': '2026-11-04', 'heat_score': 52.0, 'temperature': None},
        {'date': '2026-11-05', 'heat_score': 52.0, 'temperature': 4},
    ]
    assert payload['concepts'][0]['temperature_streak_days'] == 1


def _snapshot(points):
    return {'as_of_date': '2026-11-05', 'price_basis': 'tdx_export_qfq',
            'temperature_basis': 'absolute_median_return_v1',
            'windows': {'10': {'concepts': [{'concept_code': 'C1', 'concept_name': '样例', 'temperature': 4}],
                               'heat_history': {'C1': points}}}}


def test_temperature_trend_api_reads_saved_levels_for_industry_and_concept():
    points = [{'date': '2026-11-04', 'heat_score': 55, 'temperature': None},
              {'date': '2026-11-05', 'heat_score': 62, 'temperature': 4}]
    with patch('app.api.concept_temperature._load', return_value=_snapshot(points)):
        for scope in ('concept', 'industry'):
            result = handle_concept_temperature_trend(f'scope={scope}&window=10&concept_code=C1&metric=temperature')
            assert result['ok'] and result['metric'] == 'temperature'
            assert result['points'] == points
            assert result['as_of_date'] == '2026-11-05'
        old = handle_concept_temperature_trend('window=10&concept_code=C1')
    assert old['ok'] and old['points'] == points  # old heat-score entry stays usable


def test_temperature_trend_rejects_stale_snapshot_without_levels():
    with patch('app.api.concept_temperature._load', return_value=_snapshot([{'date': '2026-11-05', 'heat_score': 62}])):
        result = handle_concept_temperature_trend('window=10&concept_code=C1&metric=temperature')
    assert not result['ok'] and result['status'] == 409
    assert '重建' in result['error']


def test_temperature_trend_rejects_unknown_metric():
    assert handle_concept_temperature_trend('window=10&concept_code=C1&metric=invalid')['status'] == 400


def test_temperature_change_cell_opens_level_dialog_without_selecting_row():
    html = (ROOT / 'web/concept-temperature.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/concept-temperature.js').read_text(encoding='utf-8')
    assert 'data-temperature-trend-code' in js
    assert 'openHeatTrend(button.dataset.temperatureTrendCode, \'temperature\')' in js
    assert 'event.stopPropagation()' in js
    assert 'metric=' in js
    assert '历史温度档位' in js
    assert '当前成分' in js and '非历史时点成分' in js
    assert 'trend-close' in html and 'heat-chart' in html


def test_trend_dialog_is_centered_and_does_not_call_missing_days_valid():
    html = (ROOT / 'web/concept-temperature.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/concept-temperature.js').read_text(encoding='utf-8')
    assert re.search(r'\.trend-dialog\{[^}]*margin:auto', html)
    assert '条交易日记录' in js
    assert '个有效记录' not in js
