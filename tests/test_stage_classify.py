"""Deterministic lifecycle-stage classification tests.

Each test feeds a synthetic QFQ daily-bar series engineered to produce a
specific stage, and asserts the exact stage + region returned.  These fixtures
were calibrated against the classifier and lock the per-stage behaviour.
"""
import numpy as np
import pandas as pd
import pytest

from app.stage_classify import classify_stage, _STAGE_LABELS, _REGION_LABELS


def bars(closes, volumes=None):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    if volumes is None:
        volumes = [1e6] * n
    return pd.DataFrame(
        dict(open=closes, high=highs, low=lows, close=closes, volume=volumes),
        index=dates,
    )


def flat(v, n):
    return [float(v)] * n


def lin(a, b, n):
    return list(np.linspace(a, b, n))


def classify(closes, **kw):
    return classify_stage(bars(closes, **kw))


def test_insufficient_data():
    r = classify([100.0] * 30)
    assert r["status"] == "insufficient_data"
    assert r["stage"] is None
    assert r["detail"] == "交易日不足60日"


def test_d2_markdown_strict_decline():
    r = classify([200.0 - i for i in range(90)])
    assert r["stage"] == "D2"
    assert r["region"] == "down"
    assert r["stage_label"] == "主跌"


def test_u2_advance_strict_rise():
    r = classify([100.0 + i for i in range(90)])
    assert r["stage"] == "U2"
    assert r["region"] == "up"
    assert r["stage_label"] == "主升"


def test_d1_breakdown_ma20_just_turned_down():
    r = classify(flat(110, 85) + [109, 108, 107, 106, 105])
    assert r["stage"] == "D1"
    assert r["region"] == "down"
    assert r["stage_label"] == "破位下跌"


def test_d3_rebound_in_downtrend_low_volume():
    r = classify(lin(110, 41, 70) + lin(41.5, 51, 20))
    assert r["stage"] == "D3"
    assert r["region"] == "down"
    assert r["stage_label"] == "下跌中继"


def test_u3_pullback_in_uptrend():
    r = classify(lin(100, 170, 70) + lin(168.5, 159, 20))
    assert r["stage"] == "U3"
    assert r["region"] == "up"
    assert r["stage_label"] == "上升中继"


def test_u4_climax_excessive_extension():
    r = classify(lin(100, 110, 60) + lin(110, 210, 30))
    assert r["stage"] == "U4"
    assert r["region"] == "up"
    assert r["stage_label"] == "加速赶顶"
    assert r["evidence"]["bias20"] >= 0.18


def test_u1_early_uptrend_reclaims_ma60():
    r = classify(flat(100, 80) + lin(100, 110, 10))
    assert r["stage"] == "U1"
    assert r["region"] == "up"
    assert r["stage_label"] == "上升初期"


def test_b1_basing_sideways_at_lows():
    r = classify([52 - 0.02 * i for i in range(90)])
    assert r["stage"] == "B1"
    assert r["region"] == "base"
    assert r["stage_label"] == "底部盘整"


def test_t1_distribution_sideways_at_highs():
    r = classify([48 + 0.02 * i for i in range(90)])
    assert r["stage"] == "T1"
    assert r["region"] == "top"
    assert r["stage_label"] == "高位震荡"


def test_b2_bounce_volume_breakout_above_ma20():
    closes = lin(70, 50, 60) + flat(50, 15) + lin(50, 52, 15)
    vols = [1e6] * 89 + [2.5e6]
    r = classify(closes, volumes=vols)
    assert r["stage"] == "B2"
    assert r["region"] == "base"
    assert r["stage_label"] == "探底回升"
    assert r["evidence"]["vol_ratio"] >= 1.5


def test_b3_retest_holds_above_prior_low():
    r = classify(lin(60, 50, 40) + lin(50, 60, 15) + lin(60, 53, 20) + flat(53, 15))
    assert r["stage"] == "B3"
    assert r["region"] == "base"
    assert r["stage_label"] == "回踩确认"


def test_zero_price_placeholder_bars_are_dropped_before_classification():
    """TDX exports suspended sessions as extra 0.00 rows; they must not reach the MAs."""
    from app.stage_classify import prepare_bars

    closes = lin(100, 170, 70) + lin(168.5, 159, 20)
    clean = bars(closes)
    # placeholder rows carry no price information at all — inserting them must not
    # change the classification, otherwise a suspension would rewrite history
    dirty_closes = closes[:61] + [0.0] + closes[61:72] + [0.0] + closes[72:83] + [0.0] + closes[83:]
    dirty = bars(dirty_closes)

    assert len(prepare_bars(dirty)) == len(dirty) - 3
    expected = classify_stage(clean)
    got = classify_stage(dirty)
    assert (got["region"], got["stage"]) == (expected["region"], expected["stage"])
    for field in ("ma20", "ma60", "slope20", "slope60", "bias20", "vol_ratio"):
        assert got["evidence"][field] == expected["evidence"][field]


def test_all_stages_have_labels_and_evidence():
    # every declared stage/region must carry a label, and evidence is populated
    assert set(_STAGE_LABELS) == {"D1", "D2", "D3", "B1", "B2", "B3",
                                  "U1", "U2", "U3", "U4", "T1"}
    assert set(_REGION_LABELS) == {"down", "base", "up", "top"}
    r = classify([100.0 + i for i in range(90)])
    for key in ("ma5", "ma10", "ma20", "ma60", "slope20", "slope60",
                "bias20", "pos_high_60", "pos_low_60", "vol_ratio"):
        assert key in r["evidence"]
