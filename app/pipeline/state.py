"""Data update job state management."""
import re
import threading
from datetime import datetime

from app.config import DATA_UPDATE_OUTPUT_TAIL_LINES

DATA_UPDATE_LOCK = threading.Lock()
DATA_UPDATE_JOB_STATE_LOCK = threading.Lock()
DATA_UPDATE_JOB_STATE: dict[str, object] = {
    'status': 'idle',
    'running': False,
    'can_retry_failed': False,
    'current_progress_text': '暂无数据更新任务',
}


class DataUpdateStepError(RuntimeError):
    def __init__(
        self,
        step_name: str,
        message: str,
        *,
        returncode: int | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.returncode = returncode
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail


def _tail_lines(text: str | None, limit: int = DATA_UPDATE_OUTPUT_TAIL_LINES) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def _data_update_job_snapshot() -> dict[str, object]:
    with DATA_UPDATE_JOB_STATE_LOCK:
        return dict(DATA_UPDATE_JOB_STATE)


def _update_data_update_job_state(**updates: object) -> dict[str, object]:
    with DATA_UPDATE_JOB_STATE_LOCK:
        DATA_UPDATE_JOB_STATE.update(updates)
        return dict(DATA_UPDATE_JOB_STATE)


def _append_data_update_job_output(line: str) -> None:
    with DATA_UPDATE_JOB_STATE_LOCK:
        lines = list(DATA_UPDATE_JOB_STATE.get('stdout_tail_lines') or [])
        if line.strip():
            lines.append(line.strip())
        DATA_UPDATE_JOB_STATE['stdout_tail_lines'] = lines[-DATA_UPDATE_OUTPUT_TAIL_LINES:]
        DATA_UPDATE_JOB_STATE['stdout_tail'] = "\n".join(DATA_UPDATE_JOB_STATE['stdout_tail_lines'])


def _format_timestamp(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def parse_data_update_progress_line(line: str) -> dict[str, object]:
    text = str(line or "").strip()
    match = re.match(r"^\[(\d+)/(\d+)\]\s+(.+?)\s+(开始构建|完成|失败|跳过)", text)
    if not match:
        return {"last_line": text}
    index = int(match.group(1))
    total = int(match.group(2))
    industry = match.group(3).strip()
    action = match.group(4)
    if action == "开始构建":
        progress_text = f"当前进度：[{index}/{total}] {industry} 正在构建..."
    elif action == "完成":
        progress_text = f"当前进度：[{index}/{total}] {industry} 完成"
    elif action == "跳过":
        progress_text = f"当前进度：[{index}/{total}] {industry} 已跳过"
    else:
        progress_text = f"当前进度：[{index}/{total}] {industry} 失败"
    return {
        "last_line": text,
        "progress_index": index,
        "progress_total": total,
        "current_industry": industry,
        "current_progress_text": progress_text,
    }


def _record_data_update_progress(step_name: str, line: str) -> None:
    _append_data_update_job_output(line)
    parsed = parse_data_update_progress_line(line)
    updates: dict[str, object] = {
        'current_step': step_name,
        'last_line': parsed.get('last_line') or str(line or '').strip(),
    }
    for key in ('progress_index', 'progress_total', 'current_industry', 'current_progress_text'):
        if key in parsed:
            updates[key] = parsed[key]
    if 'current_progress_text' not in updates and updates['last_line']:
        updates['current_progress_text'] = f"当前步骤：{step_name} · {updates['last_line']}"
    _update_data_update_job_state(**updates)
