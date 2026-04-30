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
    """Compute historical RPS-20 and RPS-50 for one stock using full local history."""
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

rows = []
for i, d in enumerate(dates):
    rows.append({
        "trading_day": d,
        "rps_20": rps20[i],
        "rps_50": rps50[i],
        "return_20_pct": round(ret20[i], 4) if ret20[i] is not None else None,
        "return_50_pct": round(ret50[i], 4) if ret50[i] is not None else None,
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

    for report_date, fp in search_index._all_financial_files():
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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        limit = self.parse_limit(params.get("limit", ["100"])[0], default=100, maximum=500)
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

    def respond_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
