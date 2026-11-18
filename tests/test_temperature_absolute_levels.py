"""绝对涨幅档位与相对热度排名相互独立。"""
import pytest

from app.concept_temperature import _temperature, build_temperature_rows


@pytest.mark.parametrize('window,cuts', [
    (3, (-5, -2, 0, 1.5, 3)),
    (5, (-7, -3, 0, 2, 4.5)),
    (10, (-12, -5, 0, 3, 6)),
    (20, (-18, -7, 0, 4.5, 9)),
    (60, (-30, -10, 0, 8, 15)),
])
def test_absolute_threshold_boundaries(window, cuts):
    def classify(ret, breadth=80, excess=1, strong=40):
        return _temperature(window, ret, breadth, excess, strong, 25, 30, 3)[0]
    cold, weak, zero, hot, extreme = cuts
    assert classify(cold) == 0
    assert classify(cold + .001) == 1
    assert classify(weak) == 1
    assert classify(weak + .001) == 2
    assert classify(zero) == 2
    assert classify(.001) == 3
    assert classify(hot) == 4
    assert classify(extreme) == 5


@pytest.mark.parametrize('breadth,excess,strong,expected', [
    (49.99, 1, 40, 2), (50, 1, 40, 3),
    (59.99, 1, 40, 3), (60, 0, 40, 3), (60, .01, 40, 4),
    (74.99, 1, 30, 4), (75, 1, 29.99, 4), (75, 1, 30, 5),
])
def test_positive_returns_require_breadth_and_excess_gates(breadth, excess, strong, expected):
    level, label = _temperature(10, 7, breadth, excess, strong, 25, 30, 3)
    assert level == expected
    if breadth < 50:
        assert label == '分化上涨'


def test_insufficient_members_and_negative_returns():
    assert _temperature(10, 20, 100, 5, 80, 50, 2, 3) == (None, '数据不足')
    assert _temperature(10, -9.23, 33.3, -1.52, 0, 0, 30, 3) == (1, '偏冷')
    assert _temperature(10, -12, 33.3, -1.52, 0, 0, 30, 3) == (0, '冰点')


def test_streak_history_uses_only_sixty_sessions():
    import importlib.util
    from pathlib import Path
    module_path = Path(__file__).resolve().parents[1] / 'scripts/build_concept_temperature.py'
    spec = importlib.util.spec_from_file_location('concept_temp_builder_absolute', module_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert builder.STREAK_LOOKBACK == 60
    assert builder.HEAT_TREND_DAYS == 60


def test_api_rejects_legacy_rank_based_dataset():
    from unittest.mock import patch
    from app.api.concept_temperature import handle_concept_temperature
    old = {'as_of_date': '2026-10-30', 'price_basis': 'tdx_export_qfq', 'min_members': 3,
           'windows': {'10': {'concepts': [{'temperature': 3}]}}}
    with patch('app.api.concept_temperature._load', return_value=old):
        result = handle_concept_temperature('window=10')
    assert result['ok'] is False
    assert '重建' in result['error']


def test_rank_and_score_are_not_used_for_absolute_level():
    import pandas as pd
    dates = pd.date_range('2026-01-01', periods=31, freq='B')
    mapping = []
    frames = {}
    for group, end in [('A', 10.1), ('B', 10.2), ('C', 10.29)]:
        for index in range(3):
            symbol = f'{len(frames) + 1:06d}'
            mapping.append({'concept_code': group, 'concept_name': group, 'symbol': symbol})
            frames[symbol] = pd.DataFrame({'close': [10] * 30 + [end], 'volume': [100] * 31}, index=dates)
    rows, _ = build_temperature_rows(mapping, frames, window=10, min_members=3)
    by_name = {row['concept_name']: row for row in rows}
    assert {row['temperature'] for row in rows} == {3}
    assert by_name['C']['heat_rank'] == 1
    assert by_name['A']['heat_rank'] == 3
    assert by_name['C']['heat_percentile'] > by_name['A']['heat_percentile']
    assert by_name['C']['heat_score'] > by_name['A']['heat_score']
