import unittest
from unittest import mock


class IndustryHealthPeersTests(unittest.TestCase):
    def test_returns_snapshot_backed_secondary_industry_rows_without_per_stock_report_loads(self):
        from app.financial import reports

        payload = {
            "ok": True, "market": "sz", "symbol": "000001", "industry_level_2": "测试二级",
            "rows": [{"market": "sz", "symbol": "000001", "stock_name": "甲公司", "is_current_stock": True,
                      "annual": {"score": 76, "dimensions": {"growth_quality": 15}},
                      "quarterly": {"period": "2026Q2", "score": 69, "dimensions": {"growth_quality": 12}}}],
        }
        reports.build_industry_financial_health_peers.cache_clear()
        with mock.patch("app.financial.health_peer_snapshot.build_industry_health_peer_response", return_value=payload) as loader, \
             mock.patch.object(reports, "load_recent_three_year_financial_reports") as raw_loader:
            result = reports.build_industry_financial_health_peers("sz", "000001")

        self.assertEqual(payload, result)
        loader.assert_called_once_with("sz", "000001")
        raw_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
