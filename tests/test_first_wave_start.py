import unittest

import pandas as pd


class FirstWaveStartTest(unittest.TestCase):
    def test_platform_uses_highest_close_when_isolated_long_upper_shadow_is_outlier(self):
        from app.first_wave_start import choose_platform

        rows = []
        for i in range(8):
            rows.append({"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), "open": 10.0, "high": 10.3, "low": 9.8, "close": 10.1, "volume": 100.0, "amount": 1e8})
        rows[3].update({"high": 11.0, "close": 10.1, "open": 10.0})
        platform = choose_platform(pd.DataFrame(rows))
        self.assertEqual(platform["pressure_basis"], "highest_close_after_isolated_upper_shadow")
        self.assertAlmostEqual(platform["pressure"], 10.1)
        self.assertLessEqual(platform["width_pct"], 20.0)

    def test_scan_marks_first_breakout_and_waiting_for_confirmation_on_b_day(self):
        from app.first_wave_start import scan_symbol

        rows = []
        for i in range(60):
            rows.append({"date": pd.Timestamp("2026-01-01") + pd.offsets.BDay(i), "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100.0, "amount": 1e8})
        for i in range(8):
            rows.append({"date": pd.Timestamp("2026-03-26") + pd.offsets.BDay(i), "open": 10.0, "high": 10.3, "low": 9.8, "close": 10.1, "volume": 100.0, "amount": 1e8})
        rows.append({"date": pd.Timestamp("2026-04-07"), "open": 10.2, "high": 10.7, "low": 10.1, "close": 10.5, "volume": 180.0, "amount": 1e8})
        result = scan_symbol(pd.DataFrame(rows), market="sz", symbol="000001", stock_name="示例", as_of_date="2026-04-07")
        self.assertEqual(result["stage"], "FIRST_BREAKOUT")
        self.assertEqual(result["acceptance_score"], 5.5)
        self.assertEqual(result["classification"], "FIRST_WAVE_WATCH")
        self.assertIn("background_under_120_days", result["risk_tags"])

    def test_breakout_failure_excludes_event_when_close_falls_below_minus_1_5_percent_pressure(self):
        from app.first_wave_start import classify_event
        self.assertEqual(classify_event(pressure=10.0, closes=[10.2, 9.84]), "FAILED_BREAKOUT")


if __name__ == "__main__":
    unittest.main()
