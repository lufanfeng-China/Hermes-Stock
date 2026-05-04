import unittest
from unittest import mock


class RelativeValuationDataLoaderTests(unittest.TestCase):
    def test_compute_ttm_metric_uses_current_plus_prev_annual_minus_prev_same(self) -> None:
        from app.relative_valuation.data_loader import compute_ttm_metric_from_rows

        current_row = {"归属于母公司所有者的净利润": 30.0}
        prev_annual_row = {"归属于母公司所有者的净利润": 100.0}
        prev_same_row = {"归属于母公司所有者的净利润": 20.0}

        value = compute_ttm_metric_from_rows(
            period="2026Q1",
            field_name="归属于母公司所有者的净利润",
            current_row=current_row,
            prev_annual_row=prev_annual_row,
            prev_same_row=prev_same_row,
        )

        self.assertAlmostEqual(110.0, value, places=6)

    def test_compute_ttm_metric_returns_annual_value_directly_for_annual_period(self) -> None:
        from app.relative_valuation.data_loader import compute_ttm_metric_from_rows

        current_row = {"营业收入": 500.0}

        value = compute_ttm_metric_from_rows(
            period="2025A",
            field_name="营业收入",
            current_row=current_row,
            prev_annual_row=None,
            prev_same_row=None,
        )

        self.assertAlmostEqual(500.0, value, places=6)

    def test_pick_free_float_shares_prefers_free_float_then_listed_a_share(self) -> None:
        from app.relative_valuation.data_loader import pick_free_float_shares

        self.assertAlmostEqual(1200.0, pick_free_float_shares({"自由流通股(股)": 1200.0, "已上市流通A股": 1800.0}), places=6)
        self.assertAlmostEqual(1800.0, pick_free_float_shares({"自由流通股(股)": None, "已上市流通A股": 1800.0}), places=6)
        self.assertIsNone(pick_free_float_shares({"自由流通股(股)": None, "已上市流通A股": None}))

    def test_first_non_null_returns_first_available_value(self) -> None:
        from app.relative_valuation.data_loader import first_non_null

        self.assertEqual(3.2, first_non_null(None, 3.2, 4.1))
        self.assertIsNone(first_non_null(None, None))

    def test_normalize_amount_to_yi_converts_yuan_to_100m_unit(self) -> None:
        from app.relative_valuation.data_loader import normalize_amount_to_yi

        self.assertAlmostEqual(441.97733376, normalize_amount_to_yi(44_197_733_376.0), places=6)
        self.assertIsNone(normalize_amount_to_yi(None))

    def test_compute_ps_ttm_uses_consistent_100m_units(self) -> None:
        from app.relative_valuation.data_loader import compute_ps_ttm

        self.assertAlmostEqual(3.0, compute_ps_ttm(3000.0, 1000.0), places=6)
        self.assertIsNone(compute_ps_ttm(3000.0, None))

    def test_load_industry_valuation_snapshot_uses_cached_snapshot_when_history_and_samples_exist(self) -> None:
        from app.relative_valuation import data_loader

        cached = {
            "industry_level_2_name": "白色家电",
            "temperature_history_since_2022": [{"trading_day": "2026-04-30", "weighted_pe_ttm": 16.8}],
            "percentile_samples": {
                "pe_ttm|A_NORMAL_EARNING": [12.0, 16.0, 18.0],
            },
        }

        with (
            mock.patch.object(data_loader, "_industry_valuation_current_lookup", return_value={"白色家电": cached}),
            mock.patch.object(data_loader, "build_industry_snapshot_for_industry", side_effect=AssertionError("should not rebuild")),
        ):
            snapshot = data_loader.load_industry_valuation_snapshot("白色家电")

        self.assertEqual(cached, snapshot)

    def test_load_industry_valuation_snapshot_rebuilds_when_cached_snapshot_missing_percentile_samples(self) -> None:
        from app.relative_valuation import data_loader

        cached = {
            "industry_level_2_name": "白色家电",
            "temperature_history_since_2022": [{"trading_day": "2026-04-30", "weighted_pe_ttm": 16.8}],
        }
        rebuilt = {
            "industry_level_2_name": "白色家电",
            "temperature_history_since_2022": [{"trading_day": "2026-04-30", "weighted_pe_ttm": 16.8}],
            "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [12.0, 16.0]},
        }

        with (
            mock.patch.object(data_loader, "_industry_valuation_current_lookup", return_value={"白色家电": cached}),
            mock.patch.object(data_loader, "build_industry_snapshot_for_industry", return_value=rebuilt),
        ):
            snapshot = data_loader.load_industry_valuation_snapshot("白色家电")

        self.assertEqual(rebuilt, snapshot)

    def test_load_industry_valuation_snapshot_reuses_rebuilt_snapshot_for_same_industry(self) -> None:
        from app.relative_valuation import data_loader

        cached = {
            "industry_level_2_name": "白色家电",
            "temperature_history_since_2022": [{"trading_day": "2026-04-30", "weighted_pe_ttm": 16.8}],
        }
        rebuilt = {
            "industry_level_2_name": "白色家电",
            "temperature_history_since_2022": [{"trading_day": "2026-04-30", "weighted_pe_ttm": 16.8}],
            "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [12.0, 16.0]},
        }

        if hasattr(data_loader, "_rebuild_industry_snapshot"):
            data_loader._rebuild_industry_snapshot.cache_clear()
        with (
            mock.patch.object(data_loader, "_industry_valuation_current_lookup", return_value={"白色家电": cached}),
            mock.patch.object(data_loader, "build_industry_snapshot_for_industry", return_value=rebuilt) as rebuild_mock,
        ):
            first = data_loader.load_industry_valuation_snapshot("白色家电")
            second = data_loader.load_industry_valuation_snapshot("白色家电")

        self.assertEqual(rebuilt, first)
        self.assertEqual(rebuilt, second)
        self.assertEqual(1, rebuild_mock.call_count)

    def test_load_industry_percentile_sample_prefers_precomputed_snapshot_samples(self) -> None:
        from app.relative_valuation import data_loader

        snapshot = {
            "pe_invalid_threshold": 90.0,
            "percentile_samples": {
                "ps_ttm|B_THIN_PROFIT_DISTORTED": [1.2, 1.8, 2.5],
            },
        }

        with (
            mock.patch.object(data_loader, "load_industry_valuation_snapshot", return_value=snapshot),
            mock.patch.object(data_loader, "_industry_members", side_effect=AssertionError("should not live scan industry members")),
        ):
            sample = data_loader.load_industry_percentile_sample(
                "白色家电",
                "ps_ttm",
                "B_THIN_PROFIT_DISTORTED",
            )

        self.assertEqual([1.2, 1.8, 2.5], sample)

    def test_load_industry_percentile_sample_reads_cached_lookup_before_snapshot_rebuild(self) -> None:
        from app.relative_valuation import data_loader

        cached = {
            "industry_level_2_name": "白色家电",
            "percentile_samples": {
                "pe_ttm|A_NORMAL_EARNING": [12.0, 16.0, 18.0],
            },
        }

        with (
            mock.patch.object(data_loader, "_industry_valuation_current_lookup", return_value={"白色家电": cached}),
            mock.patch.object(data_loader, "load_industry_valuation_snapshot", side_effect=AssertionError("should not rebuild snapshot")),
        ):
            sample = data_loader.load_industry_percentile_sample(
                "白色家电",
                "pe_ttm",
                "A_NORMAL_EARNING",
            )

        self.assertEqual([12.0, 16.0, 18.0], sample)

    def test_build_industry_snapshot_for_industry_attaches_precomputed_percentile_samples(self) -> None:
        from app.relative_valuation import data_loader

        stock_inputs = [
            {
                "market": "sz",
                "symbol": "000001",
                "industry_level_1_name": "家电",
                "industry_level_2_name": "白色家电",
                "listed_days": 300,
                "free_float_market_cap": 200.0,
                "ttm_net_profit": 20.0,
                "ttm_revenue": 100.0,
                "revenue_yoy": 0.12,
                "gross_margin": 0.25,
                "book_value_per_share": 5.0,
                "pe_ttm": 10.0,
                "ps_ttm": 2.0,
                "is_suspended": False,
            },
            {
                "market": "sz",
                "symbol": "000002",
                "industry_level_1_name": "家电",
                "industry_level_2_name": "白色家电",
                "listed_days": 320,
                "free_float_market_cap": 150.0,
                "ttm_net_profit": 1.0,
                "ttm_revenue": 120.0,
                "revenue_yoy": 0.08,
                "gross_margin": 0.20,
                "book_value_per_share": 3.0,
                "pe_ttm": 120.0,
                "ps_ttm": 1.25,
                "is_suspended": False,
            },
            {
                "market": "sz",
                "symbol": "000003",
                "industry_level_1_name": "家电",
                "industry_level_2_name": "白色家电",
                "listed_days": 340,
                "free_float_market_cap": 180.0,
                "ttm_net_profit": -5.0,
                "ttm_revenue": 90.0,
                "revenue_yoy": -0.15,
                "gross_margin": 0.10,
                "book_value_per_share": 2.5,
                "pe_ttm": None,
                "ps_ttm": 2.5,
                "is_suspended": False,
            },
        ]

        with (
            mock.patch.object(data_loader, "_industry_members", return_value=[
                {"market": "sz", "symbol": "000001"},
                {"market": "sz", "symbol": "000002"},
                {"market": "sz", "symbol": "000003"},
            ]),
            mock.patch.object(data_loader, "load_stock_relative_valuation_inputs", side_effect=stock_inputs),
            mock.patch("app.relative_valuation.history.load_industry_temperature_history", return_value=[
                {"trading_day": "2025-12-31", "weighted_pe_ttm": 11.0},
            ]),
            mock.patch.object(data_loader, "_latest_trading_day_for_industry", return_value="2026-04-30"),
        ):
            snapshot = data_loader.build_industry_snapshot_for_industry("白色家电")

        self.assertEqual(
            {
                "pe_ttm|A_NORMAL_EARNING": [10.0],
                "ps_ttm|B_THIN_PROFIT_DISTORTED": [2.0, 1.25, 2.5],
                "ps_ttm|C_LOSS|C1_REVENUE_LOSS": [2.5],
            },
            snapshot["percentile_samples"],
        )

    def test_build_industry_snapshot_for_industry_uses_prefetched_temperature_history(self) -> None:
        from app.relative_valuation import data_loader

        stock_inputs = [
            {
                "market": "sz",
                "symbol": "000001",
                "industry_level_1_name": "家电",
                "industry_level_2_name": "白色家电",
                "listed_days": 300,
                "free_float_market_cap": 200.0,
                "ttm_net_profit": 20.0,
                "ttm_revenue": 100.0,
                "revenue_yoy": 0.12,
                "gross_margin": 0.25,
                "book_value_per_share": 5.0,
                "pe_ttm": 10.0,
                "ps_ttm": 2.0,
                "is_suspended": False,
            },
        ]
        prefetched_history = [{"trading_day": "2025-12-31", "weighted_pe_ttm": 11.0}]

        with (
            mock.patch.object(data_loader, "_industry_members", return_value=[{"market": "sz", "symbol": "000001"}]),
            mock.patch.object(data_loader, "load_stock_relative_valuation_inputs", side_effect=stock_inputs),
            mock.patch("app.relative_valuation.history.load_industry_temperature_history", side_effect=AssertionError("should not recompute history")),
            mock.patch.object(data_loader, "_latest_trading_day_for_industry", return_value="2026-04-30"),
        ):
            snapshot = data_loader.build_industry_snapshot_for_industry(
                "白色家电",
                temperature_history=prefetched_history,
            )

        self.assertEqual(prefetched_history, snapshot["temperature_history_since_2022"])

    def test_latest_trading_day_for_industry_prefers_real_snapshot_day(self) -> None:
        from app.relative_valuation import data_loader

        search_index = mock.Mock()
        search_index._load_latest_daily_snapshot.side_effect = [
            {"latest_close": 10.0, "trading_day": "2026-04-29"},
            {"latest_close": 11.0, "trading_day": "2026-04-30"},
        ]

        with mock.patch.object(data_loader, "_search_index_module", return_value=search_index):
            trading_day = data_loader._latest_trading_day_for_industry(
                [
                    {"market": "sz", "symbol": "000001"},
                    {"market": "sz", "symbol": "000002"},
                ]
            )

        self.assertEqual("2026-04-30", trading_day)
