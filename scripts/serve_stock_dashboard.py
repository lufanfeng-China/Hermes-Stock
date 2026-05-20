#!/usr/bin/env python3
"""Serve a minimal local dashboard for one stock's daily trend and volume windows."""

from __future__ import annotations

import argparse
import functools
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.industry.heatmap import DEFAULT_INDUSTRY_LIMIT, industry_heatmap_response
from app.relative_valuation.service import build_relative_valuation_result
from app.valuation.models import (
    calc_intrinsic_value_dcf,
    calc_gordon_growth,
    calc_cost_of_equity_capm,
    calc_cost_of_debt,
    calc_wacc,
    calc_tax_rate,
    calc_altman_z_score,
    calc_piotroski_f_score,
    calc_dupont_analysis,
    calc_enterprise_value_breakdown,
    safe_div,
)
from app.search.index import (
    build_stock_screener_response,
    concept_search_response,
    rps_ranking_response,
    stock_profile_response,
    stock_search_response,
    pool_filter_response,
    industry_hierarchy_response,
    concept_list_response,
    load_stock_screener_strategy_rows,
    realtime_screener_response,
)


TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
DEFAULT_SYMBOL = "601600"
DEFAULT_HISTORY_LIMIT = 120
WEB_ROOT = PROJECT_ROOT / "web"
DERIVED_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
STOCK_SCREENER_STRATEGY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_screener_strategies_current.json"
STOCK_RPS_CURRENT_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_current.json"
DEFAULT_HERMES_MODEL = os.environ.get("HERMES_MODEL", "").strip()
DATA_UPDATE_LOCK = threading.Lock()
DATA_UPDATE_JOB_STATE_LOCK = threading.Lock()
DATA_UPDATE_JOB_STATE: dict[str, object] = {
    'status': 'idle',
    'running': False,
    'can_retry_failed': False,
    'current_progress_text': '暂无数据更新任务',
}
DATA_UPDATE_OUTPUT_TAIL_LINES = 8


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


def ensure_stock_screener_strategy_dataset(strategy: str) -> None:
    """Build the stock-screener strategy dataset on demand when a preset needs it."""
    strategy = str(strategy or "").strip()
    if strategy not in {"rps_standard_launch", "rps_attack", "rps_pullback", "rps_first", "ma_cross"}:
        return
    dataset_is_current = (
        STOCK_SCREENER_STRATEGY_DATASET.exists()
        and (
            not STOCK_RPS_CURRENT_DATASET.exists()
            or STOCK_SCREENER_STRATEGY_DATASET.stat().st_mtime >= STOCK_RPS_CURRENT_DATASET.stat().st_mtime
        )
    )
    dataset_has_strategy = False
    if STOCK_SCREENER_STRATEGY_DATASET.exists():
        try:
            payload = json.loads(STOCK_SCREENER_STRATEGY_DATASET.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("rows", [])
            dataset_has_strategy = any(str(row.get("strategy", "")).strip() == strategy for row in rows if isinstance(row, dict))
        except Exception:
            dataset_has_strategy = False
    if dataset_is_current and dataset_has_strategy:
        return
    result = subprocess.run(
        [
            TONGDAXIN_PYTHON,
            str(PROJECT_ROOT / "scripts" / "build_stock_screener_strategies.py"),
            "--strategy",
            strategy,
            "--tdxdir",
            TONGDAXIN_DIR,
            "--output",
            str(STOCK_SCREENER_STRATEGY_DATASET),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(_tail_lines(result.stderr or result.stdout or "strategy build failed"))
    load_stock_screener_strategy_rows.cache_clear()


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


def _industry_template_tags(ind1: str, ind2: str) -> set[str]:
    text = f"{ind1 or ''}/{ind2 or ''}"
    tags: set[str] = set()

    if any(token in text for token in ("保险", "非银金融", "证券", "多元金融")):
        tags.add("nonbank_finance")
    if any(token in text for token in ("银行", "全国性银行", "地方性银行")):
        tags.add("bank")
    if any(token in text for token in ("工业金属", "有色", "钢铁", "建材", "化工", "石油", "煤炭")):
        tags.add("materials_resources")
    if any(token in text for token in ("工业金属", "有色")):
        tags.add("industrial_metal")
    if any(token in text for token in ("食品饮料", "酿酒", "商贸", "轻工制造", "家电", "纺织服饰", "社会服务", "消费")):
        tags.add("consumer")
    if any(token in text for token in ("医药医疗", "医药生物", "化学制药", "中药", "生物制品", "医疗服务", "医疗器械")):
        tags.add("pharma")
    if any(token in text for token in ("电子", "半导体", "计算机", "通信", "传媒")):
        tags.add("tech_media")
    if any(token in text for token in ("半导体", "消费电子")):
        tags.add("semiconductor")
    if any(token in text for token in ("机械设备", "工程机械", "通用设备", "专用设备", "电力设备", "汽车", "国防军工", "建筑", "交通运输")):
        tags.add("cyclical_manufacturing")
    if any(token in text for token in ("公用事业", "环保")):
        tags.add("utilities_env")
    if any(token in text for token in ("农林牧渔", "养殖业", "种植业")):
        tags.add("agriculture")
    if any(token in text for token in ("房地产", "房地产开发", "房产服务")):
        tags.add("real_estate")
    if any(token in text for token in ("综合", "综合类")):
        tags.add("composite")
    return tags


def _build_industry_valuation_percentile_payload(market: str, symbol: str) -> dict[str, object]:
    from app.search.index import _load_financial_snapshot, _stock_name_lookup
    from app.relative_valuation import data_loader as valuation_data_loader
    from app.relative_valuation.labels import classify_percentile_band
    from app.relative_valuation.percentiles import compute_empirical_percentile

    snap = _load_financial_snapshot()
    score_entry = snap.get("scores", {}).get(f"{market}:{symbol}") if snap else {}
    industry_level_2_name = str(score_entry.get("industry_sw_level_2") or "")
    industry_level_1_name = str(score_entry.get("industry_sw_level_1") or "")
    if not industry_level_2_name:
        return {"ok": False, "error": "industry_not_found"}

    stock_name = _stock_name_lookup().get((market, symbol), symbol)
    industry_snapshot = valuation_data_loader.load_industry_valuation_snapshot(industry_level_2_name) or {}
    sample_status = str(industry_snapshot.get("sample_status") or "insufficient")
    members = industry_snapshot.get("member_valuation_rows") or []
    if not members:
        live_members = []
        for member in valuation_data_loader._industry_members(industry_level_2_name):
            row_market = str(member.get("market") or "").strip().lower()
            row_symbol = str(member.get("symbol") or "").strip()
            if not row_market or not row_symbol:
                continue
            stock_inputs = valuation_data_loader.load_stock_relative_valuation_inputs(row_market, row_symbol)
            if not stock_inputs:
                continue
            live_members.append({
                "market": row_market,
                "symbol": row_symbol,
                "stock_name": stock_inputs.get("stock_name") or member.get("stock_name") or row_symbol,
                "current_price": stock_inputs.get("current_price"),
                "total_market_cap": stock_inputs.get("total_market_cap"),
                "free_float_market_cap": stock_inputs.get("free_float_market_cap"),
                "pe_ttm": stock_inputs.get("pe_ttm"),
                "ps_ttm": stock_inputs.get("ps_ttm"),
            })
        members = live_members
    current_stock_member = next(
        (m for m in members if isinstance(m, dict) and m.get("market", "").strip().lower() == market and m.get("symbol", "").strip() == symbol),
        None,
    )

    def positive_float(raw_value):
        value = valuation_data_loader._to_float(raw_value)
        if value is None or value <= 0:
            return None
        return value

    pe_ttm = positive_float(current_stock_member.get("pe_ttm")) if current_stock_member else None
    ps_ttm = positive_float(current_stock_member.get("ps_ttm")) if current_stock_member else None

    relative_payload = build_relative_valuation_result(market, symbol)
    if relative_payload.get("ok"):
        stock_name = str(relative_payload.get("stock_name") or stock_name)
        classification = str(relative_payload.get("classification") or "A_NORMAL_EARNING")
        sub_classification = relative_payload.get("sub_classification")
        primary_metric = str(
            relative_payload.get("primary_percentile_metric")
            or relative_payload.get("primary_metric")
            or "pe_ttm"
        )
        if primary_metric not in {"pe_ttm", "ps_ttm"}:
            primary_metric = "pe_ttm"
        primary_value = valuation_data_loader._to_float(relative_payload.get("primary_percentile_value"))
        if primary_value is not None and primary_value <= 0:
            primary_value = None
        primary_percentile = valuation_data_loader._to_float(relative_payload.get("primary_percentile"))
        valuation_band_label = relative_payload.get("valuation_band_label")
    else:
        classification = "A_NORMAL_EARNING" if pe_ttm is not None else "B_THIN_PROFIT_DISTORTED"
        sub_classification = None
        primary_metric = "pe_ttm" if pe_ttm is not None else "ps_ttm"
        primary_value = pe_ttm if primary_metric == "pe_ttm" else ps_ttm
        primary_percentile = None
        valuation_band_label = None

    if sample_status == "ok" and primary_value is not None:
        sample = valuation_data_loader.load_industry_percentile_sample(
            industry_level_2_name,
            primary_metric,
            classification,
            str(sub_classification) if sub_classification else None,
        ) or []
    else:
        sample = []
    if primary_percentile is None and primary_value is not None and sample:
        primary_percentile = compute_empirical_percentile(primary_value, sample)
    if valuation_band_label is None:
        valuation_band_label = classify_percentile_band(primary_percentile) if primary_percentile is not None else None

    member_rows: list[dict[str, object]] = []
    for vr in members:
        if not isinstance(vr, dict):
            continue
        row_market = str(vr.get("market") or "").strip().lower()
        row_symbol = str(vr.get("symbol") or "").strip()
        if not row_market or not row_symbol:
            continue
        row_pe_ttm = positive_float(vr.get("pe_ttm"))
        row_ps_ttm = positive_float(vr.get("ps_ttm"))
        row_value = row_pe_ttm if primary_metric == "pe_ttm" else row_ps_ttm
        row_percentile = compute_empirical_percentile(row_value, sample) if row_value is not None and sample else None
        row_band = classify_percentile_band(row_percentile) if row_percentile is not None else "估值不可比"
        member_rows.append({
            "stock_name": vr.get("stock_name") or vr.get("symbol") or row_symbol,
            "market": row_market,
            "symbol": row_symbol,
            "current_price": valuation_data_loader._to_float(vr.get("current_price")),
            "ps_ttm": row_ps_ttm,
            "pe_ttm": row_pe_ttm,
            "valuation_metric": primary_metric,
            "valuation_percentile": row_percentile,
            "_percentile_rank": row_percentile,
            "valuation_band": row_band,
            "_band_label": row_band,
            "is_current_stock": row_market == market and row_symbol == symbol,
        })

    member_rows.sort(key=lambda r: (r["valuation_percentile"] is None, r["valuation_percentile"] or 0))
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "industry_level_2_name": industry_level_2_name,
        "industry_level_1_name": industry_level_1_name,
        "classification": classification,
        "sample_status": sample_status,
        "primary_metric": primary_metric,
        "primary_percentile_metric": primary_metric,
        "primary_percentile_value": primary_value,
        "primary_percentile": primary_percentile,
        "valuation_band_label": valuation_band_label,
        "rows": member_rows,
    }


def infer_market(symbol: str) -> tuple[str, int]:
    if symbol.startswith(("60", "68", "90")):
        return "sh", 1
    if symbol.startswith(("00", "30", "20")):
        return "sz", 0
    raise ValueError(f"unsupported symbol prefix for {symbol}")


def _format_timestamp(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def load_data_update_status() -> dict[str, object]:
    financial_candidates = sorted(DERIVED_FINAL_DIR.glob('financial_snapshot_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    financial_snapshot = None
    latest_timestamps: list[float] = []
    if financial_candidates:
        latest = financial_candidates[0]
        try:
            payload = json.loads(latest.read_text(encoding='utf-8'))
        except Exception:
            payload = {}
        latest_timestamps.append(latest.stat().st_mtime)
        financial_snapshot = {
            'path': str(latest),
            'report_date': payload.get('report_date'),
            'updated_at': _format_timestamp(latest.stat().st_mtime),
        }

    industry_path = DERIVED_FINAL_DIR / 'dataset_industry_valuation_current.json'
    industry_valuation = None
    if industry_path.exists():
        try:
            rows = json.loads(industry_path.read_text(encoding='utf-8'))
            industry_count = len(rows) if isinstance(rows, list) else None
            member_valuation_row_count = 0
            member_valuation_industry_count = 0
            complete_member_valuation_industry_count = 0
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    member_rows = row.get('member_valuation_rows')
                    if isinstance(member_rows, list):
                        member_valuation_industry_count += 1
                        member_valuation_row_count += len(member_rows)
                        if member_rows:
                            complete_member_valuation_industry_count += 1
        except Exception:
            industry_count = None
            member_valuation_row_count = None
            member_valuation_industry_count = None
            complete_member_valuation_industry_count = None
        latest_timestamps.append(industry_path.stat().st_mtime)
        industry_valuation = {
            'path': str(industry_path),
            'updated_at': _format_timestamp(industry_path.stat().st_mtime),
            'industry_count': industry_count,
            'member_valuation_row_count': member_valuation_row_count,
            'member_valuation_industry_count': member_valuation_industry_count,
            'complete_member_valuation_industry_count': complete_member_valuation_industry_count,
        }

    return {
        'ok': True,
        'financial_snapshot': financial_snapshot,
        'industry_valuation': industry_valuation,
        'data_update_job': _data_update_job_snapshot(),
        'latest_updated_at': _format_timestamp(max(latest_timestamps)) if latest_timestamps else None,
    }


def _latest_trading_day_for_refresh() -> str | None:
    try:
        search_index = importlib.import_module('app.search.index')
        snapshot = search_index._load_latest_daily_snapshot('sh', DEFAULT_SYMBOL)
        trading_day = str(snapshot.get('trading_day') or '').strip()
        if trading_day:
            return trading_day
    except Exception:
        return None
    return None


def _is_allowed_local_origin(origin: str | None, referer: str | None = None) -> bool:
    candidates = [str(origin or '').strip(), str(referer or '').strip()]
    for text in candidates:
        if not text:
            continue
        try:
            parsed = urlparse(text)
        except Exception:
            continue
        hostname = (parsed.hostname or '').strip().lower()
        if hostname in {'127.0.0.1', 'localhost'}:
            return True
    return False


def clear_runtime_data_caches() -> None:
    module_names = [
        'app.search.index',
        'app.relative_valuation.data_loader',
        'app.relative_valuation.history',
    ]
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            cache_clear = getattr(attr, 'cache_clear', None)
            if callable(cache_clear):
                try:
                    cache_clear()
                except Exception:
                    continue


def _data_update_commands(trading_day: str | None, retry_failed: bool = False) -> list[tuple[str, list[str]]]:
    if retry_failed:
        return [(
            'build_industry_relative_valuation_snapshot',
            [
                TONGDAXIN_PYTHON,
                str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py'),
                '--reuse-existing-complete',
            ],
        )]
    commands: list[tuple[str, list[str]]] = []
    if trading_day:
        commands.append((
            'archive_daily',
            [
                TONGDAXIN_PYTHON,
                str(PROJECT_ROOT / 'scripts/archive_daily.py'),
                '--trading-day',
                trading_day,
                '--force-rerun',
                '--rerun-reason',
                'manual-dashboard-refresh',
            ],
        ))
    commands.extend([
        ('update_financial_ts', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/update_financial_ts.py')]),
        ('build_financial_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_financial_snapshot_from_warehouse.py'), 'latest']),
        ('build_industry_relative_valuation_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py')]),
        (
            'build_rps_history',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_rps_history.py'), '--ndays', '120'],
        ),
        (
            'rebuild_screener_standard_launch',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_standard_launch', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_attack',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_attack', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_pullback',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_pullback', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_first',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_first', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_ma_cross',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'ma_cross', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
    ])
    return commands


def _run_data_update_command(
    step_name: str,
    command: list[str],
    progress_callback=None,
) -> SimpleNamespace:
    if progress_callback is None:
        return subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=1800,
        )
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_text = ""
    try:
        assert process.stdout is not None
        for line in process.stdout:
            stdout_lines.append(line)
            progress_callback(step_name, line.rstrip('\n'))
        stderr_text = process.stderr.read() if process.stderr is not None else ""
        returncode = process.wait(timeout=1800)
    except Exception:
        process.kill()
        raise
    return SimpleNamespace(returncode=returncode, stdout="".join(stdout_lines), stderr=stderr_text)


def run_full_data_update(progress_callback=None, retry_failed: bool = False) -> dict[str, object]:
    trading_day = _latest_trading_day_for_refresh()
    steps: list[dict[str, object]] = []
    commands = _data_update_commands(trading_day, retry_failed=retry_failed)

    for step_name, command in commands:
        try:
            result = _run_data_update_command(step_name, command, progress_callback=progress_callback)
        except subprocess.TimeoutExpired as exc:
            stdout_tail = _tail_lines(exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout)
            stderr_tail = _tail_lines(exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr)
            steps.append({
                'name': step_name,
                'command': ' '.join(command),
                'ok': False,
                'returncode': None,
                'stdout_tail': stdout_tail,
                'stderr_tail': stderr_tail,
                'timed_out': True,
            })
            raise DataUpdateStepError(
                step_name,
                f'{step_name} 超时（超过 1800 秒），数据更新已停止或失败',
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            ) from exc
        stdout_tail = _tail_lines(result.stdout)
        stderr_tail = _tail_lines(result.stderr)
        steps.append({
            'name': step_name,
            'command': ' '.join(command),
            'ok': result.returncode == 0,
            'returncode': result.returncode,
            'stdout_tail': stdout_tail,
            'stderr_tail': stderr_tail,
        })
        if result.returncode != 0:
            raise DataUpdateStepError(
                step_name,
                f'{step_name} 数据更新已停止或失败（exit code {result.returncode}）',
                returncode=result.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

    clear_runtime_data_caches()
    _load_rps_history_dataset.cache_clear()
    return {
        'ok': True,
        'steps': steps,
        'data_update_status': load_data_update_status(),
    }


def _run_data_update_worker(retry_failed: bool = False) -> None:
    try:
        result = run_full_data_update(progress_callback=_record_data_update_progress, retry_failed=retry_failed)
        status_payload = result.get('data_update_status') if isinstance(result, dict) else {}
        _update_data_update_job_state(
            status='succeeded',
            running=False,
            can_retry_failed=False,
            finished_at=_format_timestamp(time.time()),
            current_progress_text='数据更新完成',
            data_update_status=status_payload,
        )
    except Exception as exc:
        updates: dict[str, object] = {
            'status': 'failed',
            'running': False,
            'can_retry_failed': True,
            'finished_at': _format_timestamp(time.time()),
            'current_progress_text': '数据更新已停止或失败，可点击“重试失败项”继续',
            'error': str(exc),
        }
        if isinstance(exc, DataUpdateStepError):
            updates.update({
                'failed_step': exc.step_name,
                'returncode': exc.returncode,
                'stdout_tail': exc.stdout_tail,
                'stderr_tail': exc.stderr_tail,
            })
        _update_data_update_job_state(**updates)
    finally:
        try:
            DATA_UPDATE_LOCK.release()
        except RuntimeError:
            pass


def start_data_update_job(retry_failed: bool = False) -> dict[str, object]:
    if not DATA_UPDATE_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': {'code': 'data_update_busy', 'message': '已有数据更新任务在运行中'}}
    now = _format_timestamp(time.time())
    _update_data_update_job_state(
        status='running',
        running=True,
        mode='retry_failed' if retry_failed else 'full',
        can_retry_failed=False,
        started_at=now,
        finished_at=None,
        current_step='init',
        current_industry=None,
        progress_index=None,
        progress_total=None,
        current_progress_text='当前进度：正在准备数据更新...',
        error=None,
        stdout_tail='',
        stderr_tail='',
        stdout_tail_lines=[],
    )
    thread = threading.Thread(target=_run_data_update_worker, kwargs={'retry_failed': retry_failed}, daemon=True)
    thread.start()
    payload = load_data_update_status()
    payload['started'] = True
    return payload


def load_stock_history(symbol: str, history_limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, object]:
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
suffix = int(sys.argv[3])
tdxdir = sys.argv[4]
history_limit = int(sys.argv[5])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)
minute = reader.minute(symbol=symbol, suffix=suffix)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")
if minute is None or minute.empty:
    raise RuntimeError("minute data not found")

minute = minute.copy()
minute["trading_day"] = minute.index.strftime("%Y-%m-%d")
window_specs = {
    "open_15m_volume": ("09:31:00", "09:45:00"),
    "window_1430_1445_volume": ("14:30:00", "14:45:00"),
}
by_day = {}
for trading_day, day_frame in minute.groupby("trading_day", sort=True):
    metrics = {}
    timestamps = day_frame.index.strftime("%H:%M:%S")
    for indicator_name, (start_ts, end_ts) in window_specs.items():
        selected = day_frame.loc[(timestamps >= start_ts) & (timestamps <= end_ts)]
        metrics[indicator_name] = {
            "volume": int(selected["volume"].fillna(0).sum()),
            "bar_count": int(selected.shape[0]),
        }
    by_day[trading_day] = metrics

rows = []
for index, row in daily.sort_index().iterrows():
    trading_day = index.strftime("%Y-%m-%d")
    metrics = by_day.get(trading_day)
    if not metrics:
        continue
    rows.append(
        {
            "trading_day": trading_day,
            "close": round(float(row["close"]), 4),
            "open_15m_volume": metrics["open_15m_volume"]["volume"],
            "open_15m_bar_count": metrics["open_15m_volume"]["bar_count"],
            "window_1430_1445_volume": metrics["window_1430_1445_volume"]["volume"],
            "window_1430_1445_bar_count": metrics["window_1430_1445_volume"]["bar_count"],
        }
    )

if not rows:
    raise RuntimeError("no overlapping daily/minute history found")

rows = rows[-history_limit:]
latest = rows[-1]
payload = {
    "ok": True,
    "symbol": symbol,
    "market": market,
    "history_limit": history_limit,
    "latest_trading_day": latest["trading_day"],
    "latest_metrics": {
        "open_15m_volume": latest["open_15m_volume"],
        "open_15m_bar_count": latest["open_15m_bar_count"],
        "window_1430_1445_volume": latest["window_1430_1445_volume"],
        "window_1430_1445_bar_count": latest["window_1430_1445_bar_count"],
        "close": latest["close"],
    },
    "history": rows,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [
            TONGDAXIN_PYTHON,
            "-c",
            script,
            symbol,
            market,
            str(suffix),
            TONGDAXIN_DIR,
            str(history_limit),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "unknown subprocess error").strip()
        raise RuntimeError(stderr)
    return json.loads(result.stdout)


def load_stock_kline(symbol: str, *, limit: int = 250) -> dict[str, object]:
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
suffix = int(sys.argv[3])
tdxdir = sys.argv[4]
limit = int(sys.argv[5])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")

rows = []
for index, row in daily.sort_index().tail(limit).iterrows():
    rows.append({
        "trading_day": index.strftime("%Y-%m-%d"),
        "open": round(float(row["open"]), 2),
        "high": round(float(row["high"]), 2),
        "low": round(float(row["low"]), 2),
        "close": round(float(row["close"]), 2),
        "volume": int(row["volume"]) if not (row["volume"] != row["volume"]) else 0,
    })

print(json.dumps({"ok": True, "symbol": symbol, "market": market, "bars": rows}, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [TONGDAXIN_PYTHON, "-c", script, symbol, market, str(suffix), TONGDAXIN_DIR, str(limit)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mootdx subprocess error")
    return json.loads(result.stdout)


def compute_stock_price_percentile(
    market: str, symbol: str, *, years: int = 5
) -> dict[str, object]:
    """
    Compute where the latest close sits in the stock's own N-year price history.

    Uses all available local .day records from TDX up to `years`, then computes
    empirical percentile = % of historical closes <= latest close.
    Returns bands: 极低(<20%) / 低(20-40%) / 中(40-60%) / 高(60-80%) / 极高(>80%).
    """
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    if market not in {"sh", "sz", "bj"}:
        raise ValueError(f"unsupported market: {market}")

    import subprocess as _subprocess

    script = r"""
import json, sys, statistics, pandas as pd

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
tdxdir = sys.argv[3]
years  = int(sys.argv[4])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily  = reader.daily(symbol=symbol)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found for " + symbol)

daily.index = daily.index.astype("datetime64[ns]")
daily = daily.sort_index()

# Keep only the last N years
cutoff = daily.index[-1] - pd.DateOffset(years=years)
recent = daily[daily.index >= cutoff].copy()

if len(recent) < 30:
    raise RuntimeError(f"only {len(recent)} trading days in {years}-year window for {symbol}")

prices = recent["close"].dropna().tolist()
latest  = prices[-1]

# Empirical percentile
below  = sum(1 for p in prices if p <= latest)
pct    = below / len(prices) * 100

if   pct < 20: band = "极低"
elif pct < 40: band = "低"
elif pct < 60: band = "中"
elif pct < 80: band = "高"
else:          band = "极高"

# Also compute min/max/mean/std
mean_price = statistics.mean(prices)
std_price  = statistics.stdev(prices) if len(prices) > 1 else 0

print(json.dumps({
    "ok": True,
    "symbol": symbol,
    "market": market,
    "years": years,
    "bar_count": len(prices),
    "window_start": str(recent.index[0].date()),
    "window_end":   str(recent.index[-1].date()),
    "latest_close": round(float(latest), 2),
    "price_percentile": round(pct, 2),
    "price_band": band,
    "price_min":  round(float(min(prices)), 2),
    "price_max":  round(float(max(prices)), 2),
    "price_mean": round(float(mean_price), 2),
    "price_std":  round(float(std_price), 2),
}, ensure_ascii=False))
""".strip()

    result = _subprocess.run(
        ["/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python", "-c", script,
         symbol, market, "/mnt/c/new_tdx64", str(years)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mootdx error")
    return json.loads(result.stdout)


STOCK_RPS_HISTORY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_history.json"
CAPITAL_FLOW_CACHE = PROJECT_ROOT / "data" / "derived" / "cache" / "capital_flow" / "capital_flow_full.json"


@functools.lru_cache(maxsize=1)
def _load_rps_history_dataset() -> list[dict[str, object]]:
    """Load the precomputed cross-sectional RPS history dataset (cached in memory)."""
    if not STOCK_RPS_HISTORY_DATASET.exists():
        return []
    return json.loads(STOCK_RPS_HISTORY_DATASET.read_text(encoding="utf-8"))


def load_stock_rps_history(symbol: str) -> dict[str, object]:
    """Return cross-sectional RPS history for one stock from the precomputed dataset."""
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    market, _suffix = infer_market(symbol)

    all_rows = _load_rps_history_dataset()
    history = [
        {
            "trading_day": str(row.get("trading_day", "")),
            "rps_20": row.get("rps_20"),
            "rps_50": row.get("rps_50"),
            "rps_120": row.get("rps_120"),
            "rps_250": row.get("rps_250"),
        }
        for row in all_rows
        if row.get("symbol") == symbol and row.get("market") == market
    ]
    history.sort(key=lambda item: str(item.get("trading_day", "")))
    return {"ok": True, "symbol": symbol, "market": market, "history": history}


def load_recent_three_year_financial_reports(market: str, symbol: str) -> dict[str, object]:
    search_index = importlib.import_module("app.search.index")

    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"}:
        raise ValueError("market must be sh, sz or bj")
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    def row_matches(row_symbol: str) -> bool:
        row_symbol = str(row_symbol).strip()
        if row_symbol != symbol:
            return False
        if market == "sh":
            return row_symbol.startswith(("5", "6", "9"))
        if market == "sz":
            return row_symbol.startswith(("0", "1", "2", "3", "4", "8"))
        return row_symbol.startswith(("4", "8", "9"))

    matched_reports: list[dict[str, object]] = []
    stock_name = search_index._stock_name_lookup().get((market, symbol), "")
    latest_year: int | None = None
    earliest_year: int | None = None

    for report_date, fp in search_index._all_financial_files():
        report_year = int(str(report_date or "0")[:4] or "0")
        if earliest_year is not None and report_year < earliest_year:
            break
        loaded = search_index._load_file(fp)
        if loaded is None:
            continue
        _date_str, df = loaded

        matched_row = None
        for row_symbol, row in df.iterrows():
            if row_matches(str(row_symbol)):
                matched_row = row
                break
        if matched_row is None:
            continue

        period_label = _report_date_to_period_label(str(report_date))
        announce_raw = matched_row.get("announce_date") if hasattr(matched_row, "get") else None
        announce_date = ""
        try:
            picked_announce = search_index._pick(announce_raw)
            if picked_announce is not None:
                announce_date = str(int(picked_announce))
        except (TypeError, ValueError):
            announce_date = str(announce_raw or "").strip()

        matched_reports.append(
            {
                "report_date": str(report_date),
                "announce_date": announce_date,
                "year": str(report_date)[:4],
                "period": period_label,
                "row": matched_row,
            }
        )
        if latest_year is None:
            latest_year = report_year
            earliest_year = latest_year - 2

    if not matched_reports:
        raise ValueError(f"no recent financial reports found for {market}:{symbol}")

    matched_reports.sort(key=lambda row: str(row.get("report_date") or ""), reverse=True)
    latest_report_seed = matched_reports[0]
    latest_period_label = str(latest_report_seed.get("period") or "")
    latest_year = int(str(latest_report_seed.get("year") or "0")[:4] or "0")
    earliest_year = latest_year - 2 if latest_year else 0
    filtered_rows = [
        row for row in matched_reports
        if int(str(row.get("year") or "0")[:4] or "0") >= earliest_year
    ]
    reports = [_materialize_financial_report(search_index, row) for row in filtered_rows]
    reports.sort(key=lambda row: str(row.get("report_date") or ""))
    latest_report = reports[-1] if reports else None

    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "latest_report": latest_report,
        "latest_period_label": latest_period_label,
        "reports": reports,
    }


def _report_date_to_period_label(report_date: str) -> str:
    text = str(report_date or "").strip()
    if len(text) != 8 or not text.isdigit():
        return text
    year = text[:4]
    month_day = text[4:]
    mapping = {
        "0331": "Q1",
        "0630": "Q2",
        "0930": "Q3",
        "1231": "A",
    }
    suffix = mapping.get(month_day)
    if not suffix:
        return text
    return f"{year}{suffix}"


def _extract_period_quarter(period_label: str) -> str:
    text = str(period_label or "").strip().upper()
    match = re.match(r"^\d{4}(Q[1-4]|A)$", text)
    return match.group(1) if match else ""


def _materialize_financial_report(search_index, seed: dict[str, object]) -> dict[str, object]:
    matched_row = seed.get("row")
    derived = search_index._derive_sub_fields(matched_row, None)
    metrics = {
        "revenue": search_index._pick(matched_row.get("营业收入")),
        "net_profit": search_index._pick(matched_row.get("归属于母公司所有者的净利润")),
        "ex_net_profit": search_index._pick(matched_row.get("扣除非经常性损益后的净利润")),
        "ocf": search_index._pick(matched_row.get("经营活动产生的现金流量净额")),
        "roe_ex": derived.get("roe_ex"),
        "debt_ratio": derived.get("debt_ratio"),
        "current_ratio": derived.get("current_ratio"),
        "quick_ratio": derived.get("quick_ratio"),
        "profit_growth": derived.get("profit_growth"),
        "revenue_growth": derived.get("revenue_growth"),
        "ex_profit_growth": derived.get("ex_profit_growth"),
        "ocf_to_profit": derived.get("ocf_to_profit"),
        "free_cf": derived.get("free_cf"),
    }
    return {
        "report_date": seed.get("report_date"),
        "announce_date": seed.get("announce_date"),
        "year": seed.get("year"),
        "period": seed.get("period"),
        "metrics": metrics,
    }


def build_ai_financial_report_prompt(
    *,
    stock_name: str,
    market: str,
    symbol: str,
    reports: list[dict[str, object]],
    latest_report: dict[str, object] | None = None,
) -> str:
    latest = latest_report or (reports[-1] if reports else None)
    report_blob = json.dumps(reports, ensure_ascii=False, indent=2)
    latest_blob = json.dumps(latest, ensure_ascii=False, indent=2)
    return (
        f"你是一名A股财报分析师。请基于 {stock_name}（{market}:{symbol}）最近3年财报数据，"
        "输出严格 JSON，不要输出任何额外说明。\n"
        "解读逻辑必须以最新一期财报为主，优先与上年同期比较；只有在完成上年同期比较后，才把更早历史作为辅助验证，不要把历史数据当成主结论。\n"
        "请重点覆盖：总体评价、财报亮点、风险警示、加分项、减分项。\n"
        "JSON 字段必须且只能包含：overall, highlights, risks, positive_factors, negative_factors。\n"
        "其中 overall 为字符串，其余字段为字符串数组；内容使用简洁中文。\n"
        "请明确关注最新一期的营收同比、净利润同比、扣非同比，以及少量质量指标如扣非ROE、资产负债率、流动比率。\n"
        "若最新一期是季度报告，请先对比上年同期（例如 2026Q1 先比 2025Q1），再参考更早同季度或前后报告期；若最新一期是年报，也要优先与上年同期年报比较。\n"
        "你会收到 latest_report 和 reports 两部分：latest_report 是主分析对象，reports 是最近3年完整报告期时间线（按时间顺序）。\n"
        f"latest_report:\n{latest_blob}\n"
        "reports:\n"
        f"{report_blob}\n"
        "请返回 JSON。"
    )


def load_sub_indicator_score_context(market: str, symbol: str) -> dict[str, object]:
    search_index = importlib.import_module("app.search.index")

    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"}:
        raise ValueError("market must be sh, sz or bj")
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    return search_index.compute_stock_score(market, symbol)


def build_sub_indicator_explanation_prompt(
    *,
    stock_name: str,
    market: str,
    symbol: str,
    sub_key: str,
    diagnostic: dict[str, object],
    latest_report: dict[str, object] | None,
    reports: list[dict[str, object]],
    ind1: str = "",
    ind2: str = "",
) -> str:
    indicator_name = str(diagnostic.get("indicator_name") or sub_key).strip() or sub_key
    diagnostic_blob = json.dumps(diagnostic, ensure_ascii=False, indent=2)
    latest_blob = json.dumps(latest_report or {}, ensure_ascii=False, indent=2)
    report_blob = json.dumps(reports, ensure_ascii=False, indent=2)
    industry_context = " / ".join([part for part in [str(ind1 or "").strip(), str(ind2 or "").strip()] if part]) or "未提供行业标签"
    return (
        f"你是一名A股财报分析师。请只解释 {stock_name}（{market}:{symbol}）的单个财务指标 {indicator_name}（sub_key={sub_key}），"
        "输出严格 JSON，不要输出任何额外说明。\n"
        "默认不要分析其他指标，不要扩展到公司整体结论，只围绕这一个指标的变化、归因、影响、可能原因与验证重点作答。\n"
        "分析顺序必须先看最新一期 latest_report，再优先对比上年同期（同季度对同季度、年报对上年年报），再把 reports 里的更早历史作为辅助验证。\n"
        "请明确使用 change、attribution、impact、latest_report、reports 这些上下文，并把最新一期放在最前面。\n"
        "请特别关注：变化、归因、影响、可能原因、验证重点。\n"
        "输出必须是终端风格短句：一句结论 + 若干条原因/验证短句，不要写成长段分析。\n"
        "不要照抄 latest_report、change、attribution、impact、reports 这些字段名；直接写中文结论。\n"
        "单条尽量不超过 24 个汉字；优先使用动宾短句、判断短句、研究终端口吻。\n"
        "JSON 字段必须且只能包含：summary, hypotheses, validation_focus, confidence。\n"
        "其中 summary 为字符串；hypotheses 与 validation_focus 为字符串数组；confidence 为字符串，只能使用 low / medium / high。\n"
        "如果现有证据不足，请在 hypotheses 和 validation_focus 中直接说明要核查的公告、附注或业务口径；不要编造未提供的数据。\n"
        f"行业上下文: {industry_context}\n"
        "若行业标签显示保险/非银金融，请优先使用保费收现、赔付支出、投资收付、负债久期等行业表达。\n"
        "若行业标签显示工业金属，请优先使用金属价格、库存周期、产销节奏、在途库存等行业表达。\n"
        "latest_report:\n"
        f"{latest_blob}\n"
        "reports:\n"
        f"{report_blob}\n"
        "sub_indicator_diagnostic:\n"
        f"{diagnostic_blob}\n"
        "请返回 JSON。"
    )


def generate_stock_ai_report(market: str, symbol: str) -> dict[str, object]:
    history = load_recent_three_year_financial_reports(market, symbol)
    prompt = build_ai_financial_report_prompt(
        stock_name=str(history.get("stock_name") or symbol),
        market=str(history.get("market") or market),
        symbol=str(history.get("symbol") or symbol),
        reports=list(history.get("reports") or []),
        latest_report=history.get("latest_report"),
    )

    command = [
        "hermes",
        "chat",
        "-Q",
        "--ignore-rules",
        "--source",
        "tool",
    ]
    if DEFAULT_HERMES_MODEL:
        command.extend(["-m", DEFAULT_HERMES_MODEL])
    command.extend(["-q", prompt])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "hermes command failed").strip())

    stdout = (result.stdout or "").strip()
    match = re.search(r"(\{.*\})", stdout, re.DOTALL)
    if not match:
        raise RuntimeError("hermes output did not contain JSON")

    parsed = json.loads(match.group(1))

    def _normalize_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        return [str(item).strip() for item in items if str(item).strip()]

    analysis = {
        "overall": str(parsed.get("overall") or "").strip(),
        "highlights": _normalize_list(parsed.get("highlights")),
        "risks": _normalize_list(parsed.get("risks")),
        "positive_factors": _normalize_list(parsed.get("positive_factors")),
        "negative_factors": _normalize_list(parsed.get("negative_factors")),
    }
    return {
        "ok": True,
        "market": history["market"],
        "symbol": history["symbol"],
        "stock_name": history["stock_name"],
        "report_count": len(history["reports"]),
        "latest_report": history.get("latest_report"),
        "latest_period_label": history.get("latest_period_label"),
        "reports": history["reports"],
        "analysis": analysis,
    }


def generate_sub_indicator_ai_explanation(market: str, symbol: str, sub_key: str) -> dict[str, object]:
    history = load_recent_three_year_financial_reports(market, symbol)
    score_context = load_sub_indicator_score_context(market, symbol)
    diagnostics = score_context.get("sub_indicator_diagnostics") or {}
    diagnostic = diagnostics.get(sub_key)
    if not diagnostic:
        raise ValueError(f"invalid sub_key for {market}:{symbol}: {sub_key}")

    prompt = build_sub_indicator_explanation_prompt(
        stock_name=str(score_context.get("stock_name") or history.get("stock_name") or symbol),
        market=str(score_context.get("market") or history.get("market") or market),
        symbol=str(score_context.get("symbol") or history.get("symbol") or symbol),
        sub_key=sub_key,
        diagnostic=diagnostic,
        latest_report=history.get("latest_report"),
        reports=list(history.get("reports") or []),
        ind1=str(score_context.get("ind1") or ""),
        ind2=str(score_context.get("ind2") or ""),
    )

    command = [
        "hermes",
        "chat",
        "-Q",
        "--ignore-rules",
        "--source",
        "tool",
    ]
    if DEFAULT_HERMES_MODEL:
        command.extend(["-m", DEFAULT_HERMES_MODEL])
    command.extend(["-q", prompt])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "hermes command failed").strip())

    stdout = (result.stdout or "").strip()
    match = re.search(r"(\{.*\})", stdout, re.DOTALL)
    if not match:
        raise RuntimeError("hermes output did not contain JSON")

    parsed = json.loads(match.group(1), strict=False)

    def _short_terminal_line(value: object, *, limit: int = 24, keep_terminal_punctuation: bool = True) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^(latest_report|change|attribution|impact|reports|summary|hypotheses|validation_focus)\s*[:：-]\s*", "", text, flags=re.IGNORECASE)
        if not text:
            return ""
        head_match = re.match(r"^(.*?)([；;。.!?]|$)", text)
        head = (head_match.group(1) if head_match else text).strip(" ，、;；:：")
        suffix = head_match.group(2) if head_match else ""
        if not keep_terminal_punctuation and any(sep in head for sep in ("，", ",", "、")):
            head = re.split(r"[，,、]", head, maxsplit=1)[0].strip(" ，、;；:：")
        if not keep_terminal_punctuation and "与" in head:
            head = head.split("与", 1)[0].strip(" ，、;；:：")
        if len(head) > limit:
            truncated = head[:limit].rstrip(" ，、;；:：")
            if keep_terminal_punctuation:
                split_points = [truncated.rfind(sep) for sep in ("，", ",", "、")]
                split_points = [pos for pos in split_points if pos > 0]
                if split_points:
                    truncated = truncated[:max(split_points)].rstrip(" ，、;；:：")
            head = truncated
        if keep_terminal_punctuation and suffix in {"。", "！", "？"} and head:
            return f"{head}{suffix}"
        return head

    def _normalize_list(value: object, *, limit: int = 24) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        normalized = []
        for item in items:
            text = _short_terminal_line(item, limit=limit, keep_terminal_punctuation=False)
            if text:
                normalized.append(text)
        return normalized

    def _summary_unit(sub_key_name: str) -> str:
        return {
            "roe_ex": "%",
            "net_margin": "%",
            "roe_pct": "%",
            "revenue_growth": "%",
            "profit_growth": "%",
            "ex_profit_growth": "%",
            "ar_days": "天",
            "inv_days": "天",
            "asset_turn": "次",
            "ocf_to_profit": "倍",
            "ocf_to_rev": "%",
            "debt_ratio": "%",
            "current_ratio": "倍",
            "quick_ratio": "倍",
            "ar_to_asset": "%",
            "inv_to_asset": "%",
            "goodwill_ratio": "%",
            "impair_to_rev": "%",
        }.get(sub_key_name, "")

    def _polish_summary_text(text: object, sub_key_name: str, latest_period_label: str) -> str:
        summary = _short_terminal_line(text, limit=30)
        if not summary:
            return ""
        summary = re.sub(r"(?<!\d)(\d{2})Q([1-4])", r"20\1Q\2", summary)
        if latest_period_label:
            short_period = latest_period_label[2:] if len(latest_period_label) == 6 else ""
            if short_period and short_period in summary and latest_period_label not in summary:
                summary = summary.replace(short_period, latest_period_label)
        unit = _summary_unit(sub_key_name)
        if unit:
            match_num_tail = re.search(r"(\d+(?:\.\d+)?)([。！？]?)$", summary)
            if match_num_tail:
                number = match_num_tail.group(1)
                punct = match_num_tail.group(2) or "。"
                prefix = summary[: match_num_tail.start(1)]
                summary = f"{prefix}{number}{unit}{punct}"
        elif summary[-1] not in "。！？":
            summary = f"{summary}。"
        return summary

    def _canonical_terminal_item(value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^(核对|查看|跟踪|补齐|对比|核查|关注)", "", text)
        return text.strip(" ，、;；:：")

    def _compress_terminal_items(items: list[str], *, limit: int = 18, max_items: int = 4) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = _short_terminal_line(item, limit=limit, keep_terminal_punctuation=False)
            canonical = _canonical_terminal_item(text)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            out.append(canonical)
            if len(out) >= max_items:
                break
        return out

    def _prepend_unique(items: list[str], extras: list[str], *, limit: int = 18) -> list[str]:
        return _compress_terminal_items(extras + items, limit=limit, max_items=8)

    def _apply_industry_short_templates(explanation: dict[str, object]) -> dict[str, object]:
        ind1_text = str(score_context.get("ind1") or "")
        ind2_text = str(score_context.get("ind2") or "")
        latest_period_label = str(score_context.get("latest_period") or history.get("latest_period_label") or history.get("latest_report", {}).get("period") or "")
        industry_text = f"{ind1_text}/{ind2_text}"
        industry_tags = _industry_template_tags(ind1_text, ind2_text)
        hypotheses = list(explanation.get("hypotheses") or [])
        validation_focus = list(explanation.get("validation_focus") or [])
        summary = str(explanation.get("summary") or "")

        if "nonbank_finance" in industry_tags:
            if sub_key == "free_cf":
                hypotheses = _prepend_unique(hypotheses, ["投资收付", "保费收现节奏"])
                validation_focus = _prepend_unique(validation_focus, ["保费收现", "赔付支出", "投资收付"])
                if "保险" in ind2_text and summary and "保险" not in summary:
                    summary = _short_terminal_line(f"保险资金口径下，{summary}", limit=30)
            elif sub_key in {"roe_ex", "roe_pct"}:
                hypotheses = _prepend_unique(hypotheses, ["投资收益波动", "资本消耗变化"])
                validation_focus = _prepend_unique(validation_focus, ["投资收益变动", "资本约束"])

        if "bank" in industry_tags:
            if sub_key in {"asset_turn", "revenue_growth", "profit_growth", "ex_profit_growth", "roe_ex", "roe_pct"}:
                hypotheses = _prepend_unique(hypotheses, ["息差", "资产扩张"])
                validation_focus = _prepend_unique(validation_focus, ["存贷", "净息差"])
                if summary and "银行" not in summary:
                    summary = _short_terminal_line(f"银行口径下，{summary}", limit=30)
            elif sub_key in {"current_ratio", "quick_ratio", "debt_ratio"}:
                hypotheses = _prepend_unique(hypotheses, ["负债成本", "资产久期"])
                validation_focus = _prepend_unique(validation_focus, ["负债久期", "资本充足率"])

        if "industrial_metal" in industry_tags:
            if sub_key in {"inv_to_asset", "inv_days"}:
                hypotheses = _prepend_unique(hypotheses, ["金属价格", "库存周期"])
                validation_focus = _prepend_unique(validation_focus, ["产销节奏", "库存附注"])
                if "工业金属" in ind2_text and summary and "工业金属" not in summary:
                    summary = _short_terminal_line(f"工业金属链条里，{summary}", limit=30)
            elif sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["金属价格波动", "加工费变化"])
                validation_focus = _prepend_unique(validation_focus, ["量价拆分", "产销节奏"])

        if "consumer" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "net_margin"}:
                hypotheses = _prepend_unique(hypotheses, ["渠道动销", "提价节奏"])
                validation_focus = _prepend_unique(validation_focus, ["终端动销", "渠道库存"])
                if summary and not any(token in summary for token in ("消费", "白酒", "食品饮料")):
                    summary = _short_terminal_line(f"消费品口径下，{summary}", limit=30)

        if "pharma" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "roe_ex", "net_margin"}:
                hypotheses = _prepend_unique(hypotheses, ["集采", "产品放量"])
                validation_focus = _prepend_unique(validation_focus, ["院内销售", "研发投入"])
                if summary and "医药" not in summary:
                    summary = _short_terminal_line(f"医药口径下，{summary}", limit=30)

        if "tech_media" in industry_tags:
            if sub_key in {"inv_days", "inv_to_asset", "revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["景气周期", "稼动率"])
                validation_focus = _prepend_unique(validation_focus, ["订单能见度", "库存周转"])
                if summary and "半导体" not in summary and "电子" not in summary:
                    summary = _short_terminal_line(f"电子链条里，{summary}", limit=30)
            elif sub_key in {"asset_turn", "ar_days"}:
                hypotheses = _prepend_unique(hypotheses, ["客户订单", "产品周期"])
                validation_focus = _prepend_unique(validation_focus, ["订单能见度", "回款周期"])

        if "cyclical_manufacturing" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "asset_turn", "ar_days"}:
                hypotheses = _prepend_unique(hypotheses, ["订单节奏", "产能利用率"])
                validation_focus = _prepend_unique(validation_focus, ["在手订单", "开工率"])
                if summary and "机械" not in summary and "制造" not in summary:
                    summary = _short_terminal_line(f"周期制造口径下，{summary}", limit=30)
            elif sub_key in {"inv_days", "inv_to_asset"}:
                hypotheses = _prepend_unique(hypotheses, ["补库节奏", "排产变化"])
                validation_focus = _prepend_unique(validation_focus, ["产销节奏", "库存周转"])

        if "utilities_env" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["成本传导", "价格机制"])
            validation_focus = _prepend_unique(validation_focus, ["电价气价", "燃料成本"])
            if summary and "公用" not in summary and "环保" not in summary:
                summary = _short_terminal_line(f"公用环保口径下，{summary}", limit=30)

        if "materials_resources" in industry_tags:
            if sub_key not in {"inv_to_asset", "inv_days", "revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["价格周期", "成本价差"])
                validation_focus = _prepend_unique(validation_focus, ["量价拆分", "库存附注"])

        if "agriculture" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["养殖周期", "农产品价格"])
            validation_focus = _prepend_unique(validation_focus, ["出栏节奏", "原料成本"])
            if summary and "农林牧渔" not in summary:
                summary = _short_terminal_line(f"农业口径下，{summary}", limit=30)

        if "real_estate" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["去化", "拿地节奏"])
            validation_focus = _prepend_unique(validation_focus, ["销售回款", "土储结构"])
            if summary and "地产" not in summary:
                summary = _short_terminal_line(f"地产口径下，{summary}", limit=30)

        if "composite" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["业务结构", "资产处置"])
            validation_focus = _prepend_unique(validation_focus, ["分部口径", "非经常损益"])
            if summary and "综合" not in summary:
                summary = _short_terminal_line(f"综合口径下，{summary}", limit=30)

        explanation["summary"] = _polish_summary_text(summary, sub_key, latest_period_label)
        explanation["hypotheses"] = _compress_terminal_items(hypotheses, limit=18, max_items=4)
        explanation["validation_focus"] = _compress_terminal_items(validation_focus, limit=18, max_items=4)
        return explanation

    confidence = str(parsed.get("confidence") or "").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"

    explanation = {
        "status": "ready",
        "summary": _short_terminal_line(parsed.get("summary"), limit=30),
        "hypotheses": _normalize_list(parsed.get("hypotheses"), limit=18),
        "validation_focus": _normalize_list(parsed.get("validation_focus"), limit=18),
        "confidence": confidence,
    }
    explanation = _apply_industry_short_templates(explanation)

    return {
        "ok": True,
        "market": str(score_context.get("market") or history.get("market") or market),
        "symbol": str(score_context.get("symbol") or history.get("symbol") or symbol),
        "stock_name": score_context.get("stock_name") or history.get("stock_name") or symbol,
        "sub_key": sub_key,
        "indicator_name": str(diagnostic.get("indicator_name") or sub_key),
        "explanation": explanation,
    }


class StockDashboardHandler(BaseHTTPRequestHandler):
    server_version = "StockDashboard/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/stock-window-volume":
            self.handle_api(parsed.query)
            return
        if parsed.path == "/api/stock-kline":
            self.handle_stock_kline(parsed.query)
            return
        if parsed.path == "/api/stock-rps-history":
            self.handle_stock_rps_history(parsed.query)
            return
        if parsed.path == "/api/search/stocks":
            self.handle_stock_search(parsed.query)
            return
        if parsed.path == "/api/search/concepts":
            self.handle_concept_search(parsed.query)
            return
        if parsed.path == "/api/stock-profile":
            self.handle_stock_profile(parsed.query)
            return
        if parsed.path == "/api/rps-ranking":
            self.handle_rps_ranking(parsed.query)
            return
        if parsed.path == "/api/industry-heatmap":
            self.handle_industry_heatmap(parsed.query)
            return
        if parsed.path == "/api/pool-filter":
            self.handle_pool_filter(parsed.query)
            return
        if parsed.path == "/api/industry-hierarchy":
            self.handle_industry_hierarchy(parsed.query)
            return
        if parsed.path == "/api/stock-score":
            self.handle_stock_score(parsed.query)
            return
        if parsed.path == "/api/stock-score-report-history":
            self.handle_stock_score_report_history(parsed.query)
            return
        if parsed.path == "/api/stock-score-ai-report":
            self.handle_stock_score_ai_report(parsed.query)
            return
        if parsed.path == "/api/stock-score-industry-peers":
            self.handle_stock_score_industry_peers(parsed.query)
            return
        if parsed.path == "/api/stock-score-industry-total-peers":
            self.handle_stock_score_industry_total_peers(parsed.query)
            return
        if parsed.path == "/api/stock-score-subdiag-explanation":
            self.handle_stock_score_subdiag_explanation(parsed.query)
            return
        if parsed.path == "/api/data-update-status":
            self.handle_data_update_status(parsed.query)
            return
        if parsed.path == "/api/technical-eval":
            self.handle_technical_eval(parsed.query)
            return
        if parsed.path == "/api/industry-valuation-percentile":
            self.handle_industry_valuation_percentile(parsed.query)
            return
        if parsed.path == "/api/relative-valuation":
            self.handle_relative_valuation(parsed.query)
            return
        if parsed.path == "/api/valuation-models":
            self.handle_valuation_models(parsed.query)
            return
        if parsed.path == "/api/stock-price-percentile":
            self.handle_stock_price_percentile(parsed.query)
            return
        if parsed.path == "/api/stock-screener":
            self.handle_stock_screener(parsed.query)
            return
        if parsed.path == "/api/realtime-screener":
            self.handle_realtime_screener(parsed.query)
            return
        if parsed.path == "/api/concept-list":
            self.handle_concept_list(parsed.query)
            return
        if parsed.path.startswith("/api/proxy-capital-flow"):
            self.handle_proxy_capital_flow(parsed.query)
            return
        if parsed.path == "/":
            self.serve_static("stock-score.html")
            return
        if parsed.path.startswith("/"):
            self.serve_static(parsed.path.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/data-update-run":
            self.handle_data_update_run()
            return
        if parsed.path == "/api/data-update-retry":
            self.handle_data_update_retry()
            return
        if parsed.path == "/api/save-capital-flow":
            self.handle_save_capital_flow()
            return
        if parsed.path == "/api/seed-flow-cache":
            self.handle_seed_flow_cache()
            return
        if parsed.path == "/api/sync-to-tdx-block":
            self.handle_sync_to_tdx_block()
            return
        if parsed.path == "/api/capital-flow-ranking":
            self.handle_capital_flow_ranking()
            return
        if parsed.path == "/api/capital-flow-refresh":
            self.handle_capital_flow_refresh()
            return
        if parsed.path.startswith("/api/proxy-capital-flow"):
            self.handle_proxy_capital_flow(parsed.query)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_static("stock-score.html", include_body=False)
            return
        if parsed.path.startswith("/"):
            self.serve_static(parsed.path.lstrip("/"), include_body=False)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_static(self, relative_path: str, include_body: bool = True) -> None:
        target = (WEB_ROOT / relative_path).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if include_body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def handle_api(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            payload = load_stock_history(symbol)
            self.respond_json(HTTPStatus.OK, payload)
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_symbol",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": {
                        "code": "data_unavailable",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )

    def handle_stock_kline(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        limit = self.parse_limit(params.get("limit", ["250"])[0], default=250, maximum=2000)
        try:
            payload = load_stock_kline(symbol, limit=limit)
            self.respond_json(HTTPStatus.OK, payload)
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_symbol", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "kline_unavailable", "message": str(exc)}},
            )

    def handle_stock_rps_history(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            payload = load_stock_rps_history(symbol)
            self.respond_json(HTTPStatus.OK, payload)
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_symbol", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "rps_history_unavailable", "message": str(exc)}},
            )

    def handle_stock_search(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["20"])[0], default=20, maximum=50)
        try:
            self.respond_json(HTTPStatus.OK, stock_search_response(search_query, limit=limit))
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_concept_search(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["20"])[0], default=20, maximum=50)
        try:
            self.respond_json(HTTPStatus.OK, concept_search_response(search_query, limit=limit))
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_stock_profile(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            self.respond_json(HTTPStatus.OK, stock_profile_response(symbol))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": {
                        "code": "stock_not_found",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_rps_ranking(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["99999"])[0], default=99999, maximum=99999)
        try:
            window = self.parse_rps_window(params.get("window", ["20"])[0])
            self.respond_json(HTTPStatus.OK, rps_ranking_response(search_query, window=window, limit=limit))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_rps_window", "message": str(exc)}},
            )
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_industry_heatmap(self, query: str) -> None:
        params = parse_qs(query)
        raw_limit = params.get("limit", [""])[0].strip()
        raw_refresh = params.get("refresh", [""])[0].strip().lower()
        refresh_cache = raw_refresh in {"1", "true", "yes", "y", "refresh"}
        limit = DEFAULT_INDUSTRY_LIMIT if not raw_limit else self.parse_limit(raw_limit, default=999, maximum=999)
        lookback_sessions = self.parse_limit(params.get("lookback", [str(40)])[0], default=40, maximum=120)
        try:
            self.respond_json(HTTPStatus.OK, industry_heatmap_response(limit, lookback_sessions, refresh_cache=refresh_cache))
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": {"code": "heatmap_unavailable", "message": str(exc)}},
            )

    def handle_pool_filter(self, query: str) -> None:
        params = parse_qs(query)
        level1 = params.get("level1", [])
        level2 = params.get("level2", [])
        concepts = params.get("concepts", [])
        limit = self.parse_limit(params.get("limit", ["99999"])[0], default=99999, maximum=99999)
        try:
            self.respond_json(HTTPStatus.OK, pool_filter_response(level1, level2, concepts, limit=limit))
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "pool_filter_error", "message": str(exc)}},
            )

    def handle_industry_hierarchy(self, query: str) -> None:
        try:
            self.respond_json(HTTPStatus.OK, industry_hierarchy_response())
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "hierarchy_error", "message": str(exc)}},
            )

    def handle_concept_list(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["100"])[0], default=100, maximum=200)
        try:
            self.respond_json(HTTPStatus.OK, concept_list_response(search_query, limit=limit))
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "concept_list_error", "message": str(exc)}},
            )

    def handle_stock_screener(self, query: str) -> None:
        params = {
            key: values[0].strip()
            for key, values in parse_qs(query, keep_blank_values=True).items()
            if values
        }
        try:
            ensure_stock_screener_strategy_dataset(params.get("strategy", ""))
            self.respond_json(HTTPStatus.OK, build_stock_screener_response(params))
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "stock_screener_error", "message": str(exc)}},
            )

    def handle_realtime_screener(self, query: str) -> None:
        params = {
            key: values[0].strip()
            for key, values in parse_qs(query, keep_blank_values=True).items()
            if values
        }
        try:
            if params.get("scenario", "").strip() == "rps_pullback":
                ensure_stock_screener_strategy_dataset("rps_pullback")
            self.respond_json(HTTPStatus.OK, realtime_screener_response(params))
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "realtime_screener_error", "message": str(exc)}},
            )

    def handle_stock_score(self, query: str) -> None:
        from app.search.index import compute_financial_scores, compute_stock_score
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip()
        symbol = params.get("symbol", [""])[0].strip()
        symbols_param = params.get("symbols", [""])[0].strip()  # comma-separated "market:symbol,..."
        try:
            if symbols_param:
                pairs = []
                for p in symbols_param.split(","):
                    parts = p.strip().split(":")
                    if len(parts) == 2:
                        pairs.append((parts[0], parts[1]))
                if pairs:
                    result = compute_financial_scores(pairs)
                    self.respond_json(HTTPStatus.OK, result)
                    return
            if market and symbol:
                result = compute_stock_score(market, symbol)
                self.respond_json(HTTPStatus.OK, result)
                return
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "provide market & symbol or symbols"})
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def handle_stock_score_ai_report(self, query: str) -> None:
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        try:
            self.respond_json(HTTPStatus.OK, generate_stock_ai_report(market, symbol))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_stock", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "ai_report_error", "message": str(exc)}},
            )

    def handle_stock_score_industry_peers(self, query: str) -> None:
        from app.search.index import _SUB_KEYS, build_stock_score_industry_peer_benchmark

        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        sub_key = params.get("sub_key", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol or sub_key not in _SUB_KEYS:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol/sub_key 参数不合法"}},
            )
            return
        try:
            self.respond_json(HTTPStatus.OK, build_stock_score_industry_peer_benchmark(market, symbol, sub_key))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "stock_score_industry_peers_error", "message": str(exc)}},
            )

    def handle_stock_score_industry_total_peers(self, query: str) -> None:
        from app.search.index import build_stock_score_industry_total_peer_benchmark

        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol 参数不合法"}},
            )
            return
        try:
            self.respond_json(HTTPStatus.OK, build_stock_score_industry_total_peer_benchmark(market, symbol))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "stock_score_industry_total_peers_error", "message": str(exc)}},
            )

    def handle_stock_score_subdiag_explanation(self, query: str) -> None:
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        sub_key = params.get("sub_key", [""])[0].strip()
        try:
            self.respond_json(HTTPStatus.OK, generate_sub_indicator_ai_explanation(market, symbol, sub_key))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_sub_indicator", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "subdiag_explanation_error", "message": str(exc)}},
            )

    def handle_data_update_status(self, query: str) -> None:
        try:
            self.respond_json(HTTPStatus.OK, load_data_update_status())
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "data_update_status_error", "message": str(exc)}},
            )

    def handle_data_update_run(self) -> None:
        self._handle_data_update_start(retry_failed=False)

    def handle_data_update_retry(self) -> None:
        self._handle_data_update_start(retry_failed=True)

    def handle_save_capital_flow(self) -> None:
        """接收浏览器端资金流向数据，追加写入 Parquet"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            rows = json.loads(body)
        except json.JSONDecodeError:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return
        if not isinstance(rows, list) or len(rows) == 0:
            self.respond_json(HTTPStatus.OK, {"ok": True, "saved": 0})
            return
        
        df = pd.DataFrame(rows)
        df["trading_day"] = df["trading_day"].astype(str)
        df["symbol"] = df["symbol"].astype(str)
        
        cf_file = DERIVED_FINAL_DIR / "dataset_stock_capital_flow.parquet"
        if cf_file.exists():
            old = pd.read_parquet(cf_file)
            df = pd.concat([old, df], ignore_index=True)
        df = df.drop_duplicates(subset=["symbol", "trading_day"], keep="last")
        # Keep max 30 days per stock
        df["_rank"] = df.groupby("symbol")["trading_day"].rank(ascending=False, method="dense")
        df = df[df["_rank"] <= 30].drop(columns=["_rank"])
        
        cf_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cf_file, index=False)
        self.respond_json(HTTPStatus.OK, {
            "ok": True,
            "saved": len(rows),
            "total_rows": len(df),
            "total_stocks": df["symbol"].nunique(),
        })

    def handle_proxy_capital_flow(self, query: str) -> None:
        """代理转发东方财富资金流向 API 请求（带本地缓存，同日不重复请求）"""
        params = parse_qs(query)
        symbol = params.get("symbol", [""])[0].strip()
        if not symbol or not symbol.isdigit() or len(symbol) != 6:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid symbol"})
            return
        # 检查本地缓存
        cache_dir = DERIVED_FINAL_DIR.parent / "cache" / "capital_flow"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{symbol}.json"
        today = datetime.now().strftime("%Y-%m-%d")
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                if cached.get("cached_date") == today:
                    self.respond_json(HTTPStatus.OK, {"ok": True, "data": cached["data"], "cached": True})
                    return
            except Exception:
                pass
        # 缓存未命中或过期：请求东方财富
        em_mkt = "1" if symbol.startswith(("60", "68")) else "0"
        hosts = ["push2his.eastmoney.com", "push2.eastmoney.com"]
        last_error = None
        for host in hosts:
            for attempt in range(3):
                if attempt > 0:
                    time.sleep(2)
                url = (
                    f"https://{host}/api/qt/stock/fflow/daykline/get"
                    f"?lmt=120&klt=1&secid={em_mkt}.{symbol}"
                    f"&fields1=f1,f2,f3,f7"
                    f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
                )
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    resp = urllib.request.urlopen(req, timeout=10)
                    raw = json.loads(resp.read())
                    # 写入缓存
                    cache_file.write_text(json.dumps({
                        "cached_date": today,
                        "data": raw,
                    }, separators=(",", ":")))
                    self.respond_json(HTTPStatus.OK, {"ok": True, "data": raw, "cached": False})
                    return
                except Exception as e:
                    last_error = str(e)
        # API 不可达：回退到缓存（即使是旧数据）
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                self.respond_json(HTTPStatus.OK, {"ok": True, "data": cached["data"], "cached": True, "stale": True})
                return
            except Exception:
                pass
        self.respond_json(HTTPStatus.BAD_GATEWAY, {
            "ok": False,
            "error": {"code": "proxy_failed", "message": last_error or "unknown"},
        })

    def _handle_data_update_start(self, retry_failed: bool = False) -> None:
        if not _is_allowed_local_origin(self.headers.get('Origin'), self.headers.get('Referer')):
            self.respond_json(
                HTTPStatus.FORBIDDEN,
                {"ok": False, "error": {"code": "forbidden_origin", "message": "仅允许本地页面触发数据更新"}},
            )
            return
        payload = start_data_update_job(retry_failed=retry_failed)
        if not payload.get('ok'):
            self.respond_json(HTTPStatus.CONFLICT, payload)
            return
        self.respond_json(HTTPStatus.OK, payload)

    def handle_sync_to_tdx_block(self) -> None:
        """Sync screener result stocks to Tongdaxin custom block 'AIGC' (AI股池)."""
        TDX_BLOCK_DIR = Path(TONGDAXIN_DIR) / "T0002" / "blocknew"
        block_path = TDX_BLOCK_DIR / "AIGC.blk"

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return

        stocks = payload.get("stocks", [])
        if not isinstance(stocks, list):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "stocks must be a list"})
            return

        lines = []
        for s in stocks:
            market = str(s.get("market", "")).strip().lower()
            symbol = str(s.get("symbol", "")).strip()
            if len(symbol) != 6 or not symbol.isdigit():
                continue
            if market == "sh":
                lines.append(f"1{symbol}")
            elif market == "sz":
                lines.append(f"0{symbol}")

        # Merge with existing block content (append, deduplicate)
        existing: set[str] = set()
        if block_path.exists():
            for raw_line in block_path.read_text(encoding="ascii").splitlines():
                code = raw_line.strip()
                if code and len(code) == 7 and code[0] in "01":
                    existing.add(code)
        merged = list(existing) + [l for l in lines if l not in existing]

        TDX_BLOCK_DIR.mkdir(parents=True, exist_ok=True)
        content = "\r\n".join(merged) + "\r\n"
        block_path.write_text(content, encoding="ascii")
        self.respond_json(HTTPStatus.OK, {"ok": True, "written": len(lines), "path": str(block_path)})

    def handle_capital_flow_ranking(self) -> None:
        """Return top 20 inflow/outflow from cached capital flow data."""
        if CAPITAL_FLOW_CACHE.exists():
            payload = json.loads(CAPITAL_FLOW_CACHE.read_text(encoding="utf-8"))
            self.respond_json(HTTPStatus.OK, {
                "ok": True,
                "updated_at": payload.get("updated_at"),
                "total": payload.get("total"),
                "top_inflow": payload.get("top_inflow", []),
                "top_outflow": payload.get("top_outflow", []),
            })
            return
        self.respond_json(HTTPStatus.OK, {"ok": True, "total": 0, "top_inflow": [], "top_outflow": [], "updated_at": None})

    def handle_capital_flow_refresh(self) -> None:
        """Trigger a background fetch of capital flow data."""
        import threading
        def _fetch():
            subprocess.run(
                [TONGDAXIN_PYTHON, str(PROJECT_ROOT / "scripts/fetch_capital_flow.py")],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
            )
        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        self.respond_json(HTTPStatus.OK, {"ok": True, "message": "fetch started"})

    def handle_valuation_models(self, query: str) -> None:
        """Compute DCF, WACC, Altman Z, Piotroski, DuPont for a stock."""
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol 参数不合法"}},
            )
            return

        def _to_float(v: object) -> float | None:
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        def _to_yi(v: float | None) -> float:
            """Convert raw yuan to 亿元."""
            if v is None:
                return 0
            return v / 1e8

        try:
            search_index = importlib.import_module("app.search.index")
            latest_period = search_index._snapshot_latest_period(market, symbol)
            if not latest_period:
                self.respond_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "no_financial_data"})
                return

            current = search_index._load_financial_quarter_row(latest_period, symbol)
            if current is None:
                self.respond_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "no_financial_data"})
                return

            year = int(str(latest_period)[:4])
            prev_period = f"{year - 1}{str(latest_period)[4:]}"
            previous = search_index._load_financial_quarter_row(prev_period, symbol)

            stock_name = search_index._stock_name_lookup().get((market, symbol), "")
            daily = search_index._load_latest_daily_snapshot(market, symbol)
            basic_info = search_index._load_stock_basic_info(market, symbol)
            current_price = _to_float((basic_info or {}).get("current_price"))
            if current_price is None:
                current_price = _to_float((daily or {}).get("latest_close"))

            # ── Extract financial data from CW rows (raw yuan → 亿元) ──
            _pick = search_index._pick
            def _f(key): return _to_yi(_pick(current.get(key)))

            revenue          = _f("营业收入") or 0
            net_profit       = _f("归属于母公司所有者的净利润") or 0
            ocf              = _f("经营活动产生的现金流量净额") or 0
            current_assets   = _f("流动资产合计") or 0
            current_liab     = _f("流动负债合计") or 0
            total_assets     = _f("资产总计") or 0
            total_liab       = _f("负债合计") or 0
            equity_attr      = _f("归属于母公司股东权益(资产负债表)") or 0
            retained_earn    = _f("未分配利润") or 0
            total_shares_raw = _pick(current.get("总股本"))
            total_shares     = total_shares_raw / 1e8 if total_shares_raw else 0  # 股→亿股
            short_debt       = _f("短期借款") or 0
            long_debt        = _f("长期借款") or 0
            bonds            = _f("应付债券") or 0
            interest_expense = _f("其中:利息费用(利润表-财务费用)") or 0
            income_tax       = _f("所得税费用") or 0
            income_before_tax = _f("利润总额") or 0
            ebit             = _f("息税前利润(EBIT)") or 0
            cash_equiv       = _f("货币资金") or 0
            capex            = _f("购建固定资产、无形资产和其他长期资产支付的现金") or 0
            revenue_prev     = _f("营业收入") if previous is not None else None
            net_profit_prev  = _f("归属于母公司所有者的净利润") if previous is not None else None
            total_assets_prev = _f("资产总计") if previous is not None else None

            # Derived
            free_cf = ocf - capex
            total_debt = short_debt + long_debt + bonds
            working_capital = current_assets - current_liab

            # ── Pre-computed TTM & YoY from CW ──
            ttm_net = _to_yi(_pick(current.get("近一年归母净利润（万元）"))) or _to_yi(_pick(current.get("ttm_net_profit_yi")))
            ttm_rev = _to_yi(_pick(current.get("营业总收入TTM(万元)"))) or _to_yi(_pick(current.get("ttm_revenue_yi")))

            # Derived ratios
            derived = search_index._derive_sub_fields(current, previous)
            gross_margin = derived.get("gross_margin") or 0
            asset_turnover = derived.get("asset_turnover") or 0
            roe_current = derived.get("roe_ex") or 0
            debt_ratio = derived.get("debt_ratio") or 0
            current_ratio = derived.get("current_ratio") or 0

            prev_derived = search_index._derive_sub_fields(previous, None) if previous is not None else {}
            gross_margin_prev = prev_derived.get("gross_margin") or 0
            asset_turnover_prev = prev_derived.get("asset_turnover") or 0
            roe_prev = prev_derived.get("roe_ex") or 0
            current_ratio_prev = prev_derived.get("current_ratio") or 0
            debt_ratio_prev = prev_derived.get("debt_ratio") or 0

            # ── Market data ──
            free_float_shares = _pick(current.get("无限售流通股")) or _pick(current.get("自由流通股"))
            free_float_shares = free_float_shares / 1e8 if free_float_shares else total_shares * 0.7

            market_cap = current_price * total_shares if current_price and total_shares else 0
            free_float_market_cap = current_price * free_float_shares if current_price and free_float_shares else 0

            # Previous year values for Piotroski
            prev_ocf = _to_yi(_pick(previous.get("经营活动产生的现金流量净额"))) if previous is not None else 0
            prev_net = _to_yi(_pick(previous.get("归属于母公司所有者的净利润"))) if previous is not None else 0
            prev_total_assets_val = _to_yi(_pick(previous.get("资产总计"))) if previous is not None else 0
            prev_current_assets = _to_yi(_pick(previous.get("流动资产合计"))) if previous is not None else 0
            prev_current_liab = _to_yi(_pick(previous.get("流动负债合计"))) if previous is not None else 0
            prev_total_liab_val = _to_yi(_pick(previous.get("负债合计"))) if previous is not None else 0
            prev_total_shares_raw = _pick(previous.get("总股本")) if previous is not None else None
            prev_total_shares_val = prev_total_shares_raw / 1e8 if prev_total_shares_raw else total_shares
            prev_revenue = _to_yi(_pick(previous.get("营业收入"))) if previous is not None else 0

            # ── Simple beta approximation using RPS data ──
            rps_data = (daily or {}).get("rps_20") if daily else None
            beta = 1.0  # Default for A-shares
            if rps_data is not None:
                try:
                    rps_val = float(rps_data)
                    beta = max(0.3, min(2.5, 1.0 + (rps_val - 50) / 100))
                except (ValueError, TypeError):
                    pass

            # ── China market parameters ──
            RISK_FREE_RATE = 0.025   # China 10Y government bond
            MARKET_RISK_PREMIUM = 0.06  # A-share historical ERP

            # ── Industry classification & special handling ──
            stock_name_str = str(stock_name).replace(" ", "").replace("\u3000", "")
            # Detect financial companies by name
            is_financial = any(kw in stock_name_str for kw in [
                "银行", "保险", "证券", "信托", "金融", "农商", "城商",
            ])
            # Detect real estate separately (different model)
            is_real_estate = any(kw in stock_name_str for kw in [
                "地产", "房产", "置业", "万科", "保利", "招商蛇口", "金地", "绿地",
                "华夏幸福", "新城控股", "中南建设", "荣盛发展", "滨江集团",
            ])
            # Detect construction companies (DCF-OK, high leverage is normal)
            is_construction = any(kw in stock_name_str for kw in [
                "建筑", "铁建", "中铁", "交建", "电建", "中冶", "化学工程",
                "葛洲坝", "隧道", "路桥",
            ])
            # Assets/market_cap heuristic — catch remaining financial firms
            assets_to_mcap = total_assets / market_cap if market_cap > 0 and total_assets > 0 else 0
            if not is_financial and not is_real_estate and not is_construction and assets_to_mcap > 10:
                is_financial = True  # likely financial/leasing company not caught by name

            # For banks/financials, try alternative interest expense fields
            if is_financial and interest_expense == 0:
                alt_interest = _f("利息支出") or _f("其中:利息支出") or _f("利息净收入")
                if alt_interest == 0:
                    interest_income = _f("利息收入") or 0
                    alt_interest = interest_income * 0.15
                interest_expense = alt_interest if alt_interest else interest_expense

            # ── Annualize single-quarter ROE ──
            period_str = str(latest_period)
            annualize_factor = 1.0
            if period_str.endswith("Q1"):
                annualize_factor = 4.0
            elif period_str.endswith("Q2"):
                annualize_factor = 2.0
            elif period_str.endswith("Q3"):
                annualize_factor = 4.0 / 3.0
            # Q4 and annual reports: factor = 1.0
            net_profit_annualized = net_profit * annualize_factor
            roe_annualized = safe_div(net_profit_annualized, equity_attr) if equity_attr else 0
            roa_annualized = safe_div(net_profit_annualized, total_assets) if total_assets else 0

            # ── Compute models ──
            # 1. WACC
            cost_of_equity = calc_cost_of_equity_capm(RISK_FREE_RATE, beta, MARKET_RISK_PREMIUM)
            cost_of_debt = calc_cost_of_debt(interest_expense, total_debt) if total_debt else 0.04
            tax_rate = calc_tax_rate(income_tax, income_before_tax)
            wacc_result = calc_wacc(
                market_value_equity=market_cap,
                market_value_debt=total_debt,
                cost_of_equity=cost_of_equity,
                cost_of_debt=cost_of_debt,
                tax_rate=tax_rate,
            )
            wacc_val = wacc_result.get("wacc", 0.08)

            # 2. Valuation model (DCF for industrials, PB-ROE for financial/real estate)
            growth_rate = max(0.02, min(0.25, derived.get("profit_growth", 8) / 100)) if derived.get("profit_growth") else 0.08
            if is_financial or is_real_estate:
                bvps = safe_div(equity_attr, total_shares) if total_shares else 0
                if is_real_estate:
                    # Real estate: discounted book value (reflect development risk)
                    discount = 0.40  # typical A-share real estate PB discount
                    pb_intrinsic = bvps * (1 - discount)
                    note = "房地产企业建议使用NAV估值，以下为折价净资产参考"
                    formula = "内在价值 = BVPS × (1 - 40% 风险折价)"
                else:
                    # Financial: PB-ROE model
                    pb_intrinsic = bvps * (roe_annualized / cost_of_equity) if cost_of_equity > 0 and roe_annualized > 0 else bvps
                    note = "金融企业不适用传统DCF，以下为 PB-ROE 估值模型"
                    formula = "内在价值 = BVPS × (ROE年化 ÷ COE)"
                dcf_result = {
                    "_financial_note": note,
                    "free_cash_flow": round(free_cf, 2),
                    "growth_rate": round(growth_rate, 4),
                    "book_value_per_share": round(bvps, 2),
                    "roe": round(roe_annualized, 4),
                    "cost_of_equity": round(cost_of_equity, 4),
                    "pb_intrinsic_value": round(pb_intrinsic, 2),
                    "intrinsic_value_per_share": round(pb_intrinsic, 2),
                    "formula": formula,
                    "periods": 0,
                    "terminal_value": 0,
                    "enterprise_value": 0,
                    "equity_value": 0,
                    "pv_details": [],
                }
            else:
                # Annualize quarterly FCF for DCF
                fcf_annualized = free_cf * annualize_factor
                if fcf_annualized <= 0:
                    # Negative FCF — DCF not applicable this quarter
                    dcf_result = {
                        "_financial_note": f"当前季度自由现金流为负({free_cf:.1f}亿)，DCF不适用。建议参考PB或等待年报数据。",
                        "free_cash_flow": round(free_cf, 2),
                        "growth_rate": 0, "perpetual_growth_rate": 0,
                        "wacc": 0, "periods": 0,
                        "terminal_value": 0, "enterprise_value": 0,
                        "equity_value": 0, "intrinsic_value_per_share": 0,
                        "pv_details": [],
                    }
                else:
                    dcf_result = calc_intrinsic_value_dcf(
                        free_cash_flow=fcf_annualized,
                        growth_rate=growth_rate,
                        perpetual_growth_rate=0.03,
                        wacc=max(wacc_val, 0.05),
                        cash_and_equivalents=cash_equiv,
                        total_debt=total_debt,
                        shares_outstanding=total_shares if total_shares > 0 else 1,
                    )

            # 3. Gordon Growth
            dps = safe_div(net_profit * 0.3, total_shares)  # Assume 30% payout
            gordon_result = calc_gordon_growth(
                dividends_per_share=dps,
                cost_of_equity=cost_of_equity,
                growth_rate=min(growth_rate * 0.7, cost_of_equity - 0.01),
            )

            # 4. Altman Z-Score
            altman_result = calc_altman_z_score(
                current_assets=current_assets,
                current_liabilities=current_liab,
                total_assets=total_assets,
                retained_earnings=retained_earn if retained_earn else net_profit * 0.4,
                ebit=ebit if ebit else (net_profit + interest_expense),
                market_cap=market_cap,
                total_liabilities=total_liab if total_liab > 0 else 1,
                revenue=revenue,
            )

            # 5. Piotroski F-Score
            piotroski_result = calc_piotroski_f_score(
                net_income=net_profit,
                ocf=abs(ocf),
                roa=safe_div(net_profit, total_assets),
                total_assets=total_assets,
                current_assets=current_assets,
                current_liabilities=current_liab,
                total_liabilities=total_liab,
                shares_outstanding=total_shares,
                gross_margin=gross_margin,
                asset_turnover=asset_turnover,
                prev_net_income=prev_net,
                prev_ocf=abs(prev_ocf),
                prev_roa=safe_div(prev_net or 0, prev_total_assets_val),
                prev_current_assets=prev_current_assets,
                prev_current_liabilities=prev_current_liab,
                prev_total_liabilities=prev_total_liab_val,
                prev_total_assets=prev_total_assets_val,
                prev_shares_outstanding=prev_total_shares_val,
                prev_gross_margin=gross_margin_prev,
                prev_asset_turnover=asset_turnover_prev,
            )

            # 6. DuPont
            dupont_result = calc_dupont_analysis(
                net_income=net_profit,
                revenue=revenue,
                total_assets=total_assets,
                total_equity=equity_attr if equity_attr else total_assets - total_liab,
                ebit=ebit,
                income_before_tax=income_before_tax,
            )

            # 7. Enterprise Value
            ev_result = calc_enterprise_value_breakdown(
                market_cap=market_cap,
                total_debt=total_debt,
                cash_and_equivalents=cash_equiv,
            )

            # ── Response ──
            self.respond_json(HTTPStatus.OK, {
                "ok": True,
                "market": market,
                "symbol": symbol,
                "stock_name": str(stock_name),
                "latest_period": str(latest_period),
                "market_data": {
                    "close_price": round(current_price or 0, 2),
                    "total_market_cap": round(market_cap, 2),
                    "total_shares": round(total_shares, 2),
                    "free_float_market_cap": round(free_float_market_cap, 2),
                    "beta": round(beta, 4),
                },
                "financial_summary": {
                    "revenue": round(revenue, 2),
                    "net_profit": round(net_profit, 2),
                    "ocf": round(ocf, 2),
                    "free_cf": round(free_cf, 2),
                    "total_assets": round(total_assets, 2),
                    "total_liabilities": round(total_liab, 2),
                    "total_equity": round(equity_attr, 2),
                    "total_debt": round(total_debt, 2),
                    "cash_equiv": round(cash_equiv, 2),
                },
                "wacc": wacc_result,
                "dcf": dcf_result,
                "gordon_growth": gordon_result,
                "altman_z": altman_result,
                "piotroski": piotroski_result,
                "dupont": dupont_result,
                "enterprise_value": ev_result,
            })

        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "valuation_error", "message": str(exc)}},
            )

    def handle_relative_valuation(self, query: str) -> None:
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol 参数不合法"}},
            )
            return
        try:
            result = build_relative_valuation_result(market, symbol)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND
            self.respond_json(status, result)
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "relative_valuation_error", "message": str(exc)}},
            )

    def handle_industry_valuation_percentile(self, query: str) -> None:
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol 参数不合法"}},
            )
            return
        try:
            payload = _build_industry_valuation_percentile_payload(market, symbol)
            if not payload.get("ok") and payload.get("error") == "industry_not_found":
                self.respond_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "industry_not_found"})
                return
            self.respond_json(HTTPStatus.OK, payload)
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "industry_valuation_percentile_error", "message": str(exc)}},
            )

    def handle_stock_price_percentile(self, query: str) -> None:
        """Compute historical price percentile against the stock's own N-year trading history."""
        params = parse_qs(query)
        symbol = params.get("symbol", [""])[0].strip()
        try:
            market, _ = infer_market(symbol)
        except ValueError as exc:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "invalid_stock", "message": str(exc)}})
            return
        years_param = params.get("years", ["5"])[0].strip()
        try:
            years = int(years_param)
        except (TypeError, ValueError):
            years = 5
        years = max(1, min(10, years))

        try:
            payload = compute_stock_price_percentile(market, symbol, years=years)
            self.respond_json(HTTPStatus.OK, payload)
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_stock", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "price_percentile_error", "message": str(exc)}},
            )

    def handle_technical_eval(self, query: str) -> None:
        """Return single-stock technical evaluation from pre-computed JSON."""
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        if market not in {"sh", "sz", "bj"} or not symbol.isdigit() or len(symbol) != 6:
            self.respond_json(HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_params", "message": "market/symbol required"}})
            return

        try:
            import json
            from pathlib import Path
            path = Path(__file__).resolve().parent.parent / "data" / "derived" / "datasets" / "final" / "dataset_technical_eval.json"
            if not path.is_file():
                self.respond_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "tech_data_not_found"})
                return

            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            stocks = raw.get("stocks", raw)
            entry = stocks.get(symbol)
            if not entry:
                self.respond_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "stock_not_found"})
                return

            # Enrich with stock name
            search_index = importlib.import_module("app.search.index")
            name = search_index._stock_name_lookup().get((market, symbol), "")
            entry["stock_name"] = str(name)
            entry["market"] = market
            entry["data_date"] = raw.get("data_date", "")

            self.respond_json(HTTPStatus.OK, {"ok": True, **entry})

        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "tech_eval_error", "message": str(exc)}})

    def handle_stock_score_report_history(self, query: str) -> None:
        params = parse_qs(query)
        market = params.get("market", [""])[0].strip().lower()
        symbol = params.get("symbol", [""])[0].strip()
        try:
            self.respond_json(HTTPStatus.OK, load_recent_three_year_financial_reports(market, symbol))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_stock", "message": str(exc)}},
            )
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "report_history_error", "message": str(exc)}},
            )

    @staticmethod
    def parse_limit(raw_value: str, *, default: int, maximum: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(1, min(maximum, value))

    @staticmethod
    def parse_rps_window(raw_value: str) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("window must be 20, 50, 120 or 250") from exc
        if value not in (20, 50, 120, 250):
            raise ValueError("window must be 20, 50, 120 or 250")
        return value

    def respond_json(self, status: HTTPStatus, payload: dict[str, object]) -> bool:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Default: 8765")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not WEB_ROOT.is_dir():
        raise SystemExit(f"web root not found: {WEB_ROOT}")
    server = ThreadingHTTPServer((args.host, args.port), StockDashboardHandler)
    print(f"Serving stock dashboard on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
