"""Per-symbol state for bank/securities external financial-report updates."""

from __future__ import annotations

import json
import os
import re
import tempfile
import fcntl
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse


class ExternalUpdateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


def _failure_status(code: str) -> str:
    return {
        "pdf_download_failed": "download_failed",
        "pdf_invalid": "download_failed",
        "table_not_found": "parse_failed",
        "field_not_found": "parse_failed",
        "scope_ambiguous": "validation_failed",
        "unit_ambiguous": "validation_failed",
        "validation_failed": "validation_failed",
        "publish_failed": "publish_failed",
    }.get(code, "failed")


def classify_cninfo_report_title(title: str) -> dict[str, str] | None:
    clean = re.sub(r"<[^>]+>", "", str(title or "")).replace(" ", "")
    if "摘要" in clean or "H股" in clean or "境内同步披露" in clean:
        return None
    year_match = re.search(r"(20\d{2})年", clean)
    if not year_match:
        return None
    year = year_match.group(1)
    if "第三支柱" in clean:
        if "第一季度" in clean:
            period = f"{year}Q1"
        elif "半年度" in clean or "中期" in clean:
            period = f"{year}H1"
        elif "第三季度" in clean:
            period = f"{year}Q3"
        elif "年度" in clean:
            period = f"{year}A"
        else:
            return None
        return {"report_period": period, "source_type": "pillar3_report"}
    if ("第一季度" in clean or "一季度报告" in clean) and "报告" in clean:
        return {"report_period": f"{year}Q1", "source_type": "quarterly_report"}
    if ("半年度报告" in clean or "中期报告" in clean) and "摘要" not in clean:
        return {"report_period": f"{year}H1", "source_type": "half_year_report"}
    if ("第三季度" in clean or "三季度报告" in clean) and "报告" in clean:
        return {"report_period": f"{year}Q3", "source_type": "quarterly_report"}
    if re.search(rf"{year}年?年度报告(?:（[^）]+）)?$", clean):
        return {"report_period": f"{year}A", "source_type": "annual_report"}
    return None


def normalize_cninfo_pdf_url(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://static.cninfo.com.cn/{raw.lstrip('/')}"
    parsed = urlparse(raw)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or parsed.hostname != "static.cninfo.com.cn"
            or parsed.username or parsed.password or port not in (None, 443)):
        return None
    return parsed.geturl()


def select_cninfo_reports(announcements: Iterable[Mapping[str, object]], *, symbol: str) -> list[dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    for announcement in announcements:
        if str(announcement.get("secCode") or "").strip() != symbol:
            continue
        classification = classify_cninfo_report_title(str(announcement.get("announcementTitle") or ""))
        if classification is None:
            continue
        report_key = f"{classification['report_period']}:{classification['source_type']}"
        source_url = normalize_cninfo_pdf_url(announcement.get("adjunctUrl"))
        if source_url is None:
            continue
        row: dict[str, object] = {
            **classification,
            "report_key": report_key,
            "announcement_id": str(announcement.get("announcementId") or ""),
            "org_id": str(announcement.get("orgId") or ""),
            "announcement_time": int(announcement.get("announcementTime") or 0),
            "title": re.sub(r"<[^>]+>", "", str(announcement.get("announcementTitle") or "")),
            "source_url": source_url,
        }
        previous = selected.get(report_key)
        if previous is None or int(row["announcement_time"]) >= int(previous["announcement_time"]):
            selected[report_key] = row
    return [selected[key] for key in sorted(selected)]


def extract_labeled_number(
    lines: Iterable[str],
    *,
    aliases: tuple[str, ...],
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict[str, object] | None:
    rows = [str(line or "").strip() for line in lines]
    number_pattern = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
    found: list[dict[str, object]] = []
    for index, raw_label in enumerate(rows):
        alias = next((item for item in aliases if item in raw_label), None)
        if alias is None:
            continue
        compact = re.sub(r"\s+", "", raw_label)
        normalized = re.sub(r"[（(](?:\d+|%)[）)]", "", compact).strip("：:%")
        if re.match(rf"^\d+\s+{re.escape(alias)}", raw_label):
            quality = 110
            include_following = True
        elif normalized == alias:
            quality = 100
            include_following = True
        elif compact.startswith(alias):
            quality = 90
            include_following = True
        elif re.match(rf"^\d+[.、]\s*{re.escape(alias)}", raw_label):
            quality = 70
            include_following = True
        elif any(marker in raw_label for marker in ("截至", "期末", "时点值", "均值", "报告期")):
            quality = 80
            include_following = False
        else:
            quality = 40
            include_following = False

        candidate_texts: list[str] = []
        suffix = raw_label.split(alias, 1)[1]
        suffix = re.sub(r"^[（(]\d+[）)]", "", suffix).strip(" ：:%（）()")
        if suffix:
            candidate_texts.append(suffix)
        if include_following:
            candidate_texts.extend(rows[index + 1:index + 7])

        for text in candidate_texts:
            stripped = text.strip()
            if stripped.startswith(("≥", "≤", ">=", "<=")):
                continue
            selected_value: tuple[float, str] | None = None
            for match in number_pattern.finditer(text):
                try:
                    value = float(match.group(0).replace(",", ""))
                except ValueError:
                    continue
                if 2000 <= value <= 2035 and "." not in match.group(0):
                    continue
                if minimum is not None and value < minimum:
                    continue
                if maximum is not None and value > maximum:
                    continue
                selected_value = (value, match.group(0))
                break
            if selected_value is None:
                continue
            found.append({
                "value": selected_value[0],
                "raw_label": raw_label,
                "raw_value": selected_value[1],
                "quality": quality,
            })
            break
    if not found:
        return None
    found.sort(key=lambda item: int(item["quality"]), reverse=True)
    return found[0]


class FinancialSectorStatusStore:
    """Persist one atomic JSON record per stock plus a derived summary."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.by_symbol_dir = self.root / "by_symbol"
        self.by_symbol_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _symbol(value: object) -> str:
        symbol = str(value or "").strip()
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("symbol must be a six-digit stock code")
        return symbol

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def save_symbol_status(self, payload: Mapping[str, object]) -> dict[str, object]:
        record = dict(payload)
        symbol = self._symbol(record.get("symbol"))
        record["symbol"] = symbol
        record.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        self._atomic_write_json(self.by_symbol_dir / f"{symbol}.json", record)
        return record

    def load_symbol_status(self, symbol: str) -> dict[str, object]:
        normalized = self._symbol(symbol)
        path = self.by_symbol_dir / f"{normalized}.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @contextmanager
    def symbol_lock(self, symbol: str):
        normalized = self._symbol(symbol)
        lock_dir = self.root / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with (lock_dir / f"{normalized}.lock").open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def build_summary(self, expected_symbols: Iterable[str]) -> dict[str, object]:
        symbols = [self._symbol(symbol) for symbol in expected_symbols]
        statuses: Counter[str] = Counter()
        missing = 0
        periods: list[str] = []
        for symbol in symbols:
            record = self.load_symbol_status(symbol)
            status = str(record.get("status") or "").strip()
            if not status:
                missing += 1
                continue
            statuses[status] += 1
            period = str(record.get("latest_announced_period") or "")
            if period:
                periods.append(period)
        summary: dict[str, object] = {
            "total": len(symbols),
            "status_counts": dict(sorted(statuses.items())),
            "missing_status_count": missing,
            "latest_announced_period": max(
                periods,
                key=lambda value: (
                    int(value[:4]),
                    {"Q1": 1, "H1": 2, "Q2": 2, "Q3": 3, "A": 4}.get(value[4:], 0),
                ),
                default=None,
            ),
        }
        self._atomic_write_json(self.root / "current_summary.json", summary)
        return summary


def _process_one_symbol_locked(
    request: Mapping[str, object],
    *,
    processor: Callable[[dict[str, object]], Mapping[str, object]],
    store: FinancialSectorStatusStore,
) -> dict[str, object]:
    symbol = store._symbol(request.get("symbol"))
    current = store.load_symbol_status(symbol)
    work = {**current, **dict(request), "symbol": symbol}
    work["status"] = "processing"
    work["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
    store.save_symbol_status(work)
    try:
        result = dict(processor(dict(work)))
    except ExternalUpdateError as exc:
        failed = {
            **work,
            "status": _failure_status(exc.code),
            "last_error": {"code": exc.code, "message": exc.message},
        }
        store.save_symbol_status(failed)
        return {"ok": False, "symbol": symbol, "error": failed["last_error"]}
    except Exception as exc:
        failed = {
            **work,
            "status": "failed",
            "last_error": {"code": "unexpected_error", "message": str(exc)},
        }
        store.save_symbol_status(failed)
        return {"ok": False, "symbol": symbol, "error": failed["last_error"]}
    published = {**work, **result, "symbol": symbol}
    published.setdefault("status", "up_to_date")
    published["last_success_at"] = datetime.now(timezone.utc).isoformat()
    if published.get("status") == "up_to_date" and "last_error" not in result:
        published["last_error"] = None
    store.save_symbol_status(published)
    return {"ok": True, "symbol": symbol, "status": published.get("status")}


def _process_one_symbol(
    request: Mapping[str, object],
    *,
    processor: Callable[[dict[str, object]], Mapping[str, object]],
    store: FinancialSectorStatusStore,
) -> dict[str, object]:
    symbol = store._symbol(request.get("symbol"))
    with store.symbol_lock(symbol):
        return _process_one_symbol_locked(request, processor=processor, store=store)


def run_symbol_updates(
    requests: Iterable[Mapping[str, object]],
    *,
    processor: Callable[[dict[str, object]], Mapping[str, object]],
    store: FinancialSectorStatusStore,
) -> dict[str, object]:
    results = [_process_one_symbol(request, processor=processor, store=store) for request in requests]
    succeeded = sum(1 for result in results if result.get("ok"))
    return {
        "ok": succeeded == len(results),
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


def retry_symbol_update(
    symbol: str,
    *,
    processor: Callable[[dict[str, object]], Mapping[str, object]],
    store: FinancialSectorStatusStore,
) -> dict[str, object]:
    current = store.load_symbol_status(symbol)
    if not current:
        return {
            "ok": False,
            "symbol": store._symbol(symbol),
            "error": {"code": "status_not_found", "message": "未找到该股票的外部财报更新状态"},
        }
    return _process_one_symbol(current, processor=processor, store=store)
