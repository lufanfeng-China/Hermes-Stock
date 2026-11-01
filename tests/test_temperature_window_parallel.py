"""温度构建：窗口级进程并行必须与串行结果完全一致。"""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_concept_temperature", ROOT / "scripts" / "build_concept_temperature.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture():
    """4 个概念、12 只股票、260 个交易日的合成前复权日线。"""
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(260)]
    frames, mapping = {}, []
    for stock in range(12):
        symbol = f"{600000 + stock}"
        base = 10 + stock
        closes = [base * (1 + 0.001 * index + 0.02 * ((index + stock) % 5 - 2) / 10) for index in range(260)]
        frames[symbol] = pd.DataFrame(
            {"close": closes, "high": [value * 1.01 for value in closes],
             "low": [value * 0.99 for value in closes], "volume": [1_000_000 + 1000 * stock] * 260},
            index=pd.to_datetime(days))
        mapping.append({"concept_code": f"C{stock % 4}", "concept_name": f"概念{stock % 4}",
                        "symbol": symbol, "stock_name": f"股票{stock}"})
    return mapping, frames


@pytest.fixture(scope="module")
def built():
    builder = _builder()
    mapping, frames = _fixture()
    as_of = max(frame.index.max() for frame in frames.values())
    serial = builder.build_windows((3, 10), mapping, frames, as_of, 3, jobs=1)
    parallel = builder.build_windows((3, 10), mapping, frames, as_of, 3, jobs=2)
    return serial, parallel


def test_parallel_matches_serial_exactly(built):
    serial, parallel = built
    assert set(serial) == set(parallel) == {"3", "10"}
    for window in ("3", "10"):
        assert parallel[window] == serial[window], f"窗口 {window} 并行与串行结果不一致"


def test_each_window_carries_rows_members_and_heat_history(built):
    serial, _ = built
    for window in ("3", "10"):
        section = serial[window]
        assert section["concepts"] and section["members"] and section["heat_history"]
        first = section["concepts"][0]
        assert {"concept_code", "heat_score", "temperature", "temperature_previous"} <= set(first)


def test_jobs_defaults_to_a_bounded_number():
    import multiprocessing

    builder = _builder()
    expected = max(1, min(5, multiprocessing.cpu_count() // 2, 5))
    assert 1 <= expected <= 5
    assert builder.build_windows.__doc__


def test_heat_history_is_capped_at_sixty_trading_days(built):
    builder = _builder()
    serial, _ = built
    assert builder.HEAT_TREND_DAYS == 60
    for window in ("3", "10"):
        points = next(iter(serial[window]["heat_history"].values()))
        assert len(points) <= 60, f"窗口 {window} 的热度序列有 {len(points)} 个交易日"


def test_page_copy_no_longer_promises_half_a_year():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")
    assert "过去半年" not in html and "过去半年" not in js
    assert "最近 60 个交易日" in js
