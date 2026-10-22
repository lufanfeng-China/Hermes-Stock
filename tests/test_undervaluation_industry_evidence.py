import unittest


class IndustryEvidenceTests(unittest.TestCase):
    def test_requires_positive_pe_and_ps_samples_and_returns_both_percentiles(self):
        from app.undervaluation.industry_evidence import evaluate_industry_evidence

        rows = [
            {"market": "sh", "symbol": "600001", "pe_ttm": 10.0, "ps_ttm": 1.0},
            *[{"market": "sh", "symbol": f"6000{i:02d}", "pe_ttm": 20.0 + i, "ps_ttm": 2.0 + i} for i in range(2, 11)],
            {"market": "sh", "symbol": "600099", "pe_ttm": -5.0, "ps_ttm": 0.5},
        ]
        result = evaluate_industry_evidence(
            market="sh", symbol="600001", industry_snapshot={"sample_status": "ok", "member_valuation_rows": rows},
        )

        self.assertEqual("AVAILABLE", result["status"])
        self.assertEqual(10, result["pe_sample_size"])
        self.assertEqual(10, result["ps_sample_size"])
        self.assertLessEqual(result["pe_percentile"], 30.0)
        self.assertLessEqual(result["ps_percentile"], 30.0)


if __name__ == "__main__":
    unittest.main()
