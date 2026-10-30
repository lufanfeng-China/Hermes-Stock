"""Build-provenance contract for the published stage history.

The parquet cannot be trusted by itself: an auditor needs to see which
thresholds and region gates produced the labels.  These tests pin the manifest
payload without needing the 12.5M-row dataset on disk.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_stage_history.py"


def load_build_module():
    spec = importlib.util.spec_from_file_location("build_stage_history", SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_thresholds_record_every_label_shaping_constant():
    builder = load_build_module()
    thresholds = builder.manifest_thresholds()

    # legacy scale constants
    assert thresholds["FLAT_SLOPE"] == 0.005
    assert thresholds["BIAS_CLIMAX"] == 0.18
    assert thresholds["VOL_BREAKOUT"] == 1.5
    assert thresholds["MIN_DAYS"] == 60
    # region position gates added 2026-10-30
    assert thresholds["BASE_MAX_RANGE_POS"] == 0.50
    assert thresholds["TOP_MAX_DIST_FROM_HIGH"] == 0.10
    # event-type stages must be visible in the provenance
    assert thresholds["EVENT_STAGES"] == ["B2", "D1"]


def test_manifest_thresholds_stay_in_sync_with_the_classifier():
    """Two sources must not drift: the manifest has to quote live constants."""
    builder = load_build_module()
    from app.stage_classify import (
        BASE_MAX_RANGE_POS,
        BIAS_CLIMAX,
        EVENT_STAGES,
        FLAT_SLOPE,
        MIN_DAYS,
        TOP_MAX_DIST_FROM_HIGH,
        VOL_BREAKOUT,
    )

    thresholds = builder.manifest_thresholds()
    assert thresholds["FLAT_SLOPE"] == FLAT_SLOPE
    assert thresholds["BIAS_CLIMAX"] == BIAS_CLIMAX
    assert thresholds["VOL_BREAKOUT"] == VOL_BREAKOUT
    assert thresholds["MIN_DAYS"] == MIN_DAYS
    assert thresholds["BASE_MAX_RANGE_POS"] == BASE_MAX_RANGE_POS
    assert thresholds["TOP_MAX_DIST_FROM_HIGH"] == TOP_MAX_DIST_FROM_HIGH
    assert thresholds["EVENT_STAGES"] == sorted(EVENT_STAGES)
