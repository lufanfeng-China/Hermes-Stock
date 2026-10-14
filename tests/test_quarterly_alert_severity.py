import unittest

from app.financial.quarterly_monitor import aggregate_alert_severity, classify_alert_severity


class QuarterlyAlertSeverityTests(unittest.TestCase):
    def test_small_revenue_profit_divergence_is_watch_not_high(self):
        result = classify_alert_severity(
            "revenue_profit_divergence",
            revenue_yoy=6.0,
            ex_net_profit_yoy=-3.3,
        )

        self.assertEqual(result["severity"], "watch")
        self.assertAlmostEqual(result["growth_gap_pct"], 9.3)
        self.assertEqual(result["rule"], "revenue_positive_profit_negative")

    def test_large_revenue_profit_divergence_is_high(self):
        result = classify_alert_severity(
            "revenue_profit_divergence",
            revenue_yoy=6.0,
            ex_net_profit_yoy=-15.0,
        )

        self.assertEqual(result["severity"], "high")
        self.assertAlmostEqual(result["growth_gap_pct"], 21.0)

    def test_extreme_revenue_profit_divergence_is_critical(self):
        result = classify_alert_severity(
            "revenue_profit_divergence",
            revenue_yoy=12.0,
            ex_net_profit_yoy=-35.0,
        )

        self.assertEqual(result["severity"], "critical")

    def test_profit_cash_divergence_requires_large_cash_shortfall_to_be_high(self):
        watch = classify_alert_severity(
            "profit_cash_divergence", ex_net_profit_yoy=6.0, ocf_yoy=-8.0, ttm_ocf=10.0,
        )
        high = classify_alert_severity(
            "profit_cash_divergence", ex_net_profit_yoy=12.0, ocf_yoy=-25.0, ttm_ocf=10.0,
        )
        critical = classify_alert_severity(
            "profit_cash_divergence", ex_net_profit_yoy=15.0, ocf_yoy=-55.0, ttm_ocf=-1.0,
        )

        self.assertEqual(watch["severity"], "watch")
        self.assertEqual(high["severity"], "high")
        self.assertEqual(critical["severity"], "critical")

    def test_working_capital_gap_escalates_at_thirty_and_fifty_points(self):
        self.assertEqual(classify_alert_severity("working_capital_gap", growth_gap_pct=16.0)["severity"], "watch")
        self.assertEqual(classify_alert_severity("working_capital_gap", growth_gap_pct=31.0)["severity"], "high")
        self.assertEqual(classify_alert_severity("working_capital_gap", growth_gap_pct=51.0)["severity"], "critical")

    def test_leverage_and_fcf_use_magnitude_not_only_sign(self):
        self.assertEqual(classify_alert_severity("leverage", debt_change_pct=3.0, fcf_margin_pct=2.0)["severity"], "watch")
        self.assertEqual(classify_alert_severity("leverage", debt_change_pct=8.0, fcf_margin_pct=2.0)["severity"], "high")
        self.assertEqual(classify_alert_severity("leverage", debt_change_pct=15.0, fcf_margin_pct=-1.0)["severity"], "critical")
        self.assertEqual(classify_alert_severity("fcf_margin", fcf_margin_pct=-1.0)["severity"], "watch")
        self.assertEqual(classify_alert_severity("fcf_margin", fcf_margin_pct=-6.0)["severity"], "high")
        self.assertEqual(classify_alert_severity("fcf_margin", fcf_margin_pct=-11.0)["severity"], "critical")

    def test_multiple_medium_alerts_upgrade_and_two_high_alerts_are_critical(self):
        self.assertEqual(aggregate_alert_severity(["watch", "watch"]), "watch")
        self.assertEqual(aggregate_alert_severity(["watch", "watch", "watch"]), "high")
        self.assertEqual(aggregate_alert_severity(["high", "high"]), "critical")


if __name__ == "__main__":
    unittest.main()
