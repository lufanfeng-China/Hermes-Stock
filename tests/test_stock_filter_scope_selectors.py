from unittest.mock import patch

from app.stock_filter import filter_response
from app.stock_filter_scope import build_scope_index, scope_options_response


def fixture_index():
    industries = [
        {"market": "sz", "symbol": "000001", "industry_level_2_code": "X1", "industry_level_2_name": "半导体"},
        {"market": "sz", "symbol": "000002", "industry_level_2_code": "X1", "industry_level_2_name": "半导体"},
        {"market": "sh", "symbol": "600001", "industry_level_2_code": "X2", "industry_level_2_name": "软件开发"},
    ]
    concepts = [
        {"concept_code": "C1", "concept_name": "AI算力", "symbol": "000001"},
        {"concept_code": "C1", "concept_name": "AI算力", "symbol": "600001"},
        {"concept_code": "C2", "concept_name": "机器人", "symbol": "000002"},
    ]
    temperature = {"as_of_date": "2026-11-17", "windows": {"10": {"concepts": [
        {"concept_code": "C1", "concept_name": "AI算力", "temperature": 4, "temperature_label": "热门"},
        {"concept_code": "C2", "concept_name": "机器人", "temperature": 3, "temperature_label": "升温"},
    ]}}}
    industry_temperature = {"as_of_date": "2026-11-17", "windows": {"10": {"concepts": [
        {"concept_code": "X1", "concept_name": "半导体", "temperature": 4, "temperature_label": "热门"},
        {"concept_code": "X2", "concept_name": "软件开发", "temperature": 2, "temperature_label": "中性偏弱"},
    ]}}}
    return build_scope_index(industries, concepts, temperature,
                             industry_temperature_payload=industry_temperature,
                             temperature_window=10)


def rows():
    return [
        {"market": "sz", "symbol": "000001", "industry_level_2_code": "X1", "rps_total": 100, "annual_dimensions": {}, "quarterly_dimensions": {}},
        {"market": "sz", "symbol": "000002", "industry_level_2_code": "X1", "rps_total": 99, "annual_dimensions": {}, "quarterly_dimensions": {}},
        {"market": "sh", "symbol": "600001", "industry_level_2_code": "X2", "rps_total": 98, "annual_dimensions": {}, "quarterly_dimensions": {}},
    ]


def call(params):
    with patch("app.stock_filter._universe", return_value=(rows(), "2026-11-17")), \
         patch("app.stock_filter._read_pe_percentile_snapshot", return_value={}), \
         patch("app.stock_filter.stock_scope_index", return_value=fixture_index()):
        return filter_response(params)


def test_catalog_exposes_auditable_options_and_temperature_date():
    payload = scope_options_response(index=fixture_index())
    assert payload["ok"] is True
    assert payload["concept_temperature_as_of"] == "2026-11-17"
    assert payload["industry_temperature_as_of"] == "2026-11-17"
    assert payload["industry_temperature_window"] == 10
    assert payload["concept_temperature_window"] == 10
    assert [(row["code"], row["name"], row["member_count"]) for row in payload["industries"]] == [
        ("X1", "半导体", 2),
        ("X2", "软件开发", 1),
    ]
    assert payload["concepts"][0]["temperature_label"] == "热门"
    assert payload["industries"][0]["temperature_label"] == "热门"


def test_same_category_is_or_and_cross_category_is_and_before_pagination():
    result = call({"industry_l2_codes": ["X1,X2"], "concept_codes": ["C1,C2"],
                   "concept_temperature_levels": ["4"]})
    assert result["ok"] is True
    assert [row["symbol"] for row in result["rows"]] == ["000001", "600001"]
    assert result["total_universe"] == 2
    assert result["scope_selection"]["effective_concept_codes"] == ["C1"]


def test_temperature_without_explicit_concepts_uses_all_matching_concepts():
    result = call({"concept_temperature_levels": ["3"]})
    assert result["ok"] is True
    assert [row["symbol"] for row in result["rows"]] == ["000002"]


def test_industry_temperature_intersects_explicit_industries_before_pagination():
    result = call({"industry_l2_codes": ["X1,X2"], "industry_temperature_levels": ["4"]})
    assert result["ok"] is True
    assert [row["symbol"] for row in result["rows"]] == ["000001", "000002"]
    assert result["scope_selection"]["effective_industry_codes"] == ["X1"]


def test_industry_temperature_without_explicit_industry_uses_all_matching_industries():
    result = call({"industry_temperature_levels": ["2"]})
    assert result["ok"] is True
    assert [row["symbol"] for row in result["rows"]] == ["600001"]


def test_historical_date_rejects_current_concept_scope():
    result = filter_response({"as_of_date": ["2025-10-16"], "concept_codes": ["C1"]})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_filter"
    assert "历史日期" in result["error"]["message"]


def test_historical_date_rejects_current_industry_temperature():
    result = filter_response({"as_of_date": ["2025-10-16"], "industry_temperature_levels": ["4"]})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_filter"
    assert "行业温度" in result["error"]["message"]


def test_invalid_temperature_level_is_rejected():
    result = filter_response({"concept_temperature_levels": ["9"]})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_filter"
