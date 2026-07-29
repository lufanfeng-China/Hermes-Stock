import sys
import unittest

import pandas as pd

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.search.macd_gc import _entry_price_percentile, _history_rows_with_entry_percentiles


class EntryPricePercentileTests(unittest.TestCase):
    def test_uses_entry_day_close_rank_in_trailing_window(self):
        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"])
        frame = pd.DataFrame({"close": [10.0, 20.0, 30.0, 20.0]}, index=dates)

        # pandas rank(method='average', pct=True): final 20 shares ranks 2 and 3,
        # hence (2.5 / 4) * 100 = 62.5.
        self.assertEqual(62.5, _entry_price_percentile(frame, "2020-01-06", window=4, min_periods=4))

    def test_returns_none_when_history_is_too_short_for_percentile(self):
        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
        frame = pd.DataFrame({"close": [10.0, 20.0, 30.0]}, index=dates)

        self.assertIsNone(_entry_price_percentile(frame, "2020-01-03", window=5, min_periods=4))

    def test_history_rows_receive_entry_day_percentile_without_state_mutation(self):
        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"])
        frame = pd.DataFrame({"close": [10.0, 20.0, 30.0, 20.0]}, index=dates)
        original = [{"code": "000001", "entry_date": "2020-01-06", "pnl": 100.0}]

        enriched = _history_rows_with_entry_percentiles(original, frame, window=4, min_periods=4)

        self.assertEqual(62.5, enriched[0]["pct5y"])
        self.assertNotIn("pct5y", original[0])


if __name__ == "__main__":
    unittest.main()
