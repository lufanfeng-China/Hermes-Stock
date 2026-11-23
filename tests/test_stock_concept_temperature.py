from unittest.mock import patch
from pathlib import Path


def _fixture():
    return {
        "as_of_date": "2026-11-19",
        "price_basis": "tdx_export_qfq",
        "temperature_basis": "absolute_median_return_v1",
        "windows": {"10": {
            "concepts": [
                {"concept_code": "A", "concept_name": "芯片", "temperature": 4, "temperature_label": "热门", "temperature_previous": 2, "temperature_change": 2, "temperature_trend": "warming", "temperature_trend_label": "升温"},
                {"concept_code": "B", "concept_name": "光伏", "temperature": 1, "temperature_label": "偏冷", "temperature_previous": 3, "temperature_change": -2, "temperature_trend": "cooling", "temperature_trend_label": "退坡"},
                {"concept_code": "C", "concept_name": "机器人", "temperature": 5, "temperature_label": "极热", "temperature_previous": 4, "temperature_change": 1, "temperature_trend": "warming", "temperature_trend_label": "升温"},
            ],
            "members": {
                "A": [{"symbol": "688019"}, {"symbol": "000001"}],
                "B": [{"symbol": "688019"}],
                "C": [{"symbol": "300001"}],
            },
        }},
    }


def test_stock_concept_temperature_returns_only_memberships_with_change_evidence():
    from app.api.concept_temperature import handle_stock_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        result = handle_stock_concept_temperature("market=sh&symbol=688019&window=10")

    assert result["ok"] is True
    assert result["as_of_date"] == "2026-11-19"
    assert [row["concept_name"] for row in result["concepts"]] == ["芯片", "光伏"]
    assert result["concepts"][0]["temperature_previous"] == 2
    assert result["concepts"][0]["temperature_change"] == 2
    assert result["concepts"][0]["temperature_trend"] == "warming"
    assert result["concepts"][1]["temperature_trend_label"] == "退坡"


def test_stock_concept_temperature_validates_symbol_and_window():
    from app.api.concept_temperature import handle_stock_concept_temperature

    assert handle_stock_concept_temperature("symbol=x&window=10")["status"] == 400
    assert handle_stock_concept_temperature("symbol=688019&window=7")["status"] == 400


def test_stock_concept_temperature_is_wired_to_http_handler():
    source = (Path(__file__).resolve().parents[1] / "app" / "handler.py").read_text(encoding="utf-8")
    assert 'parsed.path == "/api/stock-concept-temperature"' in source
    assert "def handle_stock_concept_temperature(self, query: str)" in source
