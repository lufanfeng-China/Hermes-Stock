import unittest


class QuarterlyMomentumTests(unittest.TestCase):
    def test_marks_improving_only_when_growth_profit_and_profitability_all_pass(self):
        from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum

        result = evaluate_quarterly_momentum({
            "status": "available",
            "latest_period": "2026Q2",
            "yoy": {"revenue": 4.0, "ex_net_profit": 2.0},
            "dimensions": [{"code": "profitability", "status": "stable", "available": True}],
        })

        self.assertEqual("IMPROVING", result["status"])
        self.assertTrue(result["improving"])
        self.assertEqual("2026Q2", result["period"])


if __name__ == "__main__":
    unittest.main()
