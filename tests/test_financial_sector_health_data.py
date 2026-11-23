from app.financial.sector_health_data import _first_finite, _profit


def test_zero_and_negative_values_are_not_treated_as_missing():
    assert _first_finite({"roe": 0.0, "fallback": 8.0}, "roe", "fallback") == 0.0
    assert _first_finite({"roe": -3.5, "fallback": 8.0}, "roe", "fallback") == -3.5
    assert _profit({"归属于母公司所有者的净利润": 0.0, "净利润": 10.0}) == 0.0
    assert _profit({"归属于母公司所有者的净利润": -5.0, "净利润": 10.0}) == -5.0
