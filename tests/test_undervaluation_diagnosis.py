import unittest


class DiagnosisTests(unittest.TestCase):
    def test_four_quadrant_keeps_unavailable_valuation_explicit(self):
        from app.undervaluation.diagnosis import classify_quality_margin_quadrant

        self.assertEqual(
            "QUALITY_ELIGIBLE_HAS_MARGIN",
            classify_quality_margin_quadrant({"status": "QUALITY_ELIGIBLE", "eligible": True}, {"status": "HAS_MARGIN"})["quadrant"],
        )
        self.assertEqual(
            "QUALITY_ELIGIBLE_NO_MARGIN",
            classify_quality_margin_quadrant({"status": "QUALITY_ELIGIBLE", "eligible": True}, {"status": "NO_MARGIN"})["quadrant"],
        )
        unavailable = classify_quality_margin_quadrant({"status": "QUALITY_ELIGIBLE", "eligible": True}, {"status": "UNAVAILABLE"})
        self.assertEqual("VALUATION_UNAVAILABLE", unavailable["quadrant"])
        self.assertFalse(unavailable["complete"])


if __name__ == "__main__":
    unittest.main()
