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


def test_u1_is_the_first_day_reclaiming_ma60():
    """上升初期只在“当日首次收复 MA60”那天成立，且不追高（乖离 <5%）。"""
    closes = lin(100, 160, 120) + lin(160, 147.2, 6) + [148.672]
    r = classify(closes)
    assert r["region"] == "up"
    assert r["stage"] == "U1", r["stage"]
    assert r["stage_label"] == "上升初期"
    assert abs(r["evidence"]["bias20"]) < 0.05


def test_u1_does_not_persist_while_price_stays_above_ma60():
    """连续站上 MA60 之后不再是“刚站上”：旧规则会连续多日标上升初期。"""
    r = classify(flat(100, 80) + lin(100, 110, 10))
    assert r["region"] == "up"
    assert r["stage"] != "U1", r["stage"]
    assert r["stage"] in {"U2", "U3"}


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
    assert r["stage_label"] == "探底回升"
    assert r["evidence"]["vol_ratio"] >= 1.5
    # 事件只标当天动作，不再把区域改写成底部：中期仍向下就该显示下跌区
    assert r["region"] == "down"
    assert r["is_event"] is True


def test_b3_retest_holds_above_prior_low():
    r = classify(lin(60, 50, 40) + lin(50, 60, 15) + lin(60, 53, 20) + flat(53, 15))
    assert r["stage"] == "B3"
    assert r["stage_label"] == "回踩确认"
    # 区域按趋势判定：短期斜率仍向下 → 下跌区，不再被强制改成底部区
    assert r["region"] == "down"


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


def test_base_requires_price_in_lower_half_of_60d_range():
    """MA60 仍上行、收盘跌破 MA60，但价格还在 60 日区间上半 → 属上升趋势回抽，不是底部盘整。

    形状：160 根从 100 涨到 180，随后 30 根回落到 174.6（略低于 MA60）。
    收盘距 60 日低点约 60% 位置，因此不得判为 base/B1。
    """
    closes = lin(100, 180, 160) + lin(180, 174.6, 30)
    r = classify(closes)
    assert r["region"] == "up", f"区间上半却被判 {r['region']}/{r['stage']}"
    assert r["stage"] != "B1"
    assert r["evidence"]["ma60"] > 0
    # 位置证据：距 60 日高点很近（-4%），说明不是底部
    assert r["evidence"]["pos_high_60"] > -0.10


def test_top_requires_price_near_the_60d_high():
    """MA60 已走弱、收盘仍在 MA60 上方，但价格离 60 日高点 13.5% → 是高位回落，不是高位震荡。

    形状：长牛 100→200、长跌 200→120（MA60 转下），随后 8 根急反弹到 150。
    """
    closes = lin(100, 200, 150) + lin(200, 120, 80) + lin(120, 150, 8)
    r = classify(closes)
    assert r["evidence"]["slope60"] < 0
    assert r["evidence"]["pos_high_60"] < -0.10
    assert r["region"] == "down", f"距高点已 13% 却被判 {r['region']}/{r['stage']}"
    assert r["stage"] != "T1"


def test_rally_inside_a_downtrend_is_r2_not_t1():
    """下跌趋势中的反弹（MA60 仍下行、价格回到 MA60 上方且贴近高点）→ R2 下跌反弹。"""
    closes = lin(100, 200, 150) + lin(200, 120, 80) + lin(120, 160, 10)
    r = classify(closes)
    assert r["evidence"]["pos_high_60"] > -0.10
    assert r["evidence"]["slope60"] < -0.005
    assert (r["region"], r["stage"]) == ("top", "R2")
    assert r["stage_label"] == "下跌反弹"


def test_t1_still_covers_flat_churn_near_the_high():
    """MA60 走平、价格贴住 60 日高点的横盘 → 仍是 T1 高位震荡（不得被 R2 抢走）。"""
    r = classify([48 + 0.02 * i for i in range(90)])
    assert abs(r["evidence"]["slope60"]) <= 0.005
    assert r["evidence"]["pos_high_60"] > -0.10
    assert (r["region"], r["stage"]) == ("top", "T1")
    assert r["stage_label"] == "高位震荡"


def test_b1_still_exists_for_genuine_lows():
    """真正的底部盘整（价格在区间下半、MA60 走平微升）必须仍判 B1，不能被位置门清空。"""
    r = classify([52 - 0.02 * i for i in range(90)])
    assert (r["region"], r["stage"]) == ("base", "B1")


def test_u2_requires_close_above_ma20():
    """主升必须站上 MA20；上升区里跌破 MA20 的短期回踩归 U3 上升中继。

    形状：120 根 100→160，最后 2 根小幅回落到 155（低于 MA20 约 0.6%，MA5 仍高于 MA10）。
    """
    closes = lin(100, 160, 120) + lin(160, 155, 2)
    r = classify(closes)
    assert r["region"] == "up"
    assert r["evidence"]["bias20"] < 0, "样本必须收盘低于 MA20"
    assert r["evidence"]["ma5"] > r["evidence"]["ma10"]
    assert r["stage"] == "U3", f"跌破 MA20 却仍判 {r['stage']}"
    assert "MA20" in r["detail"]


def test_u2_still_applies_when_close_holds_above_ma20():
    """同样的小幅回落，但收盘仍在 MA20 上方 → 仍属主升 U2。"""
    closes = lin(100, 160, 120) + lin(160, 158, 2)
    r = classify(closes)
    assert r["region"] == "up"
    assert r["evidence"]["bias20"] > 0
    assert (r["region"], r["stage"]) == ("up", "U2")


def test_event_stages_are_flagged_for_callers():
    """B2/D1 是当日事件而非可停留状态，必须通过 is_event 显式暴露。

    依据：全市场历史里 B2 平均持续 1.51 个交易日、D1 2.79 天，
    而真正的阶段（D2 6.09、B3 5.54）都在 4 天以上。
    """
    from app.stage_classify import EVENT_STAGES

    assert EVENT_STAGES == frozenset({"B2", "D1"})

    b2 = classify(lin(70, 50, 60) + flat(50, 15) + lin(50, 52, 15),
                  volumes=[1e6] * 89 + [2.5e6])
    assert (b2["region"], b2["stage"]) == ("down", "B2")
    assert b2["is_event"] is True

    d1 = classify(flat(110, 85) + [109, 108, 107, 106, 105])
    assert (d1["region"], d1["stage"]) == ("down", "D1")
    assert d1["is_event"] is True

    for fixture in (
        [100.0 + i for i in range(90)],                       # U2
        [48 + 0.02 * i for i in range(90)],                   # T1
        [52 - 0.02 * i for i in range(90)],                   # B1
        lin(100, 170, 70) + lin(168.5, 159, 20),              # U3
    ):
        result = classify(fixture)
        assert result["is_event"] is False, result["stage"]


def test_uptrend_deep_pullback_is_not_a_bottom_base():
    """MA60 仍上行、价格跌破 MA60 且落到区间下半 → 上升回撤 R1，不是底部盘整。

    全库实测：旧 B1 里 86.9% 是这种情况（MA60 斜率 > +0.5%），把它们叫底部盘整
    会掩盖“趋势受损”这一事实。
    """
    # 快速跌破后停住：60 日低点就在最近 20 日内（B3 的“未破前低”不成立），
    # 因此不会先被 B3 抢走，才能验证 R1 本身
    closes = lin(100, 200, 120) + lin(200, 150, 8) + lin(150, 153, 3)
    r = classify(closes)
    assert r["evidence"]["slope60"] > 0.005
    assert r["evidence"]["range_pos_60"] <= 0.5
    assert r["evidence"]["low_20"] <= r["evidence"]["low_20"], "sanity"
    assert (r["region"], r["stage"]) == ("base", "R1"), r["stage"]
    assert r["stage_label"] == "上升回撤"


def test_declining_trend_rally_near_high_is_not_high_level_churn():
    """MA60 下行、价格弹回 MA60 上方且贴近高点 → 下跌反弹 R2，不是高位震荡。

    全库实测：旧 T1 里 75.2% 的 MA60 斜率 < -0.5%，把它们叫高位震荡会把
    “下跌趋势里的反弹”读成“顶部件横盘”。
    """
    closes = lin(100, 200, 120) + lin(200, 130, 60) + lin(130, 190, 6)
    r = classify(closes)
    assert r["evidence"]["slope60"] < -0.005
    assert r["evidence"]["pos_high_60"] > -0.10
    assert (r["region"], r["stage"]) == ("top", "R2"), r["stage"]
    assert r["stage_label"] == "下跌反弹"


def test_volume_breakout_at_high_position_is_not_b2():
    """高位（区间位置 95%、距高点 1%）放量突破 MA20 不能叫探底回升。

    全库实测：旧 B2 里 82.4% 位于区间上半，68.7% 距高点不足 10%。
    """
    closes = lin(100, 180, 150) + lin(180, 186, 10)
    volumes = [1e6] * 159 + [2.0e6]
    r = classify(closes, volumes=volumes)
    assert r["evidence"]["range_pos_60"] > 0.9
    assert r["stage"] != "B2", f"高位放量突破被标成 {r['stage']}"
    assert r["region"] == "up"


def test_b2_still_fires_at_low_position_and_keeps_its_region():
    """低位放量收复 MA20 仍是 B2，但区域按趋势判定（不再被强制改成底部区）。"""
    closes = lin(70, 50, 60) + [50.0] * 15 + lin(50, 53, 15)
    volumes = [1e6] * 89 + [2.5e6]
    r = classify(closes, volumes=volumes)
    assert r["stage"] == "B2"
    assert r["is_event"] is True
    assert r["evidence"]["range_pos_60"] < 0.5
    # 中期仍向下、价格已离高点 12% → 该行属下跌区，标签应如实显示
    assert r["region"] == "down"


def test_b3_requires_ma60_not_already_falling():
    """MA60 已明显下行时不能叫回踩确认（旧规则只有 slope60 ≤ +0.5% 的上限）。"""
    closes = (lin(100, 200, 100) + lin(200, 110, 40) + lin(110, 148.5, 20) + lin(148.5, 133.65, 6))
    r = classify(closes)
    assert r["evidence"]["slope60"] < -0.005
    assert r["stage"] != "B3", f"MA60 斜率 {r['evidence']['slope60']:.3%} 仍被判 B3"


def test_b3_still_fires_when_ma60_is_flat_and_prior_low_holds():
    closes = lin(60, 50, 40) + lin(50, 60, 15) + lin(60, 53, 20) + [53.0] * 15
    r = classify(closes)
    assert abs(r["evidence"]["slope60"]) <= 0.005
    assert r["evidence"]["range_pos_60"] <= 0.5
    assert r["stage"] == "B3", r["stage"]
    assert r["region"] in {"base", "down"}, r["region"]


def test_b3_rejects_deep_pullbacks_below_eight_percent():
    """已经跌破 MA20 超过 8% 的回踩是深度回撤（R1 领域），不是浅回踩确认。"""
    closes = lin(100, 200, 150) + lin(200, 172, 12)
    r = classify(closes)
    assert r["evidence"]["bias20"] < -0.08
    assert r["stage"] != "B3", f"bias20={r['evidence']['bias20']:.3%} 仍被判 B3"
    assert (r["region"], r["stage"]) == ("base", "R1")


def test_d2_requires_bearish_alignment():
    """主跌必须是空头排列；均线纠缠一律归下跌中继，不再叫主跌。

    旧规则里 D2 是“下跌区兜底”，全库 19% 的 D2 其实不是空头排列。
    """
    closes = lin(100, 200, 120) + lin(200, 180, 50) + lin(180, 185.4, 6)
    r = classify(closes)
    assert r["region"] == "down"
    ev = r["evidence"]
    assert not (ev["ma5"] < ev["ma10"] < ev["ma20"] < ev["ma60"])
    assert r["stage"] == "D3", f"纠缠却判 {r['stage']}"


def test_d2_still_covers_real_bearish_alignment():
    """真正的空头排列（且非破位首日、非短期反弹）仍是 D2 主跌。"""
    closes = lin(200, 120, 90)
    r = classify(closes)
    ev = r["evidence"]
    assert r["region"] == "down"
    assert ev["ma5"] < ev["ma10"] < ev["ma20"] < ev["ma60"]
    assert r["stage"] == "D2", r["stage"]


def test_d1_takes_priority_over_d3_when_ma20_just_turns_down():
    """MA20 刚拐头向下优先判破位（实测与 D3 条件几乎不重叠，此处锁顺序）。"""
    r = classify(flat(110, 85) + [109, 108, 107, 106, 105])
    assert r["evidence"]["slope20"] < 0
    assert (r["region"], r["stage"]) == ("down", "D1")


def test_all_stages_have_labels_and_evidence():
    # every declared stage/region must carry a label, and evidence is populated
    assert set(_STAGE_LABELS) == {"D1", "D2", "D3", "B1", "B2", "B3", "R1", "R2",
                                  "U1", "U2", "U3", "U4", "T1"}
    assert set(_REGION_LABELS) == {"down", "base", "up", "top"}
    r = classify([100.0 + i for i in range(90)])
    for key in ("ma5", "ma10", "ma20", "ma60", "slope20", "slope60",
                "bias20", "pos_high_60", "pos_low_60", "vol_ratio"):
        assert key in r["evidence"]
