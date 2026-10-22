import unittest


class MarginEvidenceTests(unittest.TestCase):
    def test_requires_both_industry_and_own_history_pe_ps_discounts(self):
        from app.undervaluation.valuation_gate import evaluate_margin_evidence

        result = evaluate_margin_evidence(
            quality={"status": "QUALITY_ELIGIBLE", "eligible": True},
            industry={
                "status": "AVAILABLE",
                "pe_percentile": 30.0,
                "ps_percentile": 29.9,
                "effective_sample_count": 12,
            },
            history={
                "status": "AVAILABLE",
                "years": 3,
                "pe_valid_trading_days": 500,
                "ps_valid_trading_days": 500,
                "pe_percentile": 30.0,
                "ps_percentile": 25.0,
            },
        )

        self.assertEqual("HAS_MARGIN", result["status"])
        self.assertTrue(result["has_margin"])
        self.assertEqual([], result["reasons"])


if __name__ == "__main__":
    unittest.main()
