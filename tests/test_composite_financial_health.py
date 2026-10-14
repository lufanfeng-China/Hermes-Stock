import unittest

from app.financial.composite_health import build_composite_financial_health


class CompositeFinancialHealthTests(unittest.TestCase):
    def annual(self, score=75, coverage=100, track="five_year", flags=None):
        return {
            "score": score,
            "coverage_weight": coverage,
            "assessment_track": track,
            "red_flags": flags or [],
        }

    def quarterly(self, score=65, coverage=100, alerts=None):
        return {
            "status": "available",
            "latest_period": "2026Q2",
            "realtime_score": {"score": score, "coverage_weight": coverage},
            "alerts": alerts or [],
        }

    def test_blends_comparable_five_year_and_complete_quarterly_scores(self):
        result = build_composite_financial_health(self.annual(75), self.quarterly(65))

        self.assertEqual(result["mode"], "blended")
        self.assertEqual(result["score"], 72.0)
        self.assertEqual(result["annual_weight"], 0.70)
        self.assertEqual(result["quarterly_weight"], 0.30)
        self.assertEqual(result["quarterly_period"], "2026Q2")
        self.assertEqual(result["risk_overlay"]["status"], "none")
        self.assertEqual(result["display_status"], "stable")

    def test_reduces_partial_quarterly_to_fifteen_percent(self):
        result = build_composite_financial_health(self.annual(75), self.quarterly(65, coverage=85))

        self.assertEqual(result["mode"], "blended")
        self.assertEqual(result["score"], 73.5)
        self.assertEqual(result["annual_weight"], 0.85)
        self.assertEqual(result["quarterly_weight"], 0.15)
        self.assertEqual(result["quarterly_coverage_status"], "partial")

    def test_falls_back_to_annual_base_when_quarterly_score_is_insufficient(self):
        result = build_composite_financial_health(self.annual(75), self.quarterly(None, coverage=80))

        self.assertEqual(result["mode"], "annual_only")
        self.assertEqual(result["score"], 75.0)
        self.assertEqual(result["annual_weight"], 1.0)
        self.assertEqual(result["quarterly_weight"], 0.0)
        self.assertEqual(result["reason"], "quarterly_score_unavailable")

    def test_refuses_to_call_establishment_score_a_five_year_composite(self):
        result = build_composite_financial_health(self.annual(75, track="establishment"), self.quarterly(65))

        self.assertEqual(result["mode"], "quarterly_only")
        self.assertEqual(result["score"], 65.0)
        self.assertEqual(result["reason"], "annual_score_not_five_year_comparable")

    def test_high_severity_quarterly_alert_caps_display_status_without_hidden_penalty(self):
        result = build_composite_financial_health(
            self.annual(90),
            self.quarterly(90, alerts=[{
                "severity": "high",
                "title": "TTM 自由现金流为负",
                "detail": "TTM FCF -12.4 亿元，FCF率 -8.6%",
            }]),
        )

        self.assertEqual(result["score"], 90.0)
        self.assertEqual(result["score_status"], "excellent")
        self.assertEqual(result["display_status"], "watch")
        self.assertEqual(result["risk_overlay"]["status"], "high")
        self.assertTrue(result["risk_overlay"]["message"].startswith("高严重度预警："))
        self.assertIn("TTM 自由现金流为负", result["risk_overlay"]["message"])
        self.assertIn("TTM FCF -12.4 亿元，FCF率 -8.6%", result["risk_overlay"]["message"])

    def test_multiple_high_severity_alerts_mark_composite_as_risk(self):
        result = build_composite_financial_health(
            self.annual(90),
            self.quarterly(90, alerts=[
                {"severity": "high", "title": "TTM 自由现金流为负"},
                {"severity": "high", "title": "收入增长但扣非利润下降"},
            ]),
        )

        self.assertEqual(result["score"], 90.0)
        self.assertEqual(result["display_status"], "risk")
        self.assertEqual(result["risk_overlay"]["status"], "critical")
        self.assertTrue(result["risk_overlay"]["message"].startswith("极高风险：2 项高严重度预警叠加"))

    def test_single_critical_quarterly_alert_marks_composite_as_risk(self):
        result = build_composite_financial_health(
            self.annual(90),
            self.quarterly(90, alerts=[{
                "severity": "critical",
                "title": "TTM 自由现金流深度为负",
                "detail": "TTM FCF Margin -12.0%",
            }]),
        )

        self.assertEqual(result["score"], 90.0)
        self.assertEqual(result["risk_overlay"]["status"], "critical")
        self.assertEqual(result["display_status"], "risk")
        self.assertTrue(result["risk_overlay"]["message"].startswith("极高风险："))
        self.assertIn("TTM FCF Margin -12.0%", result["risk_overlay"]["message"])

    def test_watch_overlay_keeps_quantified_quarterly_alert_detail(self):
        result = build_composite_financial_health(
            self.annual(75),
            self.quarterly(65, alerts=[{
                "severity": "watch",
                "title": "扣非利润改善但经营现金流下降",
                "detail": "扣非利润同比 1096.7%，CFO 同比 -2.9%",
            }]),
        )

        self.assertEqual(result["risk_overlay"]["status"], "watch")
        self.assertTrue(result["risk_overlay"]["message"].startswith("普通关注："))
        self.assertIn("扣非利润同比 1096.7%，CFO 同比 -2.9%", result["risk_overlay"]["message"])


if __name__ == "__main__":
    unittest.main()
