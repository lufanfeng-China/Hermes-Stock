from pathlib import Path
from unittest.mock import patch

from app.stock_filter import _financial_score_sort_group, filter_response


def test_financial_score_sort_group_separates_model_and_report_period():
    bank = {"financial_model_code": "bank", "annual_period": "2025A", "quarterly_period": "2026Q3"}
    securities = {"financial_model_code": "securities", "annual_period": "2025A", "quarterly_period": "2026Q3"}
    general = {"financial_model_code": "general", "annual_period": "2025A", "quarterly_period": "2026Q3"}
    older_bank = {"financial_model_code": "bank", "annual_period": "2025A", "quarterly_period": "2026H1"}
    older_annual_bank = {"financial_model_code": "bank", "annual_period": "2024A", "quarterly_period": "2026Q3"}

    assert _financial_score_sort_group(general, "annual_total") != _financial_score_sort_group(bank, "annual_total")
    assert _financial_score_sort_group(bank, "annual_total") != _financial_score_sort_group(securities, "annual_total")
    assert _financial_score_sort_group(bank, "quarterly_total") != _financial_score_sort_group(older_bank, "quarterly_total")
    assert _financial_score_sort_group(bank, "composite_total") != _financial_score_sort_group(older_annual_bank, "composite_total")
    assert _financial_score_sort_group(bank, "pe_ttm") == ()


def test_financial_score_range_requires_one_model_and_ui_exposes_model_filter():
    response = filter_response({"annual_total_min": ["70"]})
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_filter"
    assert "financial_model_code" in response["error"]["message"]
    html = (Path(__file__).parents[1] / "web" / "stock-filter.html").read_text(encoding="utf-8")
    assert 'select name="financial_model_code"' in html


def test_historical_query_rejects_current_only_sector_models():
    response = filter_response({
        "as_of_date": ["2026-10-15"],
        "financial_model_code": ["bank"],
    })
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_filter"
    assert "historical" in response["error"]["message"]


def test_financial_score_range_rejects_mixed_periods_and_accepts_explicit_period():
    rows = [
        {"market": "sz", "symbol": "000001", "financial_model_code": "general",
         "annual_period": "2025A", "annual_total": 80, "annual_dimensions": {}, "quarterly_dimensions": {}},
        {"market": "sz", "symbol": "000002", "financial_model_code": "general",
         "annual_period": "2024A", "annual_total": 90, "annual_dimensions": {}, "quarterly_dimensions": {}},
    ]
    with patch("app.stock_filter._universe", return_value=(rows, "2026-11-20")):
        rejected = filter_response({"annual_total_min": ["70"]})
        accepted = filter_response({"annual_total_min": ["70"], "annual_period": ["2025A"]})
    assert rejected["ok"] is False
    assert "annual_period" in rejected["error"]["message"]
    assert accepted["ok"] is True
    assert [row["symbol"] for row in accepted["rows"]] == ["000001"]


def test_composite_range_requires_and_filters_both_report_periods():
    rows = [
        {"market": "sz", "symbol": "000001", "financial_model_code": "general",
         "annual_period": "2025A", "quarterly_period": "2026Q3", "composite_total": 80,
         "annual_dimensions": {}, "quarterly_dimensions": {}},
        {"market": "sz", "symbol": "000002", "financial_model_code": "general",
         "annual_period": "2025A", "quarterly_period": "2026H1", "composite_total": 85,
         "annual_dimensions": {}, "quarterly_dimensions": {}},
    ]
    with patch("app.stock_filter._universe", return_value=(rows, "2026-11-20")):
        rejected = filter_response({"composite_total_min": ["70"], "annual_period": ["2025A"]})
        accepted = filter_response({
            "composite_total_min": ["70"], "annual_period": ["2025A"],
            "quarterly_period": ["2026Q3"],
        })
    assert rejected["ok"] is False
    assert "quarterly_period" in rejected["error"]["message"]
    assert accepted["ok"] is True
    assert [row["symbol"] for row in accepted["rows"]] == ["000001"]


def test_financial_period_selectors_are_exposed_in_ui():
    html = (Path(__file__).parents[1] / "web" / "stock-filter.html").read_text(encoding="utf-8")
    assert 'input name="annual_period"' in html
    assert 'input name="quarterly_period"' in html
