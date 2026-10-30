"""Contracts for the Excel stage-timeline exporter.

The workbook is a view over the classifier, so the tests pin the two things that
can silently rot: how consecutive days collapse into segments, and whether the
rules sheet keeps documenting the live constants.
"""
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "export_stock_stage_timeline.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_stock_stage_timeline", SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_frame(rows):
    base = {
        "close": 10.0, "ma5": 10.0, "ma10": 10.0, "ma20": 10.0, "ma60": 9.0,
        "slope20": 0.01, "slope60": 0.01, "bias20": 0.01,
        "range_pos_60": 0.5, "pos_high_60": -0.05, "vol_ratio": 1.0,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


def test_build_segments_collapses_consecutive_days_and_flags_events():
    exporter = load_exporter()
    frame = make_frame([
        {"trading_day": "2026-01-05", "region": "down", "region_label": "下跌区",
         "stage": "D2", "stage_label": "主跌", "is_event": False, "detail": "主跌：空头排列"},
        {"trading_day": "2026-01-06", "region": "down", "region_label": "下跌区",
         "stage": "D2", "stage_label": "主跌", "is_event": False, "detail": "主跌：空头排列"},
        {"trading_day": "2026-01-07", "region": "base", "region_label": "底部区",
         "stage": "B2", "stage_label": "探底回升", "is_event": True, "detail": "探底回升：放量突破MA20"},
        {"trading_day": "2026-01-08", "region": "up", "region_label": "上升区",
         "stage": "U3", "stage_label": "上升中继", "is_event": False, "detail": "上升中继：MA5<MA10"},
    ])

    segments = exporter.build_segments(frame)

    assert list(segments["阶段代码"]) == ["D2", "B2", "U3"]
    assert list(segments["交易日数"]) == [2, 1, 1]
    assert list(segments["开始日"]) == ["2026-01-05", "2026-01-07", "2026-01-08"]
    assert list(segments["结束日"]) == ["2026-01-06", "2026-01-07", "2026-01-08"]
    assert list(segments["事件型"]) == ["", "是", ""]
    # the end-of-segment evidence must come from the last bar of that segment
    assert segments["段末收盘价"].tolist() == [10.0, 10.0, 10.0]
    assert "段末区间位置" in segments.columns and segments["段末区间位置"].iloc[0] == "50%"


def test_build_segments_keeps_every_explanation_seen_inside_a_segment():
    exporter = load_exporter()
    frame = make_frame([
        {"trading_day": "2026-02-02", "region": "up", "region_label": "上升区",
         "stage": "U3", "stage_label": "上升中继", "is_event": False, "detail": "上升中继：MA5<MA10"},
        {"trading_day": "2026-02-03", "region": "up", "region_label": "上升区",
         "stage": "U3", "stage_label": "上升中继", "is_event": False, "detail": "上升中继：收盘低于MA20"},
    ])

    segments = exporter.build_segments(frame)

    assert len(segments) == 1
    assert segments["起始判断说明"].iloc[0] == "上升中继：MA5<MA10"
    assert segments["段末判断说明"].iloc[0] == "上升中继：收盘低于MA20"
    assert segments["段内判断说明"].iloc[0] == "上升中继：MA5<MA10\n上升中继：收盘低于MA20"


def test_criteria_sheet_documents_the_live_thresholds():
    exporter = load_exporter()
    sheet = exporter.criteria_sheet("600309", "2026-10-29", "2025-10-29", 243)
    text = "\n".join(f"{row.项目} {row.说明}" for row in sheet.itertuples(index=False))

    for expected in ("FLAT_SLOPE", "BASE_MAX_RANGE_POS", "TOP_MAX_DIST_FROM_HIGH", "BIAS_CLIMAX",
                     "B2 探底回升", "U2 主升", "T1 高位震荡", "事件型"):
        assert expected in text, expected
    assert "600309" in text and "243 个交易日" in text
