import unittest


class QuarterlyMomentumTests(unittest.TestCase):
    def test_marks_improving_only_when_growth_profit_and_profitability_all_pass(self):
        from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum

        from app.financial.quarterly_monitor import build_quarterly_financial_monitor
        def row(period, revenue, profit):
            return {"period": period, "report_date": period[:4] + ("1231" if period.endswith("A") else "0630"),
                    "metrics": {"revenue": revenue, "ex_net_profit": profit, "gross_margin": 20, "net_margin": 10}}
        monitor = build_quarterly_financial_monitor([
            row("2025Q2", 100, 10), row("2025A", 200, 20), row("2026Q2", 104, 10.2)], "电子")
        result = evaluate_quarterly_momentum(monitor)

        self.assertEqual("IMPROVING", result["status"])
        self.assertTrue(result["improving"])
        self.assertEqual("2026Q2", result["period"])


if __name__ == "__main__":
    unittest.main()
