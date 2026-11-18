"""Completion forecasts based only on measured successful task durations.

The cache stores runtime seconds, never source-data dates or timeout limits. Missing
history, a stalled task and uncertain queue prefixes do not get a clock ETA.
"""

import json
import os
import statistics
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DURATION_HISTORY_PATH = PROJECT_ROOT / 'data' / 'derived' / 'cache' / 'data_update_task_durations.json'
_HISTORY_LOCK = threading.Lock()
_HISTORY_LIMIT = 5


def load_duration_history(path: Path | None = None) -> dict[str, list[int]]:
    target = path or DURATION_HISTORY_PATH
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: [int(value) for value in values[-_HISTORY_LIMIT:]
              if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 86400]
        for key, values in payload.items()
        if isinstance(key, str) and isinstance(values, list)
    }


def _parse_timestamp(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone() if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, OverflowError):
        return None


def record_success_duration(task_id: str, started_at: str | None, finished_at: str | None,
                            *, path: Path | None = None) -> bool:
    """Append one successful sample atomically; invalid timestamps are ignored."""
    start, end = _parse_timestamp(started_at), _parse_timestamp(finished_at)
    if not start or not end:
        return False
    duration = round((end - start).total_seconds())
    if duration <= 0 or duration >= 86400:
        return False
    target = path or DURATION_HISTORY_PATH
    with _HISTORY_LOCK:
        temp_path: Path | None = None
        history = load_duration_history(target)
        history[task_id] = (history.get(task_id, []) + [duration])[-_HISTORY_LIMIT:]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                             prefix='.data-update-eta-', suffix='.tmp',
                                             delete=False) as output:
                temp_path = Path(output.name)
                json.dump(history, output, ensure_ascii=False)
            os.replace(temp_path, target)
        except OSError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return False
    return True


def task_estimates(task_ids: list[str], job: dict, history: dict[str, list[int]],
                   *, now: datetime | None = None) -> dict[str, dict]:
    """Clock ETA for current/full-queue tasks only; idle rows show duration evidence."""
    now = now or datetime.now().astimezone()
    estimates = {}
    states = job.get('task_states') or {}
    for task_id in task_ids:
        samples = history.get(task_id, [])
        duration = round(statistics.median(samples[-_HISTORY_LIMIT:])) if samples else None
        estimates[task_id] = {
            'finish_at': None, 'duration_seconds': duration,
            'samples': len(samples), 'state': 'not_started',
        }
        if not job.get('running'):
            continue
        recorded = states.get(task_id) or {}
        if recorded.get('status') == 'failed':
            estimates[task_id]['state'] = 'failed'
        elif recorded.get('status') == 'done':
            estimates[task_id]['state'] = 'done'

    if not job.get('running'):
        return estimates
    current_id = job.get('current_step')
    if not isinstance(current_id, str) or current_id not in estimates:
        return estimates
    current = estimates[current_id]
    if current['state'] in {'done', 'failed'}:
        return estimates
    start = _parse_timestamp((states.get(current_id) or {}).get('started_at'))
    if not start or not current['duration_seconds']:
        current['state'] = 'no_history' if start else 'not_started'
        return estimates
    finish = start + timedelta(seconds=current['duration_seconds'])
    if finish <= now:
        current['state'] = 'overdue'
        return estimates
    current['state'] = 'running'
    current['finish_at'] = finish.isoformat(timespec='seconds')

    if job.get('mode') != 'full':
        return estimates
    cursor = finish
    for task_id in task_ids[task_ids.index(current_id) + 1:]:
        item = estimates[task_id]
        if item['state'] in {'done', 'failed'}:
            continue
        if not item['duration_seconds']:
            item['state'] = 'no_history'
            break
        cursor += timedelta(seconds=item['duration_seconds'])
        item['finish_at'] = cursor.isoformat(timespec='seconds')
        item['state'] = 'queued'
    return estimates
