import unittest


class OwnValuationHistoryTests(unittest.TestCase):
    def test_uses_only_disclosures_already_announced_on_each_raw_price_day(self):
        from app.undervaluation.own_valuation_history import build_own_valuation_history

        result = build_own_valuation_history(
            bars=[
                {"trading_day": "2024-01-02", "close": 10.0},
                {"trading_day": "2024-01-03", "close": 12.0},
                {"trading_day": "2024-04-02", "close": 14.0},
                {"trading_day": "2024-04-03", "close": 16.0},
            ],
            disclosures=[
                {"announce_date": "2024-01-03", "ttm_eps": 2.0, "ttm_revenue": 100.0, "total_shares": 100.0, "period": "2023Q3"},
                {"announce_date": "2024-04-03", "ttm_eps": 4.0, "ttm_revenue": 200.0, "total_shares": 100.0, "period": "2023A"},
            ],
            as_of_date="2024-04-03",
        )

        self.assertEqual(3, result["pe_valid_trading_days"])
        self.assertEqual(3, result["ps_valid_trading_days"])
        self.assertEqual("2023A", result["latest_disclosed_period"])
        self.assertEqual(4.0, result["latest_pe_ttm"])
        self.assertEqual(8.0, result["latest_ps_ttm"])
        self.assertEqual("2024-01-03", result["series"][0]["announce_date"])
        self.assertEqual("2024-04-03", result["series"][-1]["announce_date"])


if __name__ == "__main__":
    unittest.main()
