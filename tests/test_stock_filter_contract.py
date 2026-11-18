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

    def test_pe_ttm_ascending_sorts_full_pool_and_puts_missing_values_last(self):
        rows = [
            {"market": "sz", "symbol": f"{i:06d}", "pe_ttm": value,
             "annual_dimensions": {}, "quarterly_dimensions": {}}
            for i, value in enumerate([None, 12.0, -4.0, 0.0, 3.0])
        ]
        with patch("app.stock_filter._universe", return_value=(rows, "2026-11-06")), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}):
            result = filter_response({"sort": ["pe_ttm"], "order": ["asc"]})
        self.assertTrue(result["ok"])
        self.assertEqual(["000002", "000003", "000004", "000001", "000000"],
                         [row["symbol"] for row in result["rows"]])

    def test_existing_descending_sort_keeps_missing_values_last(self):
        rows = [{"market": "sz", "symbol": f"{i:06d}", "rps_total": value,
                 "annual_dimensions": {}, "quarterly_dimensions": {}}
                for i, value in enumerate([None, 0.0, 20.0])]
        with patch("app.stock_filter._universe", return_value=(rows, "2026-11-06")), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}):
            result = filter_response({"sort": ["rps_total"], "order": ["desc"]})
        self.assertTrue(result["ok"])
        self.assertEqual(["000002", "000001", "000000"],
                         [row["symbol"] for row in result["rows"]])

    def test_price_five_year_percentile_ascending_sorts_before_pagination_and_stale_last(self):
        day = "2026-11-06"
        rows = [{"market": "sz", "symbol": f"{i:06d}", "annual_dimensions": {},
                 "quarterly_dimensions": {}, "price_percentile_5y": float(52 - i),
                 "qfq_as_of": day} for i in range(52)]
        rows[1]["price_percentile_5y"] = 0.0
        rows[50]["price_percentile_5y"] = None
        rows[51].update(price_percentile_5y=-99.0, qfq_as_of="2026-11-05")
        with patch("app.stock_filter._universe", return_value=(rows, day)), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}):
            first = filter_response({"sort": ["price_percentile_5y"], "order": ["asc"]})
            second = filter_response({"sort": ["price_percentile_5y"], "order": ["asc"], "page": ["2"]})
        self.assertTrue(first["ok"])
        self.assertEqual(52, first["total_matched"])
        self.assertEqual("000001", first["rows"][0]["symbol"])
        self.assertEqual(["000050", "000051"], [row["symbol"] for row in second["rows"]])

    def test_price_five_year_percentile_historical_sort_uses_historical_values(self):
        day = "2025-10-16"
        rows = [{"market": "sz", "symbol": str(i).zfill(6), "annual_dimensions": {},
                 "quarterly_dimensions": {}, "price_percentile_5y": value, "qfq_as_of": day}
                for i, value in [(1, 85.0), (2, 15.0)]]
        with patch("app.stock_filter._historical_universe", return_value=(rows, day)):
            result = filter_response({"as_of_date": [day], "sort": ["price_percentile_5y"], "order": ["asc"]})
        self.assertTrue(result["ok"])
        self.assertEqual(["000002", "000001"], [row["symbol"] for row in result["rows"]])

    def test_price_five_year_percentile_sort_rejects_all_missing_or_stale_data(self):
        day = "2026-11-06"
        rows = [{"market": "sz", "symbol": "000001", "annual_dimensions": {},
                 "quarterly_dimensions": {}, "price_percentile_5y": 20.0, "qfq_as_of": "2026-11-05"}]
        with patch("app.stock_filter._universe", return_value=(rows, day)), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}):
            result = filter_response({"sort": ["price_percentile_5y"], "order": ["asc"]})
        self.assertFalse(result["ok"])
        self.assertEqual("price_percentile_unavailable", result["error"]["code"])

    def test_pe_five_year_percentile_ascending_sorts_before_pagination_and_nulls_last(self):
        day = "2026-11-06"
        rows = [{"market": "sz", "symbol": f"{i:06d}", "annual_dimensions": {},
                 "quarterly_dimensions": {}} for i in range(52)]
        values: dict[int, float | None] = {i: float(100 - i) for i in range(52)}
        values[1] = 0.0
        values[51] = None
        snapshot = {"schema_version": "stock-filter-pe-percentile-v1", "as_of_date": day,
                    "stocks": {f"sz:{i:06d}": {"pe_percentile_5y": values[i],
                                              "pe_percentile_5y_price_date": day}
                               for i in range(52)}}
        with patch("app.stock_filter._universe", return_value=(rows, day)), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value=snapshot):
            first = filter_response({"sort": ["pe_percentile_5y"], "order": ["asc"]})
            second = filter_response({"sort": ["pe_percentile_5y"], "order": ["asc"], "page": ["2"]})
        self.assertTrue(first["ok"])
        self.assertEqual("000001", first["rows"][0]["symbol"])
        self.assertEqual(["000000", "000051"], [row["symbol"] for row in second["rows"]])

    def test_pe_five_year_percentile_sort_rejects_stale_snapshot_and_historical_price_date(self):
        day = "2026-11-06"
        row = {"market": "sz", "symbol": "000001", "annual_dimensions": {}, "quarterly_dimensions": {},
               "pe_percentile_5y": 12.0, "pe_percentile_5y_price_date": "2026-11-05"}
        with patch("app.stock_filter._universe", return_value=([row], day)), \
             patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}):
            current = filter_response({"sort": ["pe_percentile_5y"], "order": ["asc"]})
        with patch("app.stock_filter._historical_universe", return_value=([row], day)):
            historical = filter_response({"as_of_date": [day], "sort": ["pe_percentile_5y"], "order": ["asc"]})
        self.assertEqual("pe_percentile_unavailable", current["error"]["code"])
        self.assertEqual("pe_percentile_unavailable", historical["error"]["code"])


if __name__ == "__main__":
    unittest.main()
