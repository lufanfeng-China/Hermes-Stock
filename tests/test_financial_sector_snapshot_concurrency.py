from contextlib import contextmanager
from types import SimpleNamespace

from app.financial import sector_external_runtime
from scripts.build_financial_sector_health_snapshot import (
    _merge_score_update_if_current,
    _withhold_stale_quarterly_score,
)


def test_score_update_does_not_overwrite_concurrent_retry_state():
    latest = {
        "symbol": "600036", "status": "queued", "latest_announced_period": "2026Q3",
        "quarterly_score": None, "annual_score": 90.0,
    }
    score_update = {
        "symbol": "600036", "annual_score": 93.0, "annual_period": "2025A",
        "quarterly_score": 88.0, "latest_scored_period": "2026Q3",
    }
    merged = _merge_score_update_if_current(
        latest, base_announced="2026Q3", base_status="up_to_date", score_update=score_update,
    )
    assert merged["status"] == "queued"
    assert merged["quarterly_score"] is None
    assert merged["annual_score"] == 93.0


def test_score_update_applies_when_source_state_is_unchanged():
    latest = {"symbol": "600036", "status": "up_to_date", "latest_announced_period": "2026Q3"}
    score_update = {"symbol": "600036", "quarterly_score": 88.0, "latest_scored_period": "2026Q3"}
    merged = _merge_score_update_if_current(
        latest, base_announced="2026Q3", base_status="up_to_date", score_update=score_update,
    )
    assert merged["quarterly_score"] == 88.0


def test_missing_new_period_score_moves_old_current_score_to_previous():
    old_status = {
        "latest_announced_period": "2026Q3", "latest_scored_period": "2026H1",
        "quarterly_score": 90.0, "quarterly_status": "stable",
    }
    update = _withhold_stale_quarterly_score(old_status, {})
    assert update["quarterly_score"] is None
    assert update["quarterly_status"] == "pending_update"
    assert update["previous_quarterly_period"] == "2026H1"
    assert update["previous_quarterly_score"] == 90.0


def test_parent_process_failure_does_not_downgrade_concurrent_success_inside_symbol_lock(monkeypatch):
    class Store:
        def __init__(self):
            self.locked = False
            self.current = {"symbol": "600036", "quarterly_score": 88.0, "status": "up_to_date"}
            self.saved = None

        @contextmanager
        def symbol_lock(self, symbol):
            self.locked = True
            self.current["latest_scored_period"] = "2026Q3"
            try:
                yield
            finally:
                self.locked = False

        def load_symbol_status(self, symbol):
            assert self.locked, "parent failure save must reread only after taking symbol_lock"
            return dict(self.current)

        def save_symbol_status(self, record):
            assert self.locked
            self.saved = dict(record)

    store = Store()
    monkeypatch.setattr(sector_external_runtime, "FinancialSectorStatusStore", lambda path: store)
    monkeypatch.setattr(
        sector_external_runtime.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="failed", stdout=""),
    )
    sector_external_runtime._run("600036", report_period="", source_type="")
    assert store.saved is None
    assert store.current["status"] == "up_to_date"
    assert store.current["latest_scored_period"] == "2026Q3"


def test_parent_process_failure_marks_still_queued_retry_failed(monkeypatch):
    class Store:
        def __init__(self):
            self.locked = False
            self.current = {"symbol": "600036", "status": "queued"}
            self.saved = None

        @contextmanager
        def symbol_lock(self, symbol):
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        def load_symbol_status(self, symbol):
            assert self.locked
            return dict(self.current)

        def save_symbol_status(self, record):
            assert self.locked
            self.saved = dict(record)

    store = Store()
    monkeypatch.setattr(sector_external_runtime, "FinancialSectorStatusStore", lambda path: store)
    monkeypatch.setattr(
        sector_external_runtime.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="failed", stdout=""),
    )
    sector_external_runtime._run("600036", report_period="", source_type="")
    assert store.saved["status"] == "failed"
