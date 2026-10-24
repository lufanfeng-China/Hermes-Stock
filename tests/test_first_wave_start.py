import unittest
from unittest.mock import patch

import pandas as pd

from app.first_wave_start import scan_symbol, sort_key


def eligible_bars(count=22):
    """Caller-supplied QFQ: prior 20-day return 10%, signal return 5%."""
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=count),
        "close": [10.0] * (count - 2) + [11.0, 11.55],
        "open": [11.0] * count,
        "volume": [100.0] * (count - 1) + [300.0],
    })


def scan(bars, as_of_date=None):
    return scan_symbol(bars, market="sz", symbol="1", stock_name="示例",
                       as_of_date=as_of_date or str(bars.iloc[-1]["date"].date()))


class FirstWaveStartTest(unittest.TestCase):
    def test_twenty_two_bar_candidate_contract_without_legacy_gates(self):
        bars = eligible_bars()
        with patch("app.first_wave_start.choose_platform", side_effect=AssertionError("legacy")), patch(
            "app.first_wave_start.classify_event", side_effect=AssertionError("legacy")
        ), patch("app.first_wave_start._prior_wave", side_effect=AssertionError("legacy")), patch(
            "app.first_wave_start._score_platform", side_effect=AssertionError("legacy")
        ):
            result = scan(bars)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(set(result), {"market", "symbol", "stock_name", "as_of_date", "signal_date",
                                       "current_close", "classification", "evidence"})
        self.assertEqual(result["market"], "sz")
        self.assertEqual(result["stock_name"], "示例")
        self.assertEqual(result["symbol"], "000001")
        self.assertEqual(result["signal_date"], result["as_of_date"])
        self.assertEqual(result["current_close"], 11.55)
        self.assertEqual(result["classification"], "FIRST_WAVE_ELIGIBLE")
        evidence = result["evidence"]
        self.assertEqual(set(evidence), {"current_open", "prior_20d_return_pct", "prior_20d_min_volume",
                                         "prior_20d_max_volume", "current_volume", "volume_multiple",
                                         "day_return_pct", "prior_volume_spread"})
        self.assertAlmostEqual(evidence["prior_20d_return_pct"], 10)
        self.assertAlmostEqual(evidence["day_return_pct"], 5)
        self.assertEqual(evidence["current_open"], 11)
        self.assertEqual(evidence["prior_20d_min_volume"], 100)
        self.assertEqual(evidence["prior_20d_max_volume"], 100)
        self.assertEqual(evidence["current_volume"], 300)
        self.assertEqual(evidence["volume_multiple"], 3)
        self.assertEqual(evidence["prior_volume_spread"], 1)

    def test_volume_multiple_and_spread_inclusive_bounds(self):
        for current, maximum, accepted in ((300, 250, True), (299.999, 250, False),
                                            (300, 250.001, False), (10000, 250, True)):
            with self.subTest(current=current, maximum=maximum):
                bars = eligible_bars()
                bars.loc[1, "volume"] = maximum
                bars.loc[21, "volume"] = current
                self.assertEqual(scan(bars) is not None, accepted)

    def test_future_duplicate_dates_do_not_change_historical_result(self):
        bars = eligible_bars()
        target = str(bars.iloc[-1]["date"].date())
        expected = scan(bars)
        future = bars.iloc[[-1]].copy()
        future["date"] += pd.offsets.BDay()
        self.assertEqual(scan(pd.concat([bars, future, future]), target), expected)

    def test_twenty_one_bars_are_insufficient(self):
        self.assertIsNone(scan(eligible_bars().iloc[1:]))

    def test_required_columns(self):
        for column in ("date", "open", "close", "volume"):
            with self.subTest(column=column), self.assertRaises(ValueError):
                scan(eligible_bars().drop(columns=column), "2026-01-30")

    def test_prior_return_inclusive_bounds_and_adjacent_failures(self):
        for prior, accepted in ((0, True), (20, True), (-0.000001, False), (20.000001, False)):
            with self.subTest(prior=prior):
                bars = eligible_bars()
                bars.loc[0, "close"] = 11 / (1 + prior / 100)
                self.assertEqual(scan(bars) is not None, accepted)

    def test_prior_return_uses_t_minus_21_not_t_minus_20(self):
        bars = eligible_bars()
        bars.loc[1, "close"] = 100.0
        self.assertIsNotNone(scan(bars))
        bars.loc[0, "close"] = 100.0
        self.assertIsNone(scan(bars))

    def test_day_return_boundary_and_adjacent_failure(self):
        for multiplier, accepted in ((1.05, True), (1.04999999, False)):
            for scale in (1, 1.5):
                with self.subTest(multiplier=multiplier, scale=scale):
                    bars = eligible_bars()
                    bars.loc[21, "close"] = 11 * multiplier
                    bars["close"] *= scale
                    self.assertEqual(scan(bars) is not None, accepted)

    def test_signal_close_strictly_above_open(self):
        for opening, accepted in ((11, True), (11.55 - 1e-12, True), (11.55, False), (11.56, False)):
            with self.subTest(opening=opening):
                bars = eligible_bars()
                bars.loc[21, "open"] = opening
                self.assertEqual(scan(bars) is not None, accepted)

    def test_no_moving_average_alignment_or_price_position_gate(self):
        bars = eligible_bars(80)
        bars.loc[:77, "close"] = 100.0
        bars.loc[58, "close"] = 10.0  # t-21 return anchor
        self.assertLess(bars["close"].iloc[-10:].mean(), bars["close"].iloc[-20:].mean())
        self.assertLess(bars["close"].iloc[-1], bars["close"].iloc[-10:].mean())
        self.assertIsNotNone(scan(bars))

    def test_target_day_must_have_exact_bar(self):
        bars = eligible_bars()
        target = str((bars.iloc[-1]["date"] + pd.offsets.BDay()).date())
        self.assertIsNone(scan(bars, target))
        later = bars.iloc[[-1]].copy()
        later["date"] += pd.offsets.BDay(2)
        self.assertIsNone(scan(pd.concat([bars, later]), target))

    def test_future_bad_values_and_input_order_cannot_change_result(self):
        bars = eligible_bars()
        original = bars.copy(deep=True)
        expected = scan(bars)
        self.assertIsNotNone(expected)
        target = str(bars.iloc[-1]["date"].date())
        future = pd.DataFrame({"date": [bars.iloc[-1]["date"] + pd.offsets.BDay()],
                               "close": [float("nan")], "volume": [0], "open": [-1]})
        self.assertEqual(scan(pd.concat([bars, future]), target), expected)
        self.assertEqual(scan(bars.sample(frac=1, random_state=1), target), expected)
        pd.testing.assert_frame_equal(bars, original)

    def test_next_day_is_evaluated_afresh(self):
        bars = eligible_bars()
        next_day = bars.iloc[[-1]].copy()
        next_day["date"] += pd.offsets.BDay()
        self.assertIsNone(scan(pd.concat([bars, next_day])))

    def test_global_missing_and_historical_duplicate_dates_rejected(self):
        bars = eligible_bars()
        self.assertIsNone(scan(pd.concat([bars, bars.iloc[[0]]])))
        for date in (pd.NaT, "invalid"):
            with self.subTest(date=date):
                bad = bars.iloc[[0]].copy()
                bad["date"] = date
                self.assertIsNone(scan(pd.concat([bars, bad]), str(bars.iloc[-1]["date"].date())))

    def test_stable_sort_ignores_legacy_scores(self):
        rows = [{"market": "sz", "symbol": "000001", "total_score": 100},
                {"market": "sh", "symbol": "600001", "total_score": 0},
                {"market": "sh", "symbol": "600000", "total_score": -100}]
        self.assertEqual(sorted(rows, key=sort_key), [rows[2], rows[1], rows[0]])

    def test_legacy_platform_upper_shadow_behavior_is_preserved(self):
        from app.first_wave_start import choose_platform
        rows = [{"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), "open": 10.0,
                 "high": 10.3, "low": 9.8, "close": 10.1, "volume": 100.0, "amount": 1e8}
                for i in range(8)]
        rows[3].update({"high": 11.0, "close": 10.1, "open": 10.0})
        platform = choose_platform(pd.DataFrame(rows))
        self.assertIsNotNone(platform)
        assert platform is not None
        self.assertEqual(platform["pressure_basis"], "highest_close_after_isolated_upper_shadow")
        self.assertAlmostEqual(platform["pressure"], 10.1)
        self.assertLessEqual(platform["width_pct"], 20.0)

    def test_legacy_event_classification_is_preserved(self):
        from app.first_wave_start import classify_event
        self.assertEqual(classify_event(pressure=10.0, closes=[10.2, 9.84]), "FAILED_BREAKOUT")


if __name__ == "__main__":
    unittest.main()
