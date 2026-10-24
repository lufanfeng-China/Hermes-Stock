import unittest
from unittest.mock import patch

import pandas as pd

from app.first_wave_start import scan_symbol, sort_key


def eligible_bars(count=60):
    """QFQ fixture: steadily rising close, 20% prior return, 5% day return."""
    closes = [8.0 + i * 0.1 for i in range(count)]
    closes[-32] = 10.0
    closes[-31] = 10.0
    closes[-2] = 12.0
    closes[-1] = 12.6
    # Keep the last 30 closes ascending enough for strict MA alignment.
    closes[-30:-2] = [10.1 + i * 0.065 for i in range(28)]
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=count),
        "close": closes,
        "open": [12.0] * count,
        "volume": [100.0] * (count - 1) + [400.0],
    })


def scan(bars, as_of_date=None):
    return scan_symbol(bars, market="sz", symbol="1", stock_name="示例",
                       as_of_date=as_of_date or str(bars.iloc[-1]["date"].date()))


class FirstWaveStartTest(unittest.TestCase):
    def test_current_five_condition_candidate_contract_without_legacy_gates(self):
        bars = eligible_bars()
        with patch("app.first_wave_start.choose_platform", side_effect=AssertionError("legacy")), patch(
            "app.first_wave_start.classify_event", side_effect=AssertionError("legacy")
        ):
            result = scan(bars)
        self.assertIsNotNone(result)
        self.assertEqual(set(result), {"market", "symbol", "stock_name", "as_of_date", "signal_date",
                                       "current_close", "classification", "evidence"})
        self.assertEqual(result["symbol"], "000001")
        self.assertEqual(result["signal_date"], result["as_of_date"])
        self.assertEqual(result["classification"], "FIRST_WAVE_ELIGIBLE")
        evidence = result["evidence"]
        self.assertEqual(set(evidence), {"prior_30d_return_pct", "ma10", "ma20", "ma30", "ma60",
                                         "prior_30d_min_volume", "prior_30d_max_volume", "current_volume",
                                         "volume_multiple", "day_return_pct", "prior_volume_spread", "current_open"})
        self.assertAlmostEqual(evidence["prior_30d_return_pct"], 20)
        self.assertAlmostEqual(evidence["day_return_pct"], 5)
        self.assertEqual(evidence["volume_multiple"], 4)
        self.assertEqual(evidence["prior_volume_spread"], 1)
        for days in (10, 20, 30, 60):
            self.assertAlmostEqual(evidence[f"ma{days}"], bars["close"].iloc[-days:].mean())

    def test_target_day_must_have_bar_and_no_b_plus_one_carry(self):
        bars = eligible_bars()
        tomorrow = str((bars.iloc[-1]["date"] + pd.offsets.BDay()).date())
        self.assertIsNone(scan(bars, tomorrow))

    def test_future_bars_cannot_change_historical_result(self):
        bars = eligible_bars()
        expected = scan(bars)
        future = pd.DataFrame({"date": [bars.iloc[-1]["date"] + pd.offsets.BDay()],
                               "close": [float("nan")], "volume": [0]})
        self.assertEqual(scan(pd.concat([bars, future]), expected["as_of_date"]), expected)
        self.assertEqual(scan(bars.sample(frac=1, random_state=1), expected["as_of_date"]), expected)

    def test_missing_nonfinite_or_nonpositive_price_volume_rejected(self):
        for column in ("close", "volume"):
            for index in ((0, 28, 29, 58, 59) if column == "close" else (29, 30, 58, 59)):
                for value in (None, float("nan"), float("inf"), -float("inf"), 0, -1, "bad"):
                    with self.subTest(column=column, index=index, value=value):
                        bars = eligible_bars()
                        bars[column] = bars[column].astype(object)
                        bars.loc[index, column] = value
                        self.assertIsNone(scan(bars))

    def test_duplicate_or_missing_date_is_not_silently_dropped(self):
        bars = eligible_bars()
        self.assertIsNone(scan(pd.concat([bars, bars.iloc[[0]]])))
        bars.loc[0, "date"] = pd.NaT
        self.assertIsNone(scan(bars))

    def test_requires_sixty_bars_and_required_columns(self):
        bars = eligible_bars()
        self.assertIsNone(scan(bars.iloc[1:]))
        for column in ("date", "open", "close", "volume"):
            with self.subTest(column=column), self.assertRaises(ValueError):
                scan(bars.drop(columns=column), "2026-03-25")

    def test_inclusive_day_return_boundary_survives_float_subtraction(self):
        bars = eligible_bars()
        bars["close"] *= 1.5
        self.assertIsNotNone(scan(bars))

    def test_prior_return_inclusive_bounds_and_adjacent_failures(self):
        for prior, accepted in ((10, True), (50, True), (9.999, False), (50.001, False)):
            with self.subTest(prior=prior):
                bars = eligible_bars()
                bars.loc[len(bars) - 32, "close"] = 12 / (1 + prior / 100)
                self.assertEqual(scan(bars) is not None, accepted)

    def test_volume_multiple_and_spread_inclusive_bounds(self):
        for current, maximum, accepted in ((300, 300, True), (299.999, 300, False),
                                            (300, 300.001, False), (10000, 300, True)):
            with self.subTest(current=current, maximum=maximum):
                bars = eligible_bars()
                bars.loc[30, "volume"] = maximum
                bars.loc[59, "volume"] = current
                self.assertEqual(scan(bars) is not None, accepted)

    def test_signal_day_must_close_strictly_above_open(self):
        for opening, expected in ((12.0, True), (12.6, False), (12.7, False), (0, False), (float("nan"), False), (float("inf"), False)):
            with self.subTest(opening=opening):
                bars = eligible_bars()
                bars.loc[59, "open"] = opening
                self.assertEqual(scan(bars) is not None, expected)

    def test_historical_bad_open_outside_signal_day_is_irrelevant(self):
        bars = eligible_bars()
        bars.loc[:58, "open"] = float("nan")
        self.assertIsNotNone(scan(bars))

    def test_stable_sort_ignores_legacy_scores(self):
        rows = [{"market": "sz", "symbol": "000001", "total_score": 100},
                {"market": "sh", "symbol": "600001", "total_score": 0},
                {"market": "sh", "symbol": "600000", "total_score": -100}]
        self.assertEqual(sorted(rows, key=sort_key), [rows[2], rows[1], rows[0]])

    def test_each_adjacent_ma_equality_fails_strict_alignment(self):
        for pair in ((10, 20), (20, 30), (30, 60)):
            with self.subTest(pair=pair):
                bars = eligible_bars()
                closes = [8.0] * 30 + [10.0] * 10 + [12.0] * 10 + [12.0] * 9 + [12.75]
                closes[28] = 10.0
                if pair == (10, 20):
                    closes[49] = 12.75
                elif pair == (20, 30):
                    closes[30:40] = [11.0] * 10
                    closes[40:50] = [0.25] + [11.0] * 9
                else:
                    closes[:30] = [11.0] * 28 + [10.0, 12.0]
                    closes[30:40] = [9.75] + [10.5] * 9
                    closes[40:50] = [10.5] * 10
                bars["close"] = closes
                left, right = pair
                self.assertEqual(bars["close"].iloc[-left:].mean(), bars["close"].iloc[-right:].mean())
                self.assertIsNone(scan(bars))

    def test_no_ma_slope_or_close_above_ma10_requirement(self):
        bars = eligible_bars()
        bars.loc[49:57, "close"] = 15.0
        result = scan(bars)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertLess(result["current_close"], result["evidence"]["ma10"])
        self.assertLess(bars["close"].iloc[-10:].mean(), bars["close"].iloc[-11:-1].mean())

    def test_volume_window_is_exactly_thirty_prior_bars_excluding_today(self):
        bars = eligible_bars()
        bars.loc[28, "volume"] = 10000  # t-31 outside volume window
        bars.loc[29, "volume"] = 300    # t-30 included
        result = scan(bars)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["evidence"]["prior_30d_max_volume"], 300)
        bars.loc[29, "volume"] = 301
        self.assertIsNone(scan(bars))
        bars.loc[29, "volume"] = 100
        bars.loc[58, "volume"] = 301  # t-1 included
        self.assertIsNone(scan(bars))

    def test_prior_return_uses_t_minus_31_not_t_minus_30(self):
        bars = eligible_bars()
        bars.loc[29, "close"] = 12.0
        self.assertIsNotNone(scan(bars))
        bars.loc[28, "close"] = 12.0
        self.assertIsNone(scan(bars))

    def test_below_five_percent_day_return_rejected(self):
        bars = eligible_bars()
        bars.loc[59, "close"] = 12 * 1.049999
        self.assertIsNone(scan(bars))

    def test_next_day_is_evaluated_afresh_not_carried_forward(self):
        bars = eligible_bars()
        next_day = pd.DataFrame({"date": [bars.iloc[-1]["date"] + pd.offsets.BDay()],
                                 "close": [12.6], "volume": [400]})
        self.assertIsNone(scan(pd.concat([bars, next_day])))

    def test_platform_uses_highest_close_when_isolated_long_upper_shadow_is_outlier(self):
        from app.first_wave_start import choose_platform
        rows = []
        for i in range(8):
            rows.append({"date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i), "open": 10.0,
                         "high": 10.3, "low": 9.8, "close": 10.1, "volume": 100.0, "amount": 1e8})
        rows[3].update({"high": 11.0, "close": 10.1, "open": 10.0})
        platform = choose_platform(pd.DataFrame(rows))
        self.assertEqual(platform["pressure_basis"], "highest_close_after_isolated_upper_shadow")
        self.assertAlmostEqual(platform["pressure"], 10.1)
        self.assertLessEqual(platform["width_pct"], 20.0)

    def test_breakout_failure_excludes_event_when_close_falls_below_minus_1_5_percent_pressure(self):
        from app.first_wave_start import classify_event
        self.assertEqual(classify_event(pressure=10.0, closes=[10.2, 9.84]), "FAILED_BREAKOUT")


if __name__ == "__main__":
    unittest.main()
