"""温度计算快路径：与逐日裁剪的旧算法逐位一致。"""
import math
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.concept_temperature import (
    _percentile,
    _return_and_volume,
    build_temperature_rows,
    metric_from_series,
    percentile_of,
    prepare_series,
)


def _frames(stocks=24, days=300, seed=7):
    random.seed(seed)
    index = pd.to_datetime([date(2025, 1, 1) + timedelta(days=i) for i in range(days)])
    frames, mapping = {}, []
    for stock in range(stocks):
        base = 8 + stock * 0.6
        closes = [round(base * (1 + 0.003 * i + 0.02 * random.uniform(-1, 1)), 4) for i in range(days)]
        volumes = [float(1_000_000 + random.randint(0, 500_000)) for _ in range(days)]
        frames[f"{600000 + stock}"] = pd.DataFrame(
            {"close": closes, "high": [c * 1.02 for c in closes], "low": [c * 0.98 for c in closes],
             "volume": volumes}, index=index)
        for concept in (f"C{stock % 3}", f"C{(stock + 1) % 3}"):
            mapping.append({"concept_code": concept, "concept_name": f"概念{concept}",
                            "symbol": f"{600000 + stock}", "stock_name": f"股票{stock}"})
    return mapping, frames


@pytest.mark.parametrize("window", [3, 10, 60])
@pytest.mark.parametrize("offset", [0, 7, 45])
def test_fast_path_matches_daily_clipping(window, offset):
    mapping, frames = _frames()
    prepared = prepare_series(frames)
    target = frames["600000"].index[-1 - offset]

    slow, _ = build_temperature_rows(mapping, frames, window=window, min_members=2,
                                     as_of=target, include_members=False)
    fast, _ = build_temperature_rows(mapping, frames, window=window, min_members=2,
                                     as_of=target, include_members=False, prepared=prepared)
    assert fast == slow


def test_metric_matches_reference_including_missing_volume():
    index = pd.to_datetime([date(2025, 1, 1) + timedelta(days=i) for i in range(60)])
    closes = [10 + 0.1 * i for i in range(60)]
    volumes = [float(1000 + i) for i in range(60)]
    volumes[3] = float("nan")          # 缺失成交量应按 pandas 语义跳过
    frame = pd.DataFrame({"close": closes, "volume": volumes}, index=index)
    prepared = prepare_series({"600000": frame})

    expected = _return_and_volume(frame, 10)
    actual = metric_from_series(prepared, "600000", frame.index[-1].value, 10)
    assert actual[0] == pytest.approx(expected[0])
    assert actual[1] == expected[1]
    assert actual[2] == pytest.approx(expected[2])


def test_metric_returns_none_before_enough_history():
    index = pd.to_datetime([date(2025, 1, 1) + timedelta(days=i) for i in range(20)])
    frame = pd.DataFrame({"close": [10.0] * 20, "volume": [1000.0] * 20}, index=index)
    prepared = prepare_series({"600000": frame})
    assert metric_from_series(prepared, "600000", frame.index[-1].value, 10) is None
    assert metric_from_series(prepared, "999999", frame.index[-1].value, 10) is None


def test_symbols_with_missing_close_are_left_to_the_slow_path():
    index = pd.to_datetime([date(2025, 1, 1) + timedelta(days=i) for i in range(40)])
    closes = [10.0] * 40
    closes[5] = float("nan")
    frame = pd.DataFrame({"close": closes, "volume": [1000.0] * 40}, index=index)
    assert prepare_series({"600000": frame}) == {}


def test_percentile_helper_matches_the_scalar_reference():
    values = [1.0, 2.0, 2.0, 3.5, -1.0]
    for target in values + [0.0, 10.0]:
        assert percentile_of(values, [target])[0] == pytest.approx(_percentile(values, target))
    assert percentile_of([], [1.0]) == [0.0]
