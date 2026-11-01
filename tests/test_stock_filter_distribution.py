"""板块股价收益比分布：接口口径 + 页面入口。"""
import json
from pathlib import Path

import pytest

from app.stock_filter_distribution import BIN_EDGES, BOARDS, eps_ratio_distribution

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web/stock-filter.html").read_text(encoding="utf-8")
JS = (ROOT / "web/stock-filter-distribution.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def payload():
    return eps_ratio_distribution()


def test_payload_covers_the_four_boards(payload):
    assert payload["ok"] is True
    assert [b["key"] for b in payload["boards"]] == [key for key, _ in BOARDS]
    assert [b["label"] for b in payload["boards"]] == [label for _, label in BOARDS]


def test_every_board_reports_its_own_sample(payload):
    total = 0
    for board in payload["boards"]:
        assert board["n"] > 0, board["label"]
        assert board["n"] + board["missing"] > 0
        assert board["q1"] <= board["median"] <= board["q3"]
        assert board["p10"] <= board["q1"] and board["q3"] <= board["p90"]
        total += board["n"] + board["missing"]
    assert total > 4000


def test_bins_partition_every_valid_observation(payload):
    for board in payload["boards"]:
        assert sum(b["count"] for b in board["bins"]) == board["n"]
        assert [b["label"] for b in board["bins"]] == [label for _, _, label in BIN_EDGES]
        assert sum(b["pct"] for b in board["bins"]) == pytest.approx(100, abs=0.1)


def test_negative_share_matches_the_negative_bin(payload):
    for board in payload["boards"]:
        negative_bin = board["bins"][0]
        assert negative_bin["label"] == "<0"
        assert negative_bin["count"] == board["negative"]
        assert board["negative_pct"] == pytest.approx(negative_bin["pct"], abs=0.01)


def test_implied_pe_is_five_divided_by_the_median(payload):
    for board in payload["boards"]:
        assert board["implied_pe"] == pytest.approx(500.0 / board["median"], rel=0.01)


def test_median_ordering_reflects_the_value_gradient(payload):
    by_key = {b["key"]: b for b in payload["boards"]}
    # 主板最便宜、科创板最贵（中位收益比：主板 > 创业板 > 科创板）
    assert by_key["main"]["median"] > by_key["chinext"]["median"] > by_key["star"]["median"]


def test_page_has_the_entry_point_and_the_dialog():
    assert 'id="open-eps-distribution"' in HTML
    assert "板块股价收益比分布" in HTML
    assert 'id="eps-distribution-dialog"' in HTML
    assert 'id="box-chart"' in HTML and 'id="bin-chart"' in HTML
    assert 'id="dist-rows"' in HTML
    assert '<script src="/stock-filter-distribution.js' in HTML


def test_script_renders_both_charts_from_the_api():
    assert "/api/stock-filter-distribution" in JS
    assert "showModal" in JS
    assert "renderBox" in JS and "renderBins" in JS and "renderTable" in JS
    # 箱线图必须画出箱体、中位线、触须三类元素
    for element in ("rect", "line", "circle"):
        assert "el('" + element + "'" in JS
