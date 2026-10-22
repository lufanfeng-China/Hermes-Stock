import unittest


class QualityGateTests(unittest.TestCase):
    def test_allows_five_year_annual_health_with_score_and_coverage_at_threshold(self):
        from app.undervaluation.quality_gate import evaluate_quality_gate

        result = evaluate_quality_gate({
            "assessment_track": "five_year",
            "score": 70,
            "coverage_weight": 85,
            "red_flags": [],
            "red_flag_coverage": {"evaluated": 10, "total": 10, "unavailable": []},
        })

        self.assertEqual("QUALITY_ELIGIBLE", result["status"])
        self.assertTrue(result["eligible"])
        self.assertEqual([], result["reasons"])
    def test_rejects_high_or_critical_annual_red_flag_even_with_passing_score(self):
        from app.undervaluation.quality_gate import evaluate_quality_gate

        result = evaluate_quality_gate({
            "assessment_track": "five_year",
            "score": 92,
            "coverage_weight": 100,
            "red_flags": [{"code": "fcf_two_year_negative", "severity": "high"}],
            "red_flag_coverage": {"evaluated": 10, "total": 10, "unavailable": []},
        })

        self.assertEqual("NOT_QUALITY_ELIGIBLE", result["status"])
        self.assertFalse(result["eligible"])
        self.assertEqual(["annual_high_or_critical_red_flag"], result["reasons"])
    def test_withholds_eligibility_when_a_core_red_flag_family_is_unavailable(self):
        from app.undervaluation.quality_gate import evaluate_quality_gate

        result = evaluate_quality_gate({
            "assessment_track": "five_year",
            "score": 90,
            "coverage_weight": 90,
            "red_flags": [],
            "red_flag_coverage": {
                "evaluated": 9,
                "total": 10,
                "unavailable": ["debt_ratio_rising"],
            },
        })

        self.assertEqual("INSUFFICIENT_EVIDENCE", result["status"])
        self.assertFalse(result["eligible"])
        self.assertEqual(["core_red_flag_family_unavailable:leverage_solvency"], result["reasons"])


if __name__ == "__main__":
    unittest.main()
