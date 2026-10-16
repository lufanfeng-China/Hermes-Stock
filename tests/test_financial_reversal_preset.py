import unittest
from unittest.mock import patch

from app.financial.reports import (
    build_financial_reversal_indicator,
    build_report_release_price_performance,
    build_report_release_price_trend,
)
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

    def test_stock_analysis_indicator_reuses_strict_reversal_rule(self):
        health = {"score": 55, "assessment_track": "five_year", "coverage_weight": 100, "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"]}
        monitor = {
            "latest_period": "2026Q2", "realtime_score": {"score": 80, "coverage_weight": 100},
            "yoy": {"revenue": 8, "ex_net_profit": 12}, "ttm": {"fcf_margin": 6},
            "dimensions": [{"code": "profitability", "status": "stable"}], "alerts": [],
        }

        result = build_financial_reversal_indicator(health, monitor)

        self.assertTrue(result["matched"])
        self.assertEqual(result["quarterly_period"], "2026Q2")
        self.assertEqual(result["rule_version"], "financial-reversal-v1")

    def test_stock_analysis_indicator_rejects_high_or_critical_financial_alert(self):
        health = {"score": 55, "assessment_track": "five_year", "coverage_weight": 100}
        monitor = {
            "latest_period": "2026Q2", "realtime_score": {"score": 80, "coverage_weight": 100},
            "yoy": {"revenue": 8, "ex_net_profit": 12}, "ttm": {"fcf_margin": 6},
            "dimensions": [{"code": "profitability", "status": "stable"}], "alerts": [{"severity": "high"}],
        }

        self.assertFalse(build_financial_reversal_indicator(health, monitor)["matched"])

    def test_report_release_return_uses_next_trading_day_open_and_raw_current_price(self):
        result = build_report_release_price_performance(
            announce_date="20260812",
            daily_bars=[
                {"trading_day": "2026-08-12", "open": 9.8},
                {"trading_day": "2026-08-13", "open": 10.0},
                {"trading_day": "2026-08-14", "open": 10.5},
            ],
            current_price=11.5,
            current_price_as_of="2026-08-14",
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["basis"], "raw_unadjusted")
        self.assertEqual(result["entry_trading_day"], "2026-08-13")
        self.assertEqual(result["entry_open"], 10.0)
        self.assertEqual(result["current_price"], 11.5)
        self.assertEqual(result["return_pct"], 15.0)

    def test_report_release_trend_marks_entry_high_low_and_current_raw_prices(self):
        trend = build_report_release_price_trend(
            performance={"available": True, "entry_trading_day": "2026-08-13", "entry_open": 10.0, "current_price": 11.5, "current_price_as_of": "2026-08-14"},
            daily_bars=[
                {"trading_day": "2026-08-12", "open": 9.8, "high": 10.1, "low": 9.7, "close": 10.0},
                {"trading_day": "2026-08-13", "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.4},
                {"trading_day": "2026-08-14", "open": 10.5, "high": 12.0, "low": 10.2, "close": 11.5},
            ],
        )

        self.assertTrue(trend["available"])
        self.assertEqual([point["trading_day"] for point in trend["points"]], ["2026-08-13", "2026-08-14"])
        self.assertEqual(trend["markers"]["entry_open"], {"trading_day": "2026-08-13", "price": 10.0})
        self.assertEqual(trend["markers"]["high"], {"trading_day": "2026-08-14", "price": 12.0})
        self.assertEqual(trend["markers"]["low"], {"trading_day": "2026-08-13", "price": 9.9})
        self.assertEqual(trend["markers"]["current"], {"trading_day": "2026-08-14", "price": 11.5})

    def test_report_release_return_rejects_missing_t_plus_one_open_without_price_fallback(self):
        result = build_report_release_price_performance(
            announce_date="20260812", daily_bars=[{"trading_day": "2026-08-12", "open": 9.8}],
            current_price=11.5, current_price_as_of="2026-08-12",
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "t_plus_one_open_unavailable")

    def test_composite_score_range_filters_api_rows(self):
        high = self._row(symbol="000001", composite_total=80, annual_dimensions={}, quarterly_dimensions={})
        low = self._row(symbol="000002", composite_total=40, annual_dimensions={}, quarterly_dimensions={})
        with patch("app.stock_filter._universe", return_value=([high, low], "2026-10-15")):
            response = filter_response({"composite_total_min": ["70"], "page": ["1"], "page_size": ["50"]})
        self.assertTrue(response["ok"])
        self.assertEqual([row["symbol"] for row in response["rows"]], ["000001"])
