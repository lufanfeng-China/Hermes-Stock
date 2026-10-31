"""01 股票范围：先锁定股票池，再套用其它条件。"""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.stock_filter import board_of, csi300_codes, filter_response, matches_scope

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("market, symbol, board", [
    ("sh", "600519", "main"),
    ("sh", "601398", "main"),
    ("sh", "603259", "main"),
    ("sh", "605499", "main"),
    ("sz", "000001", "main"),
    ("sz", "001979", "main"),
    ("sz", "002594", "main"),
    ("sz", "003816", "main"),
    ("sz", "300760", "chinext"),
    ("sz", "301269", "chinext"),
    ("sh", "688981", "star"),
    ("sh", "689009", "star"),
    ("bj", "920000", "bj"),
])
def test_board_classification(market, symbol, board):
    assert board_of(market, symbol) == board


def test_csi300_list_is_the_published_300():
    codes = csi300_codes()
    assert len(codes) == 300
    assert "600519" in codes and "300760" in codes


def test_scope_membership():
    assert matches_scope("sh", "600519", "all")
    assert matches_scope("sh", "600519", "csi300")
    assert not matches_scope("bj", "920000", "csi300")
    assert matches_scope("sz", "000001", "main_board")
    assert not matches_scope("sz", "300760", "main_board")
    assert matches_scope("sz", "300760", "chinext")
    assert not matches_scope("sh", "688981", "chinext")
    assert matches_scope("sh", "688981", "star")
    assert not matches_scope("sh", "600519", "star")


def test_dual_creative_is_star_plus_chinext():
    assert matches_scope("sh", "688981", "dual_creative")   # 科创板
    assert matches_scope("sz", "300760", "dual_creative")   # 创业板
    assert matches_scope("sz", "301269", "dual_creative")
    assert matches_scope("sh", "689009", "dual_creative")
    assert not matches_scope("sh", "600519", "dual_creative")   # 沪主板
    assert not matches_scope("sz", "002594", "dual_creative")   # 深主板
    assert not matches_scope("bj", "920000", "dual_creative")   # 北交所


def row(market, symbol, ratio):
    return dict(market=market, symbol=symbol, rps_total=1, annual_dimensions={},
                quarterly_dimensions={}, eps_ratio_5y=ratio)


UNIVERSE = [
    row("sh", "600519", 80.0),   # 主板 + 沪深300
    row("sh", "688981", 90.0),   # 科创板
    row("sz", "300760", 70.0),   # 创业板
    row("bj", "920000", 95.0),   # 北交所
]


def call(**params):
    with patch("app.stock_filter._universe", return_value=(UNIVERSE, "2026-10-30")):
        return filter_response(params)


def test_scope_limits_the_universe_before_other_filters():
    result = call(stock_scope=["chinext"])
    assert result["ok"] is True
    assert result["stock_scope"] == "chinext" and result["stock_scope_label"] == "创业板"
    assert result["total_universe"] == 1 and result["universe_total"] == 4
    assert [r["symbol"] for r in result["rows"]] == ["300760"]


def test_scope_combines_with_other_conditions_as_and():
    # 沪深300 里 600519(80) 与 688981(90) 都在；min=85 只留 688981
    assert call(stock_scope=["csi300"], eps_ratio_5y_min=["85"])["total_matched"] == 1
    assert call(stock_scope=["csi300"], eps_ratio_5y_min=["95"])["total_matched"] == 0
    star = call(stock_scope=["star"], eps_ratio_5y_min=["50"])
    assert star["total_matched"] == 1 and star["rows"][0]["symbol"] == "688981"


def test_dual_creative_scope_unions_both_boards_without_overlap():
    result = call(stock_scope=["dual_creative"])
    assert [r["symbol"] for r in result["rows"]] == ["688981", "300760"]
    assert result["total_universe"] == 2
    star = call(stock_scope=["star"])["total_universe"]
    chinext = call(stock_scope=["chinext"])["total_universe"]
    assert result["total_universe"] == star + chinext


def test_main_board_excludes_star_and_chinext_but_keeps_bj_out():
    result = call(stock_scope=["main_board"])
    assert [r["symbol"] for r in result["rows"]] == ["600519"]
    assert result["total_universe"] == 1


def test_unknown_scope_is_rejected():
    result = call(stock_scope=["nasdaq"])
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_filter"


def test_page_wires_the_scope_group_first():
    html = (ROOT / "web" / "stock-filter.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

    assert '<select name="stock_scope">' in html
    for value, label in (("all", "全部"), ("csi300", "沪深300"), ("main_board", "沪深主板"),
                         ("chinext", "创业板"), ("star", "科创板"),
                         ("dual_creative", "双创（科创+创业）")):
        assert f'<option value="{value}">{label}</option>' in html
    assert "<span>01</span>股票范围" in html
    # 其余分组顺次后移
    assert "<span>02</span>RPS 强度" in html and "<span>07</span>相对大盘强弱" in html
    assert "stock_scope_label" in js
