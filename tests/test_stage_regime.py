"""Contracts for the A/B/C/D regime classifier.

Each test pins one stage plus the evidence that put it there, because the whole
point of the framework is that a stage must be reconstructible from the 60-bar
window rather than asserted.
"""
import numpy as np
import pandas as pd
import pytest

from app.stage_regime import STAGE_LABELS, WINDOW, classify_regime


def make_bars(closes, volumes):
    closes = [float(x) for x in closes]
    volumes = [float(x) for x in volumes]
    assert len(closes) == len(volumes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.002 for c in closes],
            "low": [c * 0.998 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.bdate_range("2024-01-01", periods=len(closes)),
    )


def lin(start, end, count):
    return list(np.linspace(start, end, count))


def test_stage_c_when_trend_and_volume_agree():
    """单边上涨 + 量能逐级放大 + 收盘在 MA20 上方 → 主升推进 C。"""
    closes = lin(100, 140, WINDOW)
    volumes = lin(1e6, 2e6, WINDOW)
    result = classify_regime(make_bars(closes, volumes))

    assert result["stage"] == "C"
    assert result["stage_label"] == "主升推进"
    assert result["score"] >= 4
    assert result["items"]["价在MA20上"] is True
    assert result["items"]["红肥绿瘦"] is True
    assert not any(result["penalties"].values())


def test_stage_b_requires_breakout_then_shrinking_pullback():
    """横盘 → 放量突破 → 缩量回踩守住 → 启动确认 B（不是 C）。"""
    closes = [100.0] * 40 + [100.5] * 10 + [108.0] + lin(107.0, 106.0, 5) + [107.5] * 4
    volumes = [1e6] * 50 + [4e6] + [1.2e6] * 5 + [1e6] * 4
    result = classify_regime(make_bars(closes, volumes))

    assert result["stage"] == "B"
    assert result["stage_label"] == "突破启动确认"
    assert result["items"]["放量突破"] is True
    assert result["items"]["缩量回踩守住"] is True
    assert "启动确认" in result["reason"]


def test_stage_d_when_price_high_and_volume_dries_up():
    """价格贴在窗口高点但量能明显萎缩 → 放量滞涨/顶背离雏形 → 派发 D。"""
    closes = lin(100, 140, 50) + [139, 140, 141, 142, 143, 144, 143.5, 144.2, 144.1, 144.3]
    volumes = [2e6] * 50 + [8e5] * 10
    result = classify_regime(make_bars(closes, volumes))

    assert result["stage"] == "D"
    assert result["stage_label"] == "高位派发"
    assert result["penalties"]["放量滞涨"] is True
    assert result["score"] <= 3


def test_distribution_requires_a_high_position():
    """扣分项成立但价格只在箱体中部（位置<60%、乖离<5%）时不得判「高位派发」。

    实测旧口径 41.3% 的 D 行箱体位置在 0.5 以下：下跌趋势里的抛售日会被叫成高位派发。
    """
    closes = (list(np.linspace(100, 160, 25)) + list(np.linspace(160, 132, 20))
              + [132, 130, 131, 129, 130, 128, 129, 127, 128, 126, 127, 125, 126, 124, 125])
    volumes = [1e6] * 45 + [1.1e6, 1.3e6, 1.2e6, 1.5e6, 1.4e6, 1.7e6, 1.6e6, 1.9e6, 1.8e6,
                            2.1e6, 2.0e6, 2.3e6, 2.2e6, 2.5e6, 2.4e6]
    result = classify_regime(make_bars(closes, volumes))

    assert result["penalties"]["抛售日密集"] is True, "构造样本应先触发扣分项"
    assert result["evidence"]["box_position"] < 0.6
    assert result["stage"] != "D", f"箱体位置 {result['evidence']['box_position']:.2f} 却判派发"


def test_stage_a_bottom_when_lows_stop_falling():
    """横盘、低点不再下移、无明显突破 → 底部构筑（A 档）。"""
    closes = [100 + (0.5 if i % 2 else -0.5) for i in range(WINDOW)]
    result = classify_regime(make_bars(closes, [1e6] * WINDOW))

    assert result["stage"] == "A"
    assert result["items"]["低点不创新低"] is True
    assert "下跌中继" not in result["reason"]
    assert result["score"] <= 3


def test_stage_a_downtrend_when_lows_keep_falling():
    """单边下跌、低点持续下移 → 仍归 A，但必须明确说是下跌中继，不是筑底。"""
    closes = lin(140, 100, WINDOW)
    result = classify_regime(make_bars(closes, [1e6] * WINDOW))

    assert result["stage"] == "A"
    assert result["items"]["低点不创新低"] is False
    assert "下跌中继" in result["reason"]
    assert result["score"] <= 1


def test_score_is_six_items_minus_two_penalties():
    """打分口径固定：6 个正向条目各 1 分，2 个扣分项各 −1，不夹带其他权重。"""
    closes = lin(100, 140, WINDOW)
    volumes = lin(1e6, 2e6, WINDOW)
    result = classify_regime(make_bars(closes, volumes))

    assert set(result["items"]) == {
        "低点不创新低", "量能线上", "红肥绿瘦", "放量突破", "缩量回踩守住", "价在MA20上",
    }
    positives = sum(1 for value in result["items"].values() if value)
    penalties = sum(1 for value in result["penalties"].values() if value)
    assert result["score"] == positives - penalties


def test_breakout_compares_against_prior_twenty_bars_only():
    """突破以“前 20 根最高价”为基准：只追平窗口高点不算突破。"""
    closes = [100.0] * (WINDOW - 1) + [100.0]
    volumes = [1e6] * (WINDOW - 1) + [3e6]
    flat = classify_regime(make_bars(closes, volumes))
    assert flat["items"]["放量突破"] is False

    closes[-1] = 103.0
    jumped = classify_regime(make_bars(closes, volumes))
    assert jumped["items"]["放量突破"] is True


def test_window_and_basis_are_declared():
    result = classify_regime(make_bars(lin(100, 140, WINDOW), [1e6] * WINDOW))
    assert result["window_bars"] == WINDOW == 60
    assert result["price_basis"] == "tdx_export_qfq"
    assert result["stage"] in STAGE_LABELS


def test_rejects_windows_shorter_than_sixty_bars():
    with pytest.raises(ValueError):
        classify_regime(make_bars(lin(100, 110, WINDOW - 1), [1e6] * (WINDOW - 1)))
