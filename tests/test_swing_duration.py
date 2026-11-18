"""The current swing label's run starts when it first becomes knowable, not at a pivot."""
from unittest.mock import patch

import pandas as pd

from app import swing_duration


def _bars():
    rows = pd.DataFrame({
        'open': [10., 10., 0., 10., 10.], 'high': [11., 11., 0., 11., 11.],
        'low': [9., 9., 0., 9., 9.], 'close': [10., 10., 0., 10., 10.],
        'volume': [100.] * 5,
    }, index=pd.to_datetime(['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06']))
    return rows


def test_current_label_run_counts_valid_bars_and_the_first_identifiable_day():
    def fake_classify(prefix):
        return {'state': '上涨突破' if len(prefix) >= 3 else '上涨回撤'}
    with patch.object(swing_duration, 'classify', side_effect=fake_classify):
        result = swing_duration.state_run(_bars(), '上涨突破')
    assert result == {
        'state': '上涨突破', 'start_date': '2026-11-05', 'through_date': '2026-11-06',
        'trading_days': 2, 'start_confirmed': True, 'previous_state': '上涨回撤',
        'previous_date': '2026-11-03',
    }


def test_run_at_first_available_bar_is_only_a_lower_bound():
    with patch.object(swing_duration, 'classify', return_value={'state': '上涨突破'}):
        result = swing_duration.state_run(_bars(), '上涨突破')
    assert result['start_date'] == '2026-11-02'
    assert result['trading_days'] == 4
    assert result['start_confirmed'] is False
    assert result['previous_state'] is None


def test_run_does_not_pretend_to_match_a_different_published_label():
    with patch.object(swing_duration, 'classify', return_value={'state': '下跌破位'}):
        assert swing_duration.state_run(_bars(), '上涨突破') is None
