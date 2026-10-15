import unittest
from unittest.mock import patch

from app.stock_filter import filter_response, matches_financial_reversal


class FinancialReversalPresetTest(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "annual_total": 55.0,
            "annual_assessment_track": "five_year",
            "annual_coverage_weight": 100.0,
            "quarterly_total": 80.0,
            "quarterly_coverage_weight": 100.0,
            "quarterly_revenue_yoy": 8.0,
            "quarterly_ex_net_profit_yoy": 12.0,
            "quarterly_ttm_fcf_margin": 6.0,
            "quarterly_profitability_status": "stable",
            "quarterly_high_or_critical_alert": False,
        }
        row.update(overrides)
        return row

    def test_standard_reversal_with_quality_confirmation_matches(self):
        self.assertTrue(matches_financial_reversal(self._row()))

    def test_negative_ttm_free_cash_flow_is_not_a_financial_reversal(self):
        self.assertFalse(matches_financial_reversal(self._row(quarterly_ttm_fcf_margin=-0.1)))

    def test_score_jump_without_positive_profit_growth_is_not_a_financial_reversal(self):
        self.assertFalse(matches_financial_reversal(self._row(quarterly_ex_net_profit_yoy=0.0)))

    def test_missing_quality_evidence_is_not_coerced_to_a_match(self):
        self.assertFalse(matches_financial_reversal(self._row(quarterly_revenue_yoy=None)))

    def test_preset_parameter_applies_reversal_rule_before_pagination(self):
        match = self._row(symbol="000001", stock_name="示例反转", rps_total=100, annual_dimensions={}, quarterly_dimensions={})
        reject = self._row(symbol="000002", stock_name="示例伪反转", rps_total=200, quarterly_ttm_fcf_margin=-1, annual_dimensions={}, quarterly_dimensions={})
        with patch("app.stock_filter._universe", return_value=([match, reject], "2026-10-15")):
            response = filter_response({"preset": ["financial_reversal"], "page": ["1"], "page_size": ["50"], "sort": ["rps_total"]})
        self.assertTrue(response["ok"])
        self.assertEqual(response["total_matched"], 1)
        self.assertEqual(response["rows"][0]["symbol"], "000001")

    def test_composite_score_range_filters_api_rows(self):
        high = self._row(symbol="000001", composite_total=80, annual_dimensions={}, quarterly_dimensions={})
        low = self._row(symbol="000002", composite_total=40, annual_dimensions={}, quarterly_dimensions={})
        with patch("app.stock_filter._universe", return_value=([high, low], "2026-10-15")):
            response = filter_response({"composite_total_min": ["70"], "page": ["1"], "page_size": ["50"]})
        self.assertTrue(response["ok"])
        self.assertEqual([row["symbol"] for row in response["rows"]], ["000001"])
