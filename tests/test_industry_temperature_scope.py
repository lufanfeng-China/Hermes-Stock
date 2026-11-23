"""概念温度页的「概念 / 二级行业」口径切换。"""
import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location("build_concept_temperature", ROOT / "scripts" / "build_concept_temperature.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scopes_carry_their_own_output_and_min_members():
    builder = _builder()
    assert builder.SCOPES["concept"]["min_members"] == 10
    assert builder.SCOPES["industry"]["min_members"] == 3
    assert builder.SCOPES["industry"]["out_path"].name == "dataset_industry_temperature_current.json"
    assert builder.SCOPES["concept"]["out_path"].name == "dataset_concept_temperature_current.json"


def test_industry_mapping_is_isomorphic_to_the_concept_mapping():
    import json

    builder = _builder()
    rows = builder.load_industry_mapping()
    assert rows, "行业映射为空"
    assert {"concept_code", "concept_name", "symbol", "stock_name"} <= set(rows[0])
    # 不写死行业个数：以当前行业映射快照为准（会随通达信行业分类更新而变化）
    snapshot = json.loads((ROOT / "data" / "derived" / "datasets" / "final"
                           / "snapshot_stock_industry_membership.json").read_text(encoding="utf-8"))
    expected = {row["industry_level_2_code"] for row in snapshot}
    assert {row["concept_code"] for row in rows} == expected
    # 每只股票在二级行业里只能出现一次（全覆盖划分）
    symbols = [row["symbol"] for row in rows]
    assert len(symbols) == len(set(symbols))


def _fixture(scope_label="二级行业"):
    return {"scope": "industry", "unit_label": scope_label, "as_of_date": "2026-10-30",
            "price_basis": "tdx_export_qfq", "temperature_basis": "absolute_median_return_v1", "min_members": 3,
            "windows": {"10": {"concepts": [{"concept_code": "X5001", "concept_name": "全国性银行",
                                            "temperature": 3, "temperature_trend": "cooling",
                                            "temperature_streak_days": 4}],
                              "members": {"X5001": [{"symbol": "000001", "stock_name": "平安银行"}]}}},
            "heat_history": {}}


def test_api_accepts_scope_and_echoes_it():
    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        result = handle_concept_temperature("scope=industry&window=10")
    assert result["ok"] is True
    assert result["scope"] == "industry"
    assert result["scope_label"] == "二级行业"
    assert result["unit_label"] == "二级行业"
    assert result["min_members"] == 3
    assert result["concepts"][0]["concept_name"] == "全国性银行"


def test_api_defaults_to_concept_scope():
    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture("概念")):
        result = handle_concept_temperature("window=10")
    assert result["scope"] == "concept"


def test_stock_filter_scope_preserves_current_temperature_change_evidence():
    from app.stock_filter_scope import build_scope_index

    index = build_scope_index(
        [{'market': 'sz', 'symbol': '000001', 'industry_level_2_code': 'I1',
          'industry_level_2_name': '医疗器械'}],
        [], {},
        industry_temperature_payload={'as_of_date': '2026-11-19', 'windows': {'10': {'concepts': [{
            'concept_code': 'I1', 'concept_name': '医疗器械', 'temperature': 5,
            'temperature_label': '极热', 'temperature_previous': 4,
            'temperature_change': 1, 'temperature_trend': 'warming',
            'temperature_trend_label': '升温', 'temperature_previous_gap_days': 1,
        }]}}},
    )
    evidence = index['industry_temperature']['I1']
    assert evidence['temperature_previous'] == 4
    assert evidence['temperature_previous_label'] == '热门'
    assert evidence['temperature_change'] == 1
    assert evidence['temperature_trend_label'] == '升温'


@pytest.mark.parametrize("query", ["scope=etf&window=10"])
def test_unknown_scope_is_rejected(query):
    from app.api.concept_temperature import handle_concept_temperature

    result = handle_concept_temperature(query)
    assert result["ok"] is False and result["status"] == 400


def test_members_endpoint_honours_scope():
    from app.api.concept_temperature import handle_concept_temperature_members

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        result = handle_concept_temperature_members("scope=industry&window=10&concept_code=X5001")
    assert result["ok"] is True and result["scope"] == "industry"
    assert result["stocks"][0]["symbol"] == "000001"


def test_members_endpoint_enriches_stock_filter_metrics_from_same_day_snapshot():
    from app.api.concept_temperature import handle_concept_temperature_members

    metrics = {"sz:000001": {
        "mrs_score": 88.2, "turnover_percentile_1y": 76.4, "pe_ttm": 12.3,
        "annual_total": 81.0, "annual_period": "2025A",
        "quarterly_total": 73.0, "quarterly_period": "2026Q3",
    }}
    with patch("app.api.concept_temperature._load", return_value=_fixture()), \
         patch("app.api.concept_temperature._stock_metric_map", return_value=metrics):
        result = handle_concept_temperature_members("scope=industry&window=10&concept_code=X5001")

    stock = result["stocks"][0]
    assert stock["mrs_score"] == 88.2
    assert stock["turnover_percentile_1y"] == 76.4
    assert stock["pe_ttm"] == 12.3
    assert stock["annual_total"] == 81.0 and stock["annual_period"] == "2025A"
    assert stock["quarterly_total"] == 73.0 and stock["quarterly_period"] == "2026Q3"


def test_missing_industry_dataset_says_how_to_build_it():
    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature.DATASET_PATHS", {"concept": ROOT / "nope.json", "industry": ROOT / "nope.json"}):
        result = handle_concept_temperature("scope=industry&window=10")
    assert result["ok"] is False
    assert "--scope industry" in result["error"]


def test_page_has_a_scope_switch_and_sends_it_everywhere():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")

    assert 'id="scope"' in html and '<option value="industry">二级行业</option>' in html
    assert 'id="unit-header"' in html
    assert "scope= ' + encodeURIComponent(scope)" in js.replace("scope=' +", "scope= ' +")
    assert js.count("encodeURIComponent(scope)") >= 2      # 列表 / 成分
    assert "var requestedScope = scope" in js and "encodeURIComponent(requestedScope)" in js  # 趋势冻结点击时的口径
    assert "function applyScope()" in js


def test_fill_member_names_covers_blank_names():
    from app.concept_temperature import fill_member_names

    rows = [{"symbol": "600928", "stock_name": ""},
            {"symbol": "000554", "stock_name": "   "},
            {"symbol": "600519", "stock_name": "贵州茅台"}]
    filled = fill_member_names(rows)
    assert filled[0]["stock_name"] == "西安银行"
    assert filled[1]["stock_name"] == "泰山石油"
    assert filled[2]["stock_name"] == "贵州茅台"      # 已有名称不被覆盖


def test_industry_mapping_carries_names_so_future_builds_are_complete():
    rows = _builder().load_industry_mapping()
    blank = [row for row in rows if not row["stock_name"].strip()]
    assert not blank, f"行业映射仍有 {len(blank)} 行没有名称，例如 {blank[0]}"


def test_members_api_returns_names_for_industry_scope():
    from app.api.concept_temperature import handle_concept_temperature_members

    payload = {"unit_label": "二级行业", "as_of_date": "2026-10-30", "price_basis": "tdx_export_qfq", "temperature_basis": "absolute_median_return_v1",
               "min_members": 3,
               "windows": {"10": {"concepts": [{"concept_code": "X5001", "concept_name": "全国性银行"}],
                                  "members": {"X5001": [{"symbol": "600928", "stock_name": "",
                                                         "return_pct": 1.0, "latest_close": 3.9,
                                                         "volume_ratio_5d_20d": 2.1}]}}}}
    with patch("app.api.concept_temperature._load", return_value=payload):
        result = handle_concept_temperature_members("scope=industry&window=10&concept_code=X5001")
    assert result["stocks"][0]["stock_name"] == "西安银行"
