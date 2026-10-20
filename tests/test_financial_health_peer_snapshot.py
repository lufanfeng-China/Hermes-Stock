import json
import tempfile
import unittest
from pathlib import Path


class FinancialHealthPeerSnapshotTests(unittest.TestCase):
    def test_snapshot_filters_industry_and_preserves_annual_and_quarterly_contract(self):
        from app.financial.health_peer_snapshot import build_industry_health_peer_response

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            path.write_text(json.dumps({"stocks": {
                "sh:600001": {"annual": {"score": 80, "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"], "assessment_track": "five_year", "coverage_weight": 100, "dimensions": {"growth_quality": 16}}, "quarterly": {"score": 72, "period": "2026Q2", "coverage_weight": 90, "dimensions": {"growth_quality": 14}}, "latest_available_quarterly": {"score": 72, "period": "2026Q2", "coverage_weight": 90, "dimensions": {"growth_quality": 14}, "reason": None}},
                "sh:600002": {"annual": {"score": 70, "periods": ["2021A"], "assessment_track": "establishment", "coverage_weight": 80, "dimensions": {}}, "quarterly": {"score": None, "period": None, "coverage_weight": 0, "dimensions": {}}, "latest_available_quarterly": {"score": 66, "period": "2026Q1", "coverage_weight": 85, "dimensions": {"growth": 11}, "reason": None}},
                "bj:920001": {"annual": {"score": 95, "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"], "assessment_track": "five_year", "coverage_weight": 100, "dimensions": {}}, "quarterly": {"score": 99, "period": "2026Q3", "coverage_weight": 100, "dimensions": {}}, "latest_available_quarterly": {"score": 99, "period": "2026Q3", "coverage_weight": 100, "dimensions": {}, "reason": None}},
                "2:920002": {"annual": {"score": 95, "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"], "assessment_track": "five_year", "coverage_weight": 100, "dimensions": {}}, "quarterly": {"score": 99, "period": "2026Q3", "coverage_weight": 100, "dimensions": {}}, "latest_available_quarterly": {"score": 99, "period": "2026Q3", "coverage_weight": 100, "dimensions": {}, "reason": None}},
            }}), encoding="utf-8")
            response = build_industry_health_peer_response("sh", "600001", snapshot_path=path, industry_map={("sh", "600001"): ("计算机应用", "软件服务"), ("sh", "600002"): ("计算机应用", "软件服务"), ("bj", "920001"): ("计算机应用", "软件服务"), ("2", "920002"): ("计算机应用", "软件服务")}, names={("sh", "600001"): "甲", ("sh", "600002"): "乙", ("bj", "920001"): "北交所样本", ("2", "920002"): "北交所市场码样本"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["industry_level_2"], "计算机应用")
        self.assertEqual(len(response["rows"]), 2)
        self.assertTrue({row["market"] for row in response["rows"]}.isdisjoint({"bj", "2"}))
        self.assertEqual(response["rows"][0]["annual"]["score"], 80)
        self.assertEqual(response["rows"][0]["quarterly"]["period"], "2026Q2")
        self.assertEqual(response["rows"][1]["latest_available_quarterly"]["period"], "2026Q1")
        self.assertEqual(response["rows"][1]["latest_available_quarterly"]["score"], 66)
        self.assertEqual(response["rows"][1]["latest_available_quarterly"]["dimensions"]["growth_quality"], 11)
        self.assertTrue(response["rows"][0]["is_current_stock"])
