import unittest


class RelativeValuationHistoryTests(unittest.TestCase):
    def test_period_to_trading_day_maps_quarters_and_annual(self) -> None:
        from app.relative_valuation.history import period_to_trading_day

        self.assertEqual("2022-03-31", period_to_trading_day("2022Q1"))
        self.assertEqual("2022-06-30", period_to_trading_day("2022Q2"))
        self.assertEqual("2022-09-30", period_to_trading_day("2022Q3"))
        self.assertEqual("2022-12-31", period_to_trading_day("2022A"))

    def test_build_temperature_series_from_period_snapshots_keeps_only_valid_weighted_pe_points(self) -> None:
        from app.relative_valuation.history import build_temperature_series_from_period_snapshots

        snapshots = [
            {
                "trading_day": "2022-03-31",
                "weighted_pe_ttm": 18.0,
                "sample_status": "ok",
            },
            {
                "trading_day": "2022-06-30",
                "weighted_pe_ttm": None,
                "sample_status": "ok",
            },
            {
                "trading_day": "2022-09-30",
                "weighted_pe_ttm": 22.0,
                "sample_status": "insufficient",
            },
            {
                "trading_day": "2022-12-31",
                "weighted_pe_ttm": 16.0,
                "sample_status": "ok",
            },
        ]

        history = build_temperature_series_from_period_snapshots(snapshots)

        self.assertEqual(
            [
                {"trading_day": "2022-03-31", "weighted_pe_ttm": 18.0},
                {"trading_day": "2022-12-31", "weighted_pe_ttm": 16.0},
            ],
            history,
        )
