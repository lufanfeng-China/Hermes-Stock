import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.search.macd_gc import (
    _entry_price_percentile,
    _history_rows_with_entry_percentiles,
    _scan_stock,
    _signal_price_percentile,
)


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

    def test_signal_percentile_uses_only_bars_available_at_signal_close(self):
        closes = [10.0, 20.0, 30.0, 20.0, 1000.0]

        percentile = _signal_price_percentile(closes, 3, window=4, min_periods=4)

        self.assertEqual(62.5, percentile)

    def test_buy_signal_does_not_require_a_five_year_percentile(self):
        dates = pd.date_range("2026-01-02", periods=100, freq="B")
        closes = np.full(100, 100.0)
        opens = np.full(100, 100.0)
        ndif = np.full(100, -3.0)
        ndea = np.full(100, -2.5)
        ma10 = np.full(100, 100.0)
        ndif[-1] = -2.0
        ma10[-1] = 101.0

        buys, replenishes, sells = _scan_stock(
            "000001", dates, closes, opens, ndif, ndea, ma10,
            {"config": {"lot": 50_000}, "positions": {}},
        )

        self.assertEqual(1, len(buys))
        self.assertEqual([], replenishes)
        self.assertEqual([], sells)

    def test_position_pnl_uses_raw_price_while_macd_uses_signal_price(self):
        dates = pd.date_range("2026-01-02", periods=100, freq="B")
        signal_closes = np.full(100, 10.0)
        raw_closes = np.full(100, 100.0)
        raw_opens = np.full(100, 100.0)
        ndif = np.full(100, -3.0)
        ndea = np.full(100, -2.5)
        ma10 = np.full(100, 10.0)
        ndif[-1] = -2.0
        ma10[-1] = 11.0
        state = {
            "config": {"lot": 50_000},
            "positions": {"000001": {"entries": [{"date": "2026-01-02", "price": 50.0, "shares": 100}]}},
        }

        _, _, sells = _scan_stock(
            "000001", dates, signal_closes, raw_opens, ndif, ndea, ma10, state,
            raw_closes=raw_closes,
        )

        self.assertEqual(1, len(sells))
        self.assertEqual(10_000.0, sells[0]["current_value"])
        self.assertEqual(100.0, sells[0]["pnl_pct"])


if __name__ == "__main__":
    unittest.main()
