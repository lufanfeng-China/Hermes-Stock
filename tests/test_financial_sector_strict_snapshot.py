import unittest

from app.stock_filter_snapshot import build_sector_strict_financial_record


class FinancialSectorStrictSnapshotTests(unittest.TestCase):
    def test_bank_sector_record_projects_model_annual_and_latest_quarter(self) -> None:
        source = {
            "symbol": "600036", "sector_model": "bank",
            "financial_model": {"code": "bank", "label": "银行模型"},
            "annual_period": "2025A",
            "annual_score": {
                "score": 93.0, "coverage_weight": 100.0, "status": "ready",
                "score_version": "bank-health-v1", "score_comparability": "within_bank_only",
                "dimensions": {"asset_quality": {"score": 23.0}, "capital_adequacy": {"score": 20.0}},
                "red_flags": [],
            },
            "quarterly_score": {
                "score": 88.0, "coverage_weight": 100.0, "status": "stable",
                "score_version": "bank-quarterly-v1", "report_period": "2026Q3",
                "parts": {"npl_ratio": {"score": 15.0}},
            },
            "latest_announced_period": "2026Q3",
            "latest_valid_period": "2026Q3",
            "latest_scored_period": "2026Q3",
            "update_status": "up_to_date",
            "last_error": None,
        }
        record = build_sector_strict_financial_record(source, annual_anchor="2025A", quarterly_anchor="2026Q3")
        self.assertEqual("bank", record["financial_model"]["code"])
        self.assertEqual(93.0, record["annual"]["score"])
        self.assertEqual("bank-health-v1", record["annual"]["score_version"])
        self.assertEqual(88.0, record["quarterly"]["score"])
        self.assertEqual("2026Q3", record["quarterly"]["period"])
        self.assertTrue(record["good_stock_quality"]["eligible"])
        self.assertEqual("sector_blended", record["composite"]["mode"])

    def test_new_announcement_pending_does_not_masquerade_previous_score_as_latest(self) -> None:
        source = {
            "symbol": "600030", "sector_model": "securities",
            "financial_model": {"code": "securities", "label": "证券模型"},
            "annual_period": "2025A",
            "annual_score": {
                "score": 73.0, "coverage_weight": 100.0, "status": "ready",
                "score_version": "securities-health-v1", "score_comparability": "within_securities_only",
                "dimensions": {}, "red_flags": [],
            },
            "quarterly_score": {
                "score": 74.0, "coverage_weight": 90.0, "status": "stable",
                "score_version": "securities-quarterly-v1", "report_period": "2026H1", "parts": {},
            },
            "latest_announced_period": "2026Q3",
            "latest_valid_period": "2026H1",
            "latest_scored_period": "2026H1",
            "update_status": "parse_failed",
            "last_error": {"code": "table_not_found", "message": "未找到监管指标表"},
            "previous_quarterly_period": "2026H1",
            "previous_quarterly_score": 74.0,
        }
        record = build_sector_strict_financial_record(source, annual_anchor="2025A", quarterly_anchor="2026Q3")
        self.assertIsNone(record["quarterly"]["score"])
        self.assertEqual("2026Q3", record["quarterly"]["anchor_period"])
        self.assertIsNone(record["quarterly"]["period"])
        self.assertEqual("sector_annual_only", record["composite"]["mode"])
        self.assertIsNone(record["composite"]["quarterly_score"])
        self.assertEqual(74.0, record["financial_update"]["previous_quarterly_score"])
        self.assertTrue(record["financial_update"]["using_previous_score"])
        self.assertEqual("parse_failed", record["financial_update"]["status"])
    def test_annual_only_source_never_uses_annual_period_as_quarterly_anchor(self) -> None:
        source = {
            "symbol": "000166", "sector_model": "securities",
            "financial_model": {"code": "securities", "label": "证券模型"},
            "annual_period": "2025A",
            "annual_score": {"score": 70.0, "coverage_weight": 90.0, "status": "ready", "dimensions": {}, "red_flags": []},
            "quarterly_score": None,
            "latest_announced_period": "2025A",
            "latest_valid_period": "2025A",
            "latest_scored_period": None,
            "update_status": "not_disclosed",
        }
        record = build_sector_strict_financial_record(source, annual_anchor="2025A", quarterly_anchor="2026Q3")
        self.assertEqual("2026Q3", record["quarterly"]["anchor_period"])
        self.assertIsNone(record["quarterly"]["period"])
        self.assertIsNone(record["quarterly"]["score"])


if __name__ == "__main__":
    unittest.main()
