import unittest


class FinancialHealthAnchorTests(unittest.TestCase):
    def test_selects_latest_annual_and_latest_quarter_with_comparable_prior_quarter(self):
        from app.financial.health_peer_anchor import select_health_snapshot_periods
        result = select_health_snapshot_periods(["2021A", "2022A", "2023A", "2024A", "2025A", "2025Q3", "2026Q1", "2026Q2", "2026Q3"])
        self.assertEqual("2025A", result["annual_anchor"])
        self.assertEqual("2026Q3", result["quarterly_anchor"])
        self.assertEqual(["2021A", "2022A", "2023A", "2024A", "2025A", "2025Q3", "2026Q3"], result["periods"])
