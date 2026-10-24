import unittest
import pandas as pd
from test_first_wave_start import eligible_bars, scan


class RequiredWindowTests(unittest.TestCase):
    def test_old_invalid_data_outside_required_windows_does_not_add_filter(self):
        bars = eligible_bars()
        old = pd.DataFrame({'date': [bars.iloc[0]['date'] - pd.offsets.BDay()], 'close': [float('nan')], 'volume': [0]})
        self.assertEqual(scan(bars), scan(pd.concat([old, bars], ignore_index=True)))

    def test_volume_before_prior_thirty_day_window_is_irrelevant(self):
        bars = eligible_bars()
        expected = scan(bars)
        bars.loc[:28, 'volume'] = 0
        self.assertEqual(expected, scan(bars))

if __name__ == '__main__':
    unittest.main()
