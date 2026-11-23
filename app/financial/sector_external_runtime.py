"""Background runner for one-symbol bank/securities external-data retries."""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import PROJECT_ROOT, TONGDAXIN_PYTHON
from app.financial.sector_external_update import FinancialSectorStatusStore

STATUS_DIR = PROJECT_ROOT / "data" / "derived" / "financial_sector" / "update_status"
_ACTIVE_SYMBOLS: set[str] = set()
_LOCK = threading.Lock()


def _save_parent_failure(store: FinancialSectorStatusStore, symbol: str, message: str) -> None:
    with store.symbol_lock(symbol):
        record = store.load_symbol_status(symbol)
        if record.get("status") not in {
            "queued", "retry_pending", "processing", "downloading", "parsing",
            "validating", "scoring", "publishing",
        }:
            return
        record.update({
            "symbol": symbol,
            "status": "failed",
            "last_error": {"code": "retry_process_failed", "message": message},
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        })
        store.save_symbol_status(record)


def _run(symbol: str, *, report_period: str, source_type: str) -> None:
    store = FinancialSectorStatusStore(STATUS_DIR)
    command = [
        str(TONGDAXIN_PYTHON),
        str(PROJECT_ROOT / "scripts" / "update_financial_sector_external.py"),
        "--symbol", symbol,
    ]
    if report_period:
        command.extend(["--report-period", report_period])
    if source_type:
        command.extend(["--source-type", source_type])
    try:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0:
            _save_parent_failure(
                store, symbol, (completed.stderr or completed.stdout or "单股重试进程失败")[-2000:],
            )
    except Exception as exc:
        _save_parent_failure(store, symbol, str(exc))
    finally:
        with _LOCK:
            _ACTIVE_SYMBOLS.discard(symbol)


def start_symbol_retry(symbol: str, *, report_period: str = "", source_type: str = "") -> dict[str, object]:
    with _LOCK:
        if symbol in _ACTIVE_SYMBOLS:
            return {"ok": False, "started": False, "symbol": symbol, "status": "running",
                    "error": {"code": "already_running", "message": "该股票已经在更新中"}}
        _ACTIVE_SYMBOLS.add(symbol)

    store = FinancialSectorStatusStore(STATUS_DIR)
    with store.symbol_lock(symbol):
        record = store.load_symbol_status(symbol)
        record.update({
            "symbol": symbol,
            "status": "queued",
            "retry_count": int(record.get("retry_count") or 0) + 1,
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_error": record.get("last_error"),
        })
        store.save_symbol_status(record)
    thread = threading.Thread(
        target=_run,
        kwargs={"symbol": symbol, "report_period": report_period, "source_type": source_type},
        daemon=True,
        name=f"financial-sector-retry-{symbol}",
    )
    thread.start()
    return {"ok": True, "started": True, "symbol": symbol, "status": "queued",
            "report_period": report_period or None, "source_type": source_type or None}
