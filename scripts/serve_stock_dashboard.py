#!/usr/bin/env python3
"""Serve a minimal local dashboard for one stock's daily trend and volume windows."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.industry.heatmap import DEFAULT_INDUSTRY_LIMIT, industry_heatmap_response
from app.search.index import (
    concept_search_response,
    rps_ranking_response,
    stock_profile_response,
    stock_search_response,
    pool_filter_response,
    industry_hierarchy_response,
    concept_list_response,
)


TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
DEFAULT_SYMBOL = "601600"
DEFAULT_HISTORY_LIMIT = 120
WEB_ROOT = PROJECT_ROOT / "web"
DEFAULT_HERMES_MODEL = os.environ.get("HERMES_MODEL", "").strip()


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


def infer_market(symbol: str) -> tuple[str, int]:
    if symbol.startswith(("60", "68", "90")):
        return "sh", 1
    if symbol.startswith(("00", "30", "20")):
        return "sz", 0
    raise ValueError(f"unsupported symbol prefix for {symbol}")


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


def load_stock_rps_history(symbol: str) -> dict[str, object]:
    """Compute historical RPS-20/50/120/250 for one stock using full local history."""
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
tdxdir = sys.argv[3]

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")

closes = daily.sort_index()["close"].astype(float).tolist()
dates  = daily.sort_index().index.strftime("%Y-%m-%d").tolist()

def rolling_return(values, n):
    return [None] * (n - 1) + [
        (values[i] - values[i - n]) / values[i - n] * 100
        if values[i - n] != 0 else None
        for i in range(n - 1, len(values))
    ]

ret20 = rolling_return(closes, 20)
ret50 = rolling_return(closes, 50)
ret120 = rolling_return(closes, 120)
ret250 = rolling_return(closes, 250)

WINDOW = 120

def rolling_rps(values, window):
    out = []
    for i in range(len(values)):
        if i < window - 1 or values[i] is None:
            out.append(None)
            continue
        slice_vals = [v for v in values[max(0, i - window + 1):i + 1] if v is not None]
        if not slice_vals:
            out.append(None)
            continue
        below = sum(1 for v in slice_vals if v < values[i])
        pct = below / len(slice_vals) * 100
        out.append(round(pct, 2))
    return out

rps20 = rolling_rps(ret20, WINDOW)
rps50 = rolling_rps(ret50, WINDOW)
rps120 = rolling_rps(ret120, WINDOW)
rps250 = rolling_rps(ret250, WINDOW)

rows = []
for i, d in enumerate(dates):
    rows.append({
        "trading_day": d,
        "rps_20": rps20[i],
        "rps_50": rps50[i],
        "rps_120": rps120[i],
        "rps_250": rps250[i],
        "return_20_pct": round(ret20[i], 4) if ret20[i] is not None else None,
        "return_50_pct": round(ret50[i], 4) if ret50[i] is not None else None,
        "return_120_pct": round(ret120[i], 4) if ret120[i] is not None else None,
        "return_250_pct": round(ret250[i], 4) if ret250[i] is not None else None,
    })

print(json.dumps({"ok": True, "symbol": symbol, "market": market, "history": rows}, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [TONGDAXIN_PYTHON, "-c", script, symbol, market, TONGDAXIN_DIR],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mootdx subprocess error")
    return json.loads(result.stdout)


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
        if parsed.path == "/api/concept-list":
            self.handle_concept_list(parsed.query)
            return
        if parsed.path == "/":
            self.serve_static("index.html")
            return
        if parsed.path.startswith("/"):
            self.serve_static(parsed.path.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_static(self, relative_path: str) -> None:
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
        limit = self.parse_limit(params.get("limit", ["250"])[0], default=250, maximum=500)
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
