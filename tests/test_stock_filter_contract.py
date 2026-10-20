import unittest
from unittest.mock import patch

from app.stock_filter import PAGE_SIZE, filter_response, matches_blowup_break


class StockFilterContractTest(unittest.TestCase):
    def test_page_size_is_fixed_to_fifty(self):
        result = filter_response({"page_size": ["51"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_filter")

    def test_invalid_range_is_rejected(self):
        result = filter_response({"rps_total_min": ["300"], "rps_total_max": ["100"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_filter")

    def test_contract_constant(self):
        self.assertEqual(PAGE_SIZE, 50)

    def test_annual_dimension_range_filters_full_market(self):
        result = filter_response({"annual_growth_quality_min": ["1"], "page": ["1"], "page_size": ["50"]})
        self.assertTrue(result["ok"])
        self.assertGreater(result["total_matched"], 0)
        self.assertTrue(all((row["annual_dimensions"].get("growth_quality") or 0) >= 1 for row in result["rows"]))

    def test_weekly_and_monthly_trend_classifier_uses_homogeneous_resampled_closes(self):
        from app.stock_filter import classify_timeframe_trend

        self.assertEqual(classify_timeframe_trend(list(range(1, 31))), "strong_bullish")
        self.assertEqual(classify_timeframe_trend(list(range(30, 0, -1))), "bearish")
    def test_niche_leader_yes_no_filters_are_applied_before_pagination(self):
        rows = [
            {"symbol": "000001", "market": "sz", "rps_total": 100, "niche_leader": "测试赛道", "annual_dimensions": {}, "quarterly_dimensions": {}},
            {"symbol": "000002", "market": "sz", "rps_total": 99, "niche_leader": "", "annual_dimensions": {}, "quarterly_dimensions": {}},
        ]
        with patch("app.stock_filter._universe", return_value=(rows, "2026-10-16")):
            yes = filter_response({"niche_leader": ["yes"]})
            no = filter_response({"niche_leader": ["no"]})
        self.assertEqual(["000001"], [row["symbol"] for row in yes["rows"]])
        self.assertEqual(["000002"], [row["symbol"] for row in no["rows"]])

    def test_invalid_niche_leader_filter_is_rejected(self):
        result = filter_response({"niche_leader": ["maybe"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_filter")

    def test_blowup_break_requires_volume_price_signal_and_non_bearish_daily_trends(self):
        row = {"blowup_break_volume_price_ok": True, "trend_daily": "bullish", "short_trend": "recovering"}
        self.assertTrue(matches_blowup_break(row))
        self.assertFalse(matches_blowup_break({**row, "short_trend": "neutral"}))
        self.assertFalse(matches_blowup_break({**row, "blowup_break_volume_price_ok": False}))

    def test_blowup_break_preset_filters_before_pagination(self):
        rows = [
            {"symbol": "000001", "market": "sz", "rps_total": 100, "annual_dimensions": {}, "quarterly_dimensions": {}, "blowup_break_volume_price_ok": True, "trend_daily": "bullish", "short_trend": "bullish"},
            {"symbol": "000002", "market": "sz", "rps_total": 99, "annual_dimensions": {}, "quarterly_dimensions": {}, "blowup_break_volume_price_ok": True, "trend_daily": "neutral", "short_trend": "bullish"},
        ]
        with patch("app.stock_filter._universe", return_value=(rows, "2026-10-16")):
            result = filter_response({"preset": ["blowup_break"]})
        self.assertTrue(result["ok"])
        self.assertEqual(["000001"], [row["symbol"] for row in result["rows"]])
    def test_historical_snapshot_building_has_distinct_retryable_error_code(self):
        with patch("app.stock_filter._historical_universe", side_effect=ValueError("historical snapshot is building for 2026-10-13; retry after the build completes")):
            result = filter_response({"as_of_date": ["2026-10-13"]})
        self.assertFalse(result["ok"])
        self.assertEqual("historical_snapshot_building", result["error"]["code"])

    def test_historical_snapshot_building_returns_pollable_progress(self):
        with patch("app.stock_filter._historical_universe", side_effect=ValueError("historical snapshot is building for 2026-10-13; retry after the build completes")), \
             patch("app.stock_filter.read_progress", return_value={"percent": 62, "stage": "计算历史爆量突破量价与趋势", "completed": 3300, "total": 5300}):
            result = filter_response({"as_of_date": ["2026-10-13"]})
        self.assertEqual(62, result["error"]["progress"]["percent"])
        self.assertEqual("计算历史爆量突破量价与趋势", result["error"]["progress"]["stage"])

    def test_historical_date_uses_date_specific_fundamental_snapshot(self):
        rows = [{"symbol": "000001", "market": "sz", "rps_total": 100, "annual_dimensions": {}, "quarterly_dimensions": {}, "pe_ttm": 8.0, "ps_ttm": 1.2}]
        with patch("app.stock_filter._historical_universe", return_value=(rows, "2025-04-20")):
            result = filter_response({"as_of_date": ["2025-04-20"], "pe_ttm_max": ["10"]})
        self.assertTrue(result["ok"])
        self.assertTrue(result["is_historical"])
        self.assertEqual(result["effective_trade_date"], "2025-04-20")
        self.assertEqual(["000001"], [row["symbol"] for row in result["rows"]])


if __name__ == "__main__":
    unittest.main()
