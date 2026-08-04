import unittest

from app.concept_theme_clusters import build_theme_clusters, primary_concept_for_stock


class ConceptThemeClustersTest(unittest.TestCase):
    def setUp(self):
        self.mapping = [
            {"concept_code": "A", "concept_name": "甲", "symbol": "000001"},
            {"concept_code": "A", "concept_name": "甲", "symbol": "000002"},
            {"concept_code": "A", "concept_name": "甲", "symbol": "000003"},
            {"concept_code": "B", "concept_name": "乙", "symbol": "000001"},
            {"concept_code": "B", "concept_name": "乙", "symbol": "000002"},
            {"concept_code": "B", "concept_name": "乙", "symbol": "000003"},
            {"concept_code": "B", "concept_name": "乙", "symbol": "000004"},
            {"concept_code": "C", "concept_name": "丙", "symbol": "000099"},
        ]

    def test_jaccard_clusters_and_rejects_bad_threshold(self):
        result = build_theme_clusters(self.mapping, .60)
        self.assertEqual(result["concept_to_cluster"]["A"], result["concept_to_cluster"]["B"])
        self.assertNotEqual(result["concept_to_cluster"]["A"], result["concept_to_cluster"]["C"])
        with self.assertRaises(ValueError):
            build_theme_clusters(self.mapping, 0)

    def test_primary_prefers_temperature_then_heat_then_breadth_then_rank(self):
        clusters = build_theme_clusters(self.mapping)
        rows = [
            {"symbol": "000001", "concept_code": "A", "temperature": 5, "heat_score": 88, "breadth_pct": 90, "concept_rank": 2},
            {"symbol": "000001", "concept_code": "B", "temperature": 5, "heat_score": 88, "breadth_pct": 91, "concept_rank": 1},
            {"symbol": "000001", "concept_code": "C", "temperature": 4, "heat_score": 99, "breadth_pct": 99, "concept_rank": 1},
        ]
        primary = primary_concept_for_stock("000001", rows, clusters["concept_to_cluster"])
        self.assertEqual(primary["concept_code"], "B")
        self.assertEqual(primary["theme_cluster_id"], clusters["concept_to_cluster"]["B"])


if __name__ == "__main__":
    unittest.main()
