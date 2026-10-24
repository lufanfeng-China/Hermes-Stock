import unittest

import pandas as pd

from test_first_wave_start import eligible_bars, scan


class RequiredWindowTests(unittest.TestCase):
    def test_old_invalid_data_outside_required_windows_does_not_add_filter(self):
        bars = eligible_bars()
        expected = scan(bars)
        self.assertIsNotNone(expected)
        for value in (None, float("nan"), float("inf"), -float("inf"), 0, -1, "bad"):
            with self.subTest(value=value):
                old = pd.DataFrame({"date": [bars.iloc[0]["date"] - pd.offsets.BDay()],
                                    "close": [value], "volume": [value], "open": [value]})
                self.assertEqual(expected, scan(pd.concat([old, bars], ignore_index=True)))

    def test_volume_at_t_minus_21_is_outside_required_window(self):
        bars = eligible_bars()
        expected = scan(bars)
        self.assertIsNotNone(expected)
        for value in (None, float("nan"), float("inf"), 0, -1, "bad", 10000):
            with self.subTest(value=value):
                changed = bars.copy()
                changed["volume"] = changed["volume"].astype(object)
                changed.loc[0, "volume"] = value
                self.assertEqual(expected, scan(changed))

    def test_twenty_prior_volume_bars_include_both_endpoints_exclude_today(self):
        for index in (1, 20):
            with self.subTest(index=index):
                bars = eligible_bars()
                bars.loc[0, "volume"] = 10000
                bars.loc[index, "volume"] = 250
                result = scan(bars)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result["evidence"]["prior_20d_max_volume"], 250)
                self.assertEqual(result["evidence"]["prior_volume_spread"], 2.5)
                bars.loc[index, "volume"] = 250.001
                self.assertIsNone(scan(bars))

    def test_prior_minimum_volume_can_occur_at_either_endpoint(self):
        for index in (1, 20):
            with self.subTest(index=index):
                bars = eligible_bars()
                bars["volume"] = 200.0
                bars.loc[0, "volume"] = 1  # t-21 must not set the minimum
                bars.loc[index, "volume"] = 100
                bars.loc[21, "volume"] = 400
                result = scan(bars)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result["evidence"]["prior_20d_min_volume"], 100)
                self.assertEqual(result["evidence"]["volume_multiple"], 4)

    def test_all_required_closes_and_volumes_must_be_finite_positive(self):
        for column, indices in (("close", range(22)), ("volume", range(1, 22))):
            for index in indices:
                for value in (None, float("nan"), float("inf"), -float("inf"), 0, -1, "bad"):
                    with self.subTest(column=column, index=index, value=value):
                        bars = eligible_bars()
                        bars[column] = bars[column].astype(object)
                        bars.loc[index, column] = value
                        self.assertIsNone(scan(bars))

    def test_only_signal_day_open_must_be_finite_positive(self):
        bars = eligible_bars()
        expected = scan(bars)
        self.assertIsNotNone(expected)
        for value in (None, float("nan"), float("inf"), -float("inf"), 0, -1, "bad"):
            with self.subTest(value=value):
                changed = bars.copy()
                changed["open"] = changed["open"].astype(object)
                changed.loc[:20, "open"] = value
                self.assertEqual(expected, scan(changed))
                changed.loc[21, "open"] = value
                self.assertIsNone(scan(changed))

    def test_dates_remain_globally_validated_outside_numeric_windows(self):
        bars = eligible_bars()
        target = str(bars.iloc[-1]["date"].date())
        for date in (pd.NaT, "bad", bars.iloc[0]["date"], bars.iloc[-1]["date"]):
            with self.subTest(date=date):
                extra = pd.DataFrame({"date": [date], "close": [0], "volume": [0]})
                self.assertIsNone(scan(pd.concat([bars, extra]), target))


if __name__ == "__main__":
    unittest.main()
