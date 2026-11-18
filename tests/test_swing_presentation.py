"""All 22 research state labels have one explicit conservative display treatment."""
import csv
from pathlib import Path

from app.swing_presentation import STARS_BY_STATE, presentation


def test_higher_peaks_with_nonrising_valleys_has_no_bullish_rating():
    stock = {'state': '高点上移型上行', 'status': 'ok'}
    view = presentation(stock)
    assert view['tendency'] == 'neutral'
    assert view['star_count'] == 0
    assert view['stars'] == '—'
    assert presentation({**stock, 'new_low_risk': {'date': '2026-11-06'}})['tendency'] == 'neutral'
    assert presentation({**stock, 'status': 'stale_qfq'})['tendency'] == 'unknown'
    assert presentation({'state': '上涨突破', 'status': 'ok'})['stars'] == '★★★'


def test_pending_upturn_is_one_bull_star_while_unmarked_pullback_is_neutral():
    pending = presentation({'state': '上涨止跌待确认', 'status': 'ok'})
    assert (pending['tendency'], pending['star_count'], pending['stars']) == ('bull', 1, '★')
    pullback = presentation({'state': '上涨回撤', 'status': 'ok'})
    assert (pullback['tendency'], pullback['star_count'], pullback['stars']) == ('neutral', 0, '—')


def test_new_low_risk_suspends_bull_stars_without_becoming_neutral_or_unknown():
    stock = {'state': '低点抬升型上行', 'status': 'ok',
             'new_low_risk': {'date': '2026-11-06', 'low': 62.5}}
    view = presentation(stock)
    assert view['tendency'] == 'caution'
    assert view['star_count'] is None
    assert view['stars'] == '星级暂缓'
    assert view['underlying_rating'] == {'tendency': 'bull', 'star_count': 2}
    assert presentation({'state': stock['state'], 'status': 'ok', 'new_low_risk': None})['stars'] == '★★'


def test_v5_research_state_set_matches_one_to_one():
    path=Path('/mnt/c/Users/Sky.Lu/Desktop/output/swing_main_states_v5_2026-10-30.csv')
    if not path.is_file():
        import pytest
        pytest.skip('independent frozen v5 research absent')
    with path.open(encoding='utf-8-sig') as f:
        seen={row['new_state_v5'] for row in csv.DictReader(f) if row['status']=='ok'}
    assert len(seen)==22
    assert seen==set(STARS_BY_STATE)
    for state in seen:
        result=presentation({'state':state,'status':'ok'})
        assert result['tendency'] in {'bull','bear','neutral','unknown'}
        assert result['star_count'] is None or 0 <= result['star_count'] <= 3
    assert presentation({'state':'区间震荡','status':'ok'})['stars']=='—'
    assert presentation({'state':'证据不足','status':'ok'})['stars']=='未知'
    assert presentation({'state':'上涨突破','status':'stale_qfq'})['stars']=='未知'
