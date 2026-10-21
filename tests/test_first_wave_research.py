import unittest

import pandas as pd


class FirstWaveResearchTests(unittest.TestCase):
    def _bars(self):
        rows = []
        dates = pd.bdate_range("2021-01-01", periods=80)
        for day in dates[:68]:
            rows.append({"date": day, "open": 10., "high": 10.2, "low": 9.8, "close": 10., "volume": 100., "amount": 1e8})
        for day in dates[68:76]:
            rows.append({"date": day, "open": 10., "high": 10.3, "low": 9.8, "close": 10.1, "volume": 100., "amount": 1e8})
        rows.append({"date": dates[76], "open": 10.2, "high": 10.7, "low": 10.1, "close": 10.5, "volume": 180., "amount": 1e8})
        for day in dates[77:]:
            rows.append({"date": day, "open": 10.5, "high": 10.7, "low": 10.2, "close": 10.5, "volume": 100., "amount": 1e8})
        return pd.DataFrame(rows)

    def test_continuous_scanner_emits_one_frozen_b_event_not_repeated_state_rows(self):
        from app.first_wave_research import scan_continuous_events
        events = scan_continuous_events(self._bars(), market="sz", symbol="000001", stock_name="示例")
        self.assertEqual(1, len(events))
        self.assertEqual("2021-04-19", events[0]["b_date"])
        self.assertEqual("FIRST_BREAKOUT", events[0]["stage"])

    def test_outcome_requires_complete_raw_future_window_and_uses_t_plus_one_open(self):
        from app.first_wave_research import attach_raw_outcomes
        signal = {"b_date": "2021-04-19", "market": "sz", "symbol": "000001"}
        raw = self._bars().set_index("date")
        raw.iloc[77, raw.columns.get_loc("open")] = 11.0
        outcomes = attach_raw_outcomes([signal], {("sz", "000001"): raw})
        self.assertEqual("2021-04-20", outcomes[0]["entry_date"])
        self.assertEqual(11.0, outcomes[0]["entry_open_raw"])
        self.assertIsNone(outcomes[0]["return_5d_pct"])
        self.assertFalse(outcomes[0]["future_window_complete_20d"])


if __name__ == "__main__":
    unittest.main()
