"""HTTP request handler for the stock dashboard."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import importlib
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Business logic imports
from app.config import (
    PROJECT_ROOT, WEB_ROOT, TONGDAXIN_PYTHON, TONGDAXIN_DIR,
    DEFAULT_SYMBOL, DEFAULT_HERMES_MODEL, DERIVED_FINAL_DIR,
    STOCK_SCREENER_STRATEGY_DATASET, STOCK_RPS_CURRENT_DATASET,
)
from app.data.watchlist import _load_watchlist, _save_watchlist
from app.data.tech_eval import _load_tech_eval, _load_prev_tech_evals
from app.data.industry_temp import _load_industry_temp
from app.data.rps_history import load_stock_rps_history, _load_rps_history_dataset
from app.tdx.kline import load_stock_history, load_stock_kline, infer_market
from app.tdx.percentile import compute_stock_price_percentile
from app.financial.reports import load_recent_three_year_financial_reports
from app.financial.ai_report import generate_stock_ai_report, generate_sub_indicator_ai_explanation
from app.pipeline.state import (
    DATA_UPDATE_LOCK, DATA_UPDATE_JOB_STATE, _data_update_job_snapshot,
    _update_data_update_job_state, _append_data_update_job_output,
    _record_data_update_progress, DataUpdateStepError, _format_timestamp,
)
from app.pipeline.commands import ensure_stock_screener_strategy_dataset, _latest_trading_day_for_refresh
from app.pipeline.runner import start_data_update_job, run_full_data_update
from app.industry.templates import _industry_template_tags, _build_industry_valuation_percentile_payload

# Bottleneck discovery module
from app.bottleneck import (
    step1_select_trend, step2_decompose_chain, step3_identify_bottlenecks,
    step4_map_stocks, step5_verify_stocks, step6_cross_verify, step7_full_auto,
    save_report, list_reports, load_report, rerun_report, delete_report,
    check_custom_status,
)

# Additional imports from original
from app.search.index import (
    build_stock_screener_response,
    compute_stock_score,
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


def _recompute_conclusion_v2(entry: dict) -> None:
    """Recompute conclusion using short_trend as primary, trend as modifier."""
    st = entry.get("short_trend", "")
    t  = entry.get("trend", "")
    mo = entry.get("momentum", "")
    vs = entry.get("volume_signal", "")
    pos = entry.get("position", "")
    bt = entry.get("buy_triggers") or []
    owd = entry.get("one_word_limit_down", False)
    rd  = entry.get("recently_limit_down", False)

    ST_BULL = st in ("strong_bullish", "bullish")
    ST_BEAR = st in ("strong_bearish", "bearish")
    T_BULL  = t in ("strong_bullish", "bullish")
    T_BEAR  = t in ("strong_bearish", "bearish")
    T_STRONG_BEAR = t == "strong_bearish"

    LABELS = {"strong_bullish":"强多头","bullish":"多头","recovering":"修复中","neutral":"震荡",
              "bearish":"空头","strong_bearish":"强空头"}
    sl = LABELS.get(st, st)
    tl = LABELS.get(t, t)

    confirmed = [tr for tr in bt if tr.get("strength") == "confirmed"]
    watch_triggers = [tr for tr in bt if tr.get("strength") == "watch"]
    has_buy = len(confirmed) > 0
    has_watch = len(watch_triggers) > 0

    if st == "insufficient_data":
        entry.update(conclusion="insufficient_data", conclusion_label="数据不足", conclusion_color="gray", conclusion_reason="交易日不足60日")
        return
    if owd:
        entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red", conclusion_reason="一字跌停")
        return
    if st == "strong_bearish" and mo == "weak":
        entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red", conclusion_reason=f"短期{sl}+动量弱势")
        return
    if vs == "divergence" and ST_BEAR:
        entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red", conclusion_reason=f"短期{sl}+量价背离")
        return
    if has_buy:
        best = confirmed[0]
        if ST_BULL and not T_BEAR and mo != "weak" and vs != "divergence" and pos != "overheated":
            if not (rd or owd) and best.get("risk_pct", 0) <= 0.08:
                entry.update(conclusion="buy_confirmed", conclusion_label="确认买入", conclusion_color="green",
                             conclusion_reason=f"短期{sl}+{best.get('label','买入信号')}")
                return
        entry.update(conclusion="buy_watch", conclusion_label="买点观察", conclusion_color="yellow",
                     conclusion_reason=f"有{best.get('label','信号')}但条件不完全确认")
        return
    if has_watch:
        entry.update(conclusion="buy_watch", conclusion_label="买点观察", conclusion_color="yellow",
                     conclusion_reason=watch_triggers[0].get("detail",""))
        return
    # bullish
    if st == "strong_bullish" and T_BULL:
        if vs != "divergence" and pos != "overheated":
            entry.update(conclusion="bullish_strong", conclusion_label="短期强势", conclusion_color="green",
                         conclusion_reason=f"短期{sl}+长期{tl}共振")
        else:
            entry.update(conclusion="hold_watch", conclusion_label="观望持有", conclusion_color="yellow",
                         conclusion_reason=f"短期强势但{pos}过高")
        return
    if st == "strong_bullish" and T_BEAR:
        entry.update(conclusion="short_up_long_down", conclusion_label="短强长空", conclusion_color="yellow",
                     conclusion_reason=f"短期{sl}但长期{t}压制")
        return
    if st == "bullish" and T_BULL:
        entry.update(conclusion="bullish", conclusion_label="短期偏多", conclusion_color="green",
                     conclusion_reason=f"短期{sl}+长期{tl}配合")
        return
    if st == "bullish" and T_BEAR:
        entry.update(conclusion="short_up_long_down", conclusion_label="短线反弹", conclusion_color="yellow",
                     conclusion_reason=f"短期偏多但长期{tl}，谨慎追高")
        return
    if st == "recovering" and not T_STRONG_BEAR:
        entry.update(conclusion="recovering", conclusion_label="修复中", conclusion_color="yellow",
                     conclusion_reason=f"短期{sl}，关注能否转势")
        return
    if st == "recovering" and T_STRONG_BEAR:
        entry.update(conclusion="hold_watch", conclusion_label="观望持有", conclusion_color="yellow",
                     conclusion_reason="短期修复但长期强空压制")
        return
    # neutral
    if st == "neutral" and T_BULL:
        entry.update(conclusion="neutral_bullish", conclusion_label="横盘偏多", conclusion_color="yellow",
                     conclusion_reason=f"短期横盘，长期{tl}偏多")
        return
    if st == "neutral" and T_BEAR:
        entry.update(conclusion="neutral_bearish", conclusion_label="横盘偏空", conclusion_color="yellow",
                     conclusion_reason=f"短期横盘，长期{tl}偏空")
        return
    # bearish
    if ST_BEAR and vs == "divergence":
        entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red",
                     conclusion_reason=f"短期{sl}+量价背离")
        return
    if st == "bearish":
        if pos == "low" and not T_STRONG_BEAR:
            entry.update(conclusion="left_observe", conclusion_label="左侧观察", conclusion_color="yellow",
                         conclusion_reason=f"短期偏空但历史低位")
        else:
            entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red",
                         conclusion_reason=f"短期{sl}，回避")
        return
    if st == "strong_bearish":
        if T_BULL and pos == "low":
            entry.update(conclusion="short_down_long_up", conclusion_label="短空长多", conclusion_color="yellow",
                         conclusion_reason=f"短期{sl}但长期{tl}+低位")
        else:
            entry.update(conclusion="avoid", conclusion_label="回避", conclusion_color="red",
                         conclusion_reason=f"短期{sl}，回避")
        return
    if pos == "low" and not ST_BEAR:
        entry.update(conclusion="left_observe", conclusion_label="左侧观察", conclusion_color="yellow",
                     conclusion_reason="历史低位，等趋势反转")
        return
    if pos == "overheated":
        entry.update(conclusion="hold_watch", conclusion_label="观望持有", conclusion_color="yellow",
                     conclusion_reason="位置过热")
        return
    entry.update(conclusion="hold_watch", conclusion_label="观望持有", conclusion_color="yellow",
                 conclusion_reason="信号不明确，观望")


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
        if parsed.path == "/api/stock-candle-patterns":
            self.handle_stock_candle_patterns(parsed.query)
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
        if parsed.path == "/api/competitive-edge":
            self.handle_competitive_edge(parsed.query)
            return
        if parsed.path == "/api/data-update-status":
            self.handle_data_update_status(parsed.query)
            return
        if parsed.path == "/api/data-update-plan":
            self.handle_data_update_plan()
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
        if parsed.path == "/api/rps-trading-days":
            self.handle_rps_trading_days()
            return
        if parsed.path == "/api/concept-analysis":
            self.handle_concept_analysis(parsed.query)
            return
        if parsed.path == "/api/concept-cross":
            self.handle_concept_cross(parsed.query)
            return
        if parsed.path == "/api/watchlist":
            self.handle_watchlist_get()
            return
        if parsed.path == "/api/realtime-screener":
            self.handle_realtime_screener(parsed.query)
            return
        if parsed.path == "/api/concept-list":
            self.handle_concept_list(parsed.query)
            return
        # ── Bottleneck Discovery ──
        if parsed.path == "/api/bottleneck/step1":
            self.handle_bottleneck_step1(parsed.query)
            return
        if parsed.path == "/api/bottleneck/step2":
            self.handle_bottleneck_step2(parsed.query)
            return
        if parsed.path == "/api/bottleneck/step3":
            self.handle_bottleneck_step3(parsed.query)
            return
        if parsed.path == "/api/bottleneck/step4":
            self.handle_bottleneck_step4(parsed.query)
            return
        if parsed.path == "/api/bottleneck/step5":
            self.handle_bottleneck_step5(parsed.query)
            return
        if parsed.path == "/api/bottleneck/step6":
            self.handle_bottleneck_step6(parsed.query)
            return
        if parsed.path == "/api/bottleneck/auto":
            self.handle_bottleneck_auto(parsed.query)
            return
        if parsed.path == "/api/bottleneck/reports":
            self.handle_bottleneck_list_reports(parsed.query)
            return
        if parsed.path == "/api/bottleneck/report":
            self.handle_bottleneck_load_report(parsed.query)
            return
        if parsed.path == "/api/bottleneck/rerun":
            self.handle_bottleneck_rerun(parsed.query)
            return
        if parsed.path == "/api/bottleneck/report/delete":
            self.handle_bottleneck_delete_report(parsed.query)
            return
        if parsed.path == "/api/bottleneck/custom-status":
            self.handle_bottleneck_custom_status(parsed.query)
            return
        # ── End Bottleneck ──
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
        # ── End Bottleneck ──
        if parsed.path == "/api/save-capital-flow":
            self.handle_save_capital_flow()
            return
        if parsed.path == "/api/bottleneck/save-report":
            self.handle_bottleneck_save_report(parsed.query)
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
        if parsed.path == "/api/watchlist/add":
            self.handle_watchlist_add()
            return
        if parsed.path == "/api/kronos-predict":
            self.handle_kronos_predict()
            return
        if parsed.path == "/api/watchlist/remove":
            self.handle_watchlist_remove()
            return
        if parsed.path == "/api/watchlist/reorder":
            self.handle_watchlist_reorder()
            return
        if parsed.path == "/api/watchlist/clear":
            self.handle_watchlist_clear()
            return
        if parsed.path == "/api/competitive-edge":
            self.handle_competitive_edge("")
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

    def handle_stock_candle_patterns(self, query: str) -> None:
        """Return last N candlestick patterns for a stock."""
        from app.candlestick_patterns import _bar_type, PATTERNS
        from mootdx.reader import Reader
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        limit = min(int(params.get("limit", ["10"])[0]), 30)
        try:
            reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
            daily = reader.daily(symbol=symbol)
            if daily is None or daily.empty:
                self.respond_json(HTTPStatus.OK, {"ok": True, "patterns": []})
                return
            daily = daily.sort_index()
            bars = daily[["open", "high", "low", "close"]].to_dict("records")
            n = len(bars)
            result = []
            for i in range(max(0, n - limit), n):
                bar = bars[i]
                found = None
                for name, fn, lookback, direction in PATTERNS:
                    if lookback == 1:
                        try:
                            if fn(bar):
                                found = {"name": name, "direction": direction}
                                break
                        except Exception:
                            continue
                if not found:
                    try:
                        name, direction = _bar_type(bar)
                        found = {"name": name, "direction": direction}
                    except Exception:
                        found = {"name": "—", "direction": "neutral"}
                result.append(found)
            result.reverse()
            self.respond_json(HTTPStatus.OK, {"ok": True, "patterns": result})
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"ok": False, "error": str(exc)})

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
        try:
            from app.api.concept import handle_concept_list as _handle
            result = _handle(query)
            self.respond_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "concept_list_error", "message": str(exc)}},
            )

    def handle_stock_screener(self, query: str) -> None:
        params = {
            key: ",".join(v.strip() for v in values if v.strip())
            for key, values in parse_qs(query, keep_blank_values=True).items()
            if values
        }
        try:
            # Only ensure current strategy dataset when NOT in historical mode
            as_of_date = params.get("as_of_date", "").strip()
            if not as_of_date:
                ensure_stock_screener_strategy_dataset(params.get("strategy", ""))
            result = build_stock_screener_response(params)
            # Augment with swing low price for current page rows
            if result.get("rows"):
                from mootdx.reader import Reader
                reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
                for row in result["rows"]:
                    try:
                        daily = reader.daily(symbol=row["symbol"])
                        if daily is not None and not daily.empty and len(daily) >= 111:
                            daily = daily.sort_index()
                            # When historical date, truncate to as_of_date
                            if as_of_date:
                                daily = daily[daily.index <= as_of_date]
                            if len(daily) < 111:
                                row["swing_low_price"] = None
                                row["ma10_dist_pct"] = None
                                continue
                            lows = daily["low"].astype(float).tolist()
                            closes = daily["close"].astype(float).tolist()
                            n = len(lows)
                            # Search last 90 bars for most recent swing low
                            # (low < all 10 bars before AND < all 10 bars after)
                            swing_idx = None
                            search_end = n - 11  # need 10 bars after
                            search_start = max(0, n - 90)
                            for i in range(search_end - 1, search_start - 1, -1):
                                lo = lows[i]
                                before = lows[max(0, i - 10):i]
                                after = lows[i + 1:i + 11]
                                if all(lo < v for v in before) and all(lo < v for v in after):
                                    swing_idx = i
                                    break
                            if swing_idx is not None:
                                row["swing_low_price"] = round(closes[swing_idx], 2)
                            else:
                                # Fallback: lowest close in last 90 bars
                                fb_start = max(0, n - 90)
                                row["swing_low_price"] = round(min(closes[fb_start:]), 2)
                            # MA10 distance: (close - MA10) / MA10 * 100
                            if n >= 10:
                                ma10 = sum(closes[-10:]) / 10
                                row["ma10_dist_pct"] = round((closes[-1] - ma10) / ma10 * 100, 2) if ma10 != 0 else None
                            else:
                                row["ma10_dist_pct"] = None
                            # MA10 slope: daily rate of change of MA10 line
                            if n >= 11:
                                ma10_today = sum(closes[-10:]) / 10
                                ma10_yesterday = sum(closes[-11:-1]) / 10
                                if ma10_yesterday != 0:
                                    row["ma10_slope_pct"] = round((ma10_today - ma10_yesterday) / ma10_yesterday * 100, 2)
                            # MA30 slope: daily rate of change of MA30 line (uses as_of truncated data)
                            if n >= 31:
                                ma30_today = sum(closes[-30:]) / 30
                                ma30_yesterday = sum(closes[-31:-1]) / 30
                                if ma30_yesterday != 0:
                                    row["ma30_slope_pct"] = round((ma30_today - ma30_yesterday) / ma30_yesterday * 100, 2)
                        else:
                            row["swing_low_price"] = None
                            row["ma10_dist_pct"] = None
                    except Exception:
                        row["swing_low_price"] = None
            # Compute trend duration for current page rows
            if result.get("rows"):
                import glob, re
                if as_of_date:
                    # Load tech eval files with date <= as_of_date
                    pattern = str(DERIVED_FINAL_DIR / "dataset_technical_eval_*.json")
                    all_files = sorted(glob.glob(pattern), reverse=True)
                    prev_tech_days = []
                    for fp in all_files[:20]:
                        m = re.search(r'(\d{4}-\d{2}-\d{2})', fp)
                        if m and m.group(1) <= as_of_date:
                            try:
                                with open(fp) as f:
                                    data = json.load(f)
                                stocks = data.get("stocks", {}) if isinstance(data, dict) else {}
                                prev_tech_days.append({s: {"trend": v.get("trend"), "trend_label": v.get("trend_label"),
                                                              "short_trend": v.get("short_trend"), "short_trend_label": v.get("short_trend_label")}
                                                       for s, v in stocks.items()})
                            except Exception:
                                prev_tech_days.append({})
                else:
                    prev_tech_days = _load_prev_tech_evals(max_days=20)
                for row in result["rows"]:
                    try:
                        symbol = str(row.get("symbol", "")).zfill(6)
                        current_trend = str(row.get("tech_trend") or "")
                        duration = 1
                        if current_trend:
                            for day_data in prev_tech_days:
                                prev = day_data.get(symbol)
                                if prev and prev.get("trend") == current_trend:
                                    duration += 1
                                else:
                                    break
                        row["trend_duration"] = duration
                    except Exception:
                        row["trend_duration"] = 1
                    try:
                        current_short = str(row.get("tech_short_trend") or "")
                        short_dur = 1
                        if current_short:
                            for day_data in prev_tech_days:
                                prev = day_data.get(symbol)
                                if prev and prev.get("short_trend") == current_short:
                                    short_dur += 1
                                else:
                                    break
                        row["short_trend_duration"] = short_dur
                    except Exception:
                        row["short_trend_duration"] = 1
            # Augment with Kronos AI prediction
            if result.get("rows"):
                kronos_path = DERIVED_FINAL_DIR / "dataset_kronos_prediction.json"
                if kronos_path.exists():
                    try:
                        kronos_data = json.loads(kronos_path.read_text(encoding="utf-8"))
                        for row in result["rows"]:
                            key = f"{row.get('market', '')}:{row.get('symbol', '')}"
                            pred = kronos_data.get(key)
                            if pred:
                                row["pred_direction"] = pred.get("pred_direction")
                                row["pred_5d_pct"] = pred.get("pred_5d_pct")
                                row["pred_20d_pct"] = pred.get("pred_20d_pct")
                    except Exception:
                        pass
            self.respond_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "stock_screener_error", "message": str(exc)}},
            )

    def handle_kronos_predict(self) -> None:
        """On-demand Kronos prediction for a single stock. Body: {market, symbol}"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
            return

        market = str(body.get("market", "")).strip().lower()
        symbol = str(body.get("symbol", "")).strip()
        if not market or not symbol:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "market and symbol required"})
            return

        try:
            import sys as _sys
            _sys.path.insert(0, "/home/lufanfeng/Kronos")
            from model import Kronos, KronosTokenizer, KronosPredictor
            from mootdx.reader import Reader
            import pandas as pd

            tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
            model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
            predictor = KronosPredictor(model, tokenizer, max_context=400)

            reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
            daily = reader.daily(symbol=symbol)
            if daily is None or daily.empty or len(daily) < 450:
                self.respond_json(HTTPStatus.OK, {"ok": False, "error": "insufficient data"})
                return

            daily = daily.sort_index()
            n = len(daily)
            start = max(0, n - 400)
            df = daily[["open", "high", "low", "close", "volume"]].iloc[start:].copy()
            df["amount"] = (df["close"] * df["volume"] / 100).round(2)
            x_ts = pd.Series(daily.index[start:], name="timestamps")
            last_date = daily.index[-1]
            y_dates = pd.date_range(start=last_date, periods=21, freq="B")[1:]
            y_ts = pd.Series(y_dates, name="timestamps")

            pred_df = predictor.predict(
                df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=20,
                T=1.0, top_p=0.9, sample_count=1, verbose=False,
            )

            last_close = float(df["close"].iloc[-1])
            pred_5 = float(pred_df["close"].iloc[4]) if len(pred_df) > 4 else float(pred_df["close"].iloc[-1])
            pred_20 = float(pred_df["close"].iloc[-1])
            pct_5 = round((pred_5 / last_close - 1) * 100, 2)
            pct_20 = round((pred_20 / last_close - 1) * 100, 2)
            direction = "up" if pct_20 > 2 else ("down" if pct_20 < -2 else "flat")

            pred_bars = []
            for i in range(len(pred_df)):
                pred_bars.append({
                    "open": round(float(pred_df["open"].iloc[i]), 2),
                    "high": round(float(pred_df["high"].iloc[i]), 2),
                    "low": round(float(pred_df["low"].iloc[i]), 2),
                    "close": round(float(pred_df["close"].iloc[i]), 2),
                })

            result = {
                "market": market, "symbol": symbol,
                "last_close": round(last_close, 2),
                "pred_5d_pct": pct_5, "pred_20d_pct": pct_20,
                "pred_direction": direction,
                "pred_bars": pred_bars,
            }

            # Save to cache
            kronos_path = DERIVED_FINAL_DIR / "dataset_kronos_prediction.json"
            kronos_path.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if kronos_path.exists():
                try:
                    existing = json.loads(kronos_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            key = f"{market}:{symbol}"
            existing[key] = result
            kronos_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

            self.respond_json(HTTPStatus.OK, {"ok": True, **result})
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                              {"ok": False, "error": str(exc)})

    def handle_concept_analysis(self, query: str) -> None:
        """Search concept and return enriched stock list. Delegated to app.api.concept."""
        try:
            from app.api.concept import handle_concept_analysis as _handle
            result = _handle(query)
            status = result.pop("status", HTTPStatus.OK)
            self.respond_json(status, result)
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def handle_concept_cross(self, query: str) -> None:
        """Multi-concept intersection search. Delegated to app.api.concept."""
        try:
            from app.api.concept import handle_concept_cross as _handle
            result = _handle(query)
            status = result.pop("status", HTTPStatus.OK)
            self.respond_json(status, result)
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def handle_rps_trading_days(self) -> None:
        """Return sorted list of unique trading days from RPS history dataset."""
        try:
            history = _load_rps_history_dataset()
            days = sorted({str(r.get("trading_day", "")) for r in history if r.get("trading_day")})
            self.respond_json(HTTPStatus.OK, {"ok": True, "trading_days": days})
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "rps_trading_days_error", "message": str(exc)}},
            )

    # ── Watchlist handlers ───────────────────────────────────────────────

    def handle_watchlist_get(self) -> None:
        """Return watchlist with live score/tech/temp data."""
        wl = _load_watchlist()
        stocks_out = []

        if not wl.get("stocks"):
            self.respond_json(HTTPStatus.OK, {"stocks": []})
            return

        tech_data = _load_tech_eval()
        ind_temp = _load_industry_temp()

        # Init mootdx reader for price/return data
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)

        # Load a few historical tech eval files for trend duration
        prev_tech_days = _load_prev_tech_evals(max_days=20)

        for entry in wl["stocks"]:
            market = str(entry.get("market", ""))
            symbol = str(entry.get("symbol", ""))
            if not market or not symbol:
                continue

            row: dict = {
                "market": market,
                "symbol": symbol,
                "added_at": entry.get("added_at", ""),
                "add_price": entry.get("add_price"),
            }

            # Score data
            try:
                score = compute_stock_score(market, symbol)
                row["stock_name"] = score.get("stock_name", symbol)
                row["industry_level_1"] = score.get("ind1", "")
                row["industry_level_2"] = score.get("ind2", "")
                row["market_total_score"] = score.get("total_score")
                row["market_total_rank"] = score.get("market_total_rank")
                row["market_total_universe_size"] = score.get("market_total_universe_size")
                row["industry_total_score"] = score.get("ind_total_score")
                row["industry_total_rank"] = score.get("industry_total_rank")
                row["industry_total_universe_size"] = score.get("industry_total_universe_size")
                row["dim_scores"] = score.get("dim_scores", {})
            except Exception as e:
                row["_error"] = f"score: {e}"

            # RPS data from stock_profile
            if "_error" not in row:
                try:
                    profile = stock_profile_response(symbol)
                    if profile.get("ok"):
                        rps = profile.get("rps", {}) or {}
                        row["rps_20"] = rps.get("rps_20")
                        row["rps_50"] = rps.get("rps_50")
                        row["rps_120"] = rps.get("rps_120")
                        row["rps_250"] = rps.get("rps_250")
                except Exception:
                    pass

            # Tech data
            tech = tech_data.get(symbol.zfill(6), {})
            if tech:
                for field in ("trend", "trend_label", "momentum", "momentum_label",
                              "volume_signal", "volume_label",
                              "buy_trigger", "buy_trigger_label",
                              "short_trend", "short_trend_label",
                              "short_trend_prev", "short_trend_prev_label",
                              "conclusion", "conclusion_label", "conclusion_color", "conclusion_reason"):
                    row[f"tech_{field}"] = tech.get(field)

            # Industry temperature
            ind2 = row.get("industry_level_2", "")
            temp = ind_temp.get(ind2)
            if temp:
                row["industry_temperature_label"] = temp.get("label", "")
                row["industry_temperature_percentile_since_2022"] = temp.get("percentile")

            # Price / returns from mootdx kline
            if "_error" not in row:
                try:
                    daily = reader.daily(symbol=symbol)
                    if daily is not None and not daily.empty and len(daily) >= 21:
                        daily = daily.sort_index()
                        closes = daily["close"].tolist()
                        row["current_price"] = float(closes[-1])
                        row["return_1_pct"] = round((closes[-1] / closes[-2] - 1) * 100, 2)
                        row["return_5_pct"] = round((closes[-1] / closes[-6] - 1) * 100, 2)
                        row["return_20_pct"] = round((closes[-1] / closes[-21] - 1) * 100, 2)
                        # Return since added: find closes from add_date onwards
                        add_price = row.get("add_price")
                        add_date = (row.get("added_at", "") or "")[:10]
                        if add_price and add_price > 0 and add_date:
                            daily_dates = [str(d).split("T")[0] for d in daily.index]
                            since_closes = []
                            for i, d in enumerate(daily_dates):
                                if d >= add_date:
                                    since_closes.append(float(closes[i]))
                            if since_closes:
                                row["return_since_add_pct"] = round((since_closes[-1] / add_price - 1) * 100, 2)
                                row["max_return_pct"] = round((max(since_closes) / add_price - 1) * 100, 2)
                                row["max_loss_pct"] = round((min(since_closes) / add_price - 1) * 100, 2)
                        # MA10 distance
                        ma10 = sum(closes[-10:]) / 10
                        row["ma10_dist_pct"] = round((closes[-1] - ma10) / ma10 * 100, 2) if ma10 != 0 else None

                        # MA30 slope: daily rate of change of MA30 line
                        if len(closes) >= 31:
                            ma30_today = sum(closes[-30:]) / 30
                            ma30_yesterday = sum(closes[-31:-1]) / 30
                            if ma30_yesterday != 0:
                                row["ma30_slope_pct"] = round((ma30_today - ma30_yesterday) / ma30_yesterday * 100, 2)

                        # MA20 break detection: status + final return
                        add_date = (row.get("added_at", "") or "")[:10]
                        if add_price and add_price > 0 and add_date:
                            daily_dates_list = [str(d).split("T")[0] for d in daily.index]
                            start_idx = None
                            for j, d in enumerate(daily_dates_list):
                                if d >= add_date:
                                    start_idx = j
                                    break
                            if start_idx is not None:
                                row["status"] = "持有"
                                for j in range(max(start_idx, 19), len(closes)):
                                    ma20 = sum(closes[j-19:j+1]) / 20
                                    if closes[j] < ma20:
                                        sell_price = float(closes[j])
                                        row["status"] = "结束"
                                        row["sell_price"] = round(sell_price, 2)
                                        row["final_return_pct"] = round((sell_price - add_price) / add_price * 100, 2)
                                        break

                        # Candlestick pattern detection
                        try:
                            from app.candlestick_patterns import detect_latest_pattern
                            bars = daily[["open", "high", "low", "close"]].to_dict("records")
                            pattern = detect_latest_pattern(bars)
                            if pattern:
                                row["candle_pattern"] = pattern["name"]
                                row["candle_pattern_dir"] = pattern["direction"]
                        except Exception:
                            pass
                except Exception:
                    pass

            # Trend duration (延续天数)
            if "_error" not in row:
                try:
                    current_trend = row.get("tech_trend", "")
                    duration = 1
                    for day_data in prev_tech_days:
                        prev = day_data.get(symbol.zfill(6))
                        if prev and prev.get("trend") == current_trend:
                            duration += 1
                        else:
                            break
                    row["trend_duration"] = duration
                except Exception:
                    row["trend_duration"] = 1

            # Short trend duration
            if "_error" not in row:
                try:
                    current_short = row.get("tech_short_trend", "")
                    short_dur = 1
                    for day_data in prev_tech_days:
                        prev = day_data.get(symbol.zfill(6))
                        if prev and prev.get("short_trend") == current_short:
                            short_dur += 1
                        else:
                            break
                    row["short_trend_duration"] = short_dur
                except Exception:
                    row["short_trend_duration"] = 1

            stocks_out.append(row)

        # Sort by added_at descending (most recent first)
        stocks_out.sort(key=lambda r: str(r.get("added_at", "") or ""), reverse=True)

        # Compute overall portfolio return (equal-weighted)
        overall_return = None
        valid_returns = [r.get("return_since_add_pct") for r in stocks_out
                         if r.get("return_since_add_pct") is not None]
        if valid_returns:
            overall_return = round(sum(valid_returns) / len(valid_returns), 2)

        self.respond_json(HTTPStatus.OK, {
            "stocks": stocks_out,
            "overall_return_pct": overall_return,
        })

    def handle_watchlist_add(self) -> None:
        """Add stocks to watchlist. Body: {stocks: [{market, symbol}, ...], backtest_date?: 'YYYY-MM-DD'}
        When backtest_date is provided, uses the next trading day's open as benchmark price,
        and sets added_at to the backtest date."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON body"})
            return

        incoming = body.get("stocks")
        if not isinstance(incoming, list) or not incoming:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing stocks array"})
            return

        backtest_date = str(body.get("backtest_date", "")).strip()

        wl = _load_watchlist()
        existing = {(str(s["market"]), str(s["symbol"])) for s in wl.get("stocks", [])}
        added = 0
        skipped = 0
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # Try to get current prices for new additions
        from mootdx.reader import Reader
        reader = None
        try:
            reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
        except Exception:
            pass

        for s in incoming:
            key = (str(s.get("market", "")), str(s.get("symbol", "")))
            if not key[0] or not key[1]:
                continue
            if key in existing:
                skipped += 1
                continue

            added_at = now
            add_price = None

            if reader:
                try:
                    daily = reader.daily(symbol=key[1])
                    if daily is not None and not daily.empty and len(daily) >= 1:
                        daily = daily.sort_index()
                        if backtest_date:
                            # Backtest mode: use next trading day's open as benchmark
                            mask = daily.index > backtest_date
                            future = daily.loc[mask]
                            if not future.empty:
                                add_price = round(float(future.iloc[0]["open"]), 2)
                            else:
                                # No future data, use latest close
                                add_price = round(float(daily.iloc[-1]["close"]), 2)
                            added_at = backtest_date
                        else:
                            # Live mode: use latest close
                            add_price = round(float(daily.iloc[-1]["close"]), 2)
                except Exception:
                    pass

            entry = {"market": key[0], "symbol": key[1], "added_at": added_at}
            if add_price is not None:
                entry["add_price"] = add_price
            wl["stocks"].append(entry)
            existing.add(key)
            added += 1

        _save_watchlist(wl)
        self.respond_json(HTTPStatus.OK, {"ok": True, "added": added, "skipped": skipped})

    def handle_watchlist_remove(self) -> None:
        """Remove a stock from watchlist. Body: {market, symbol}"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON body"})
            return

        market = str(body.get("market", ""))
        symbol = str(body.get("symbol", ""))
        if not market or not symbol:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing market/symbol"})
            return

        wl = _load_watchlist()
        wl["stocks"] = [s for s in wl["stocks"] if not (s["market"] == market and s["symbol"] == symbol)]
        _save_watchlist(wl)
        self.respond_json(HTTPStatus.OK, {"ok": True})

    def handle_watchlist_reorder(self) -> None:
        """Reorder watchlist. Body: {stocks: [{market, symbol}, ...]}"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON body"})
            return

        incoming = body.get("stocks")
        if not isinstance(incoming, list):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing stocks array"})
            return

        wl = _load_watchlist()
        # Build lookup for original added_at
        orig = {(s["market"], s["symbol"]): s.get("added_at", "") for s in wl.get("stocks", [])}
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        new_stocks = []
        for s in incoming:
            key = (str(s.get("market", "")), str(s.get("symbol", "")))
            if not key[0] or not key[1]:
                continue
            new_stocks.append({"market": key[0], "symbol": key[1], "added_at": orig.get(key, now)})

        wl["stocks"] = new_stocks
        _save_watchlist(wl)
        self.respond_json(HTTPStatus.OK, {"ok": True})

    def handle_watchlist_clear(self) -> None:
        """Clear entire watchlist."""
        _save_watchlist({"stocks": []})
        self.respond_json(HTTPStatus.OK, {"ok": True})

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

    def handle_competitive_edge(self, query: str) -> None:
        """GET: return cached competitive edge. POST: save new data."""
        from app.competitive_edge import get_stock_competitive_edge, save_competitive_edge
        if self.command == "POST":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
                return
            market = str(body.get("market", "")).strip().lower()
            symbol = str(body.get("symbol", "")).strip()
            text = str(body.get("text", "")).strip()
            stock_name = str(body.get("stock_name", "")).strip()
            if not market or not symbol or not text:
                self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing market/symbol/text"})
                return
            result = save_competitive_edge(market, symbol, text, stock_name)
            self.respond_json(HTTPStatus.OK, {"ok": True, **result})
            return
        params = parse_qs(query)
        market = str(params.get("market", [""])[0]).strip().lower()
        symbol = str(params.get("symbol", [""])[0]).strip()
        stock_name = str(params.get("stock_name", [""])[0]).strip()
        auto_search = str(params.get("auto_search", [""])[0]).strip().lower() in ("1", "true", "yes")
        if not market or not symbol:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing market/symbol"})
            return
        try:
            result = get_stock_competitive_edge(market, symbol, stock_name, auto_search=auto_search)
            self.respond_json(HTTPStatus.OK, {"ok": True, **result})
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def handle_data_update_plan(self) -> None:
        """Return data freshness + pending task list with descriptions."""
        status = load_data_update_status()
        job = _data_update_job_snapshot()
        trading_day = _latest_trading_day_for_refresh()

        # Task definitions with descriptions
        today_str = datetime.now().strftime('%Y-%m-%d')
        tasks = []

        if trading_day and trading_day != today_str:
            tasks.append({
                'id': 'archive_daily',
                'name': '归档每日数据',
                'desc': f'归档交易日 {trading_day} 的日线/分钟线/快照数据',
            })
        tasks.extend([
            {'id': 'update_financial_ts', 'name': '更新财报时序库', 'desc': '检测通达信本地财报更新，增量追加到 Parquet 仓库'},
            {'id': 'build_financial_snapshot', 'name': '构建财务快照', 'desc': '基于最新财报生成全市场六维评分快照'},
            {'id': 'build_industry_relative_valuation_snapshot', 'name': '构建行业估值快照', 'desc': '逐行业计算 PE/PS 经验分位，覆盖 127 个二级行业'},
            {'id': 'build_rps_history', 'name': '构建 RPS 历史', 'desc': '计算全市场截面 RPS20/50/120/250，回溯 120 天'},
            {'id': 'update_rps_current', 'name': '更新当前 RPS', 'desc': '从历史 RPS 提取最新交易日数据'},
            {'id': 'rebuild_screener_rps_first', 'name': '重建 RPS首次 策略', 'desc': '重建 RPS首次进入前50 的选股策略结果'},
            {'id': 'rebuild_screener_ma_cross', 'name': '重建 均线选股 策略', 'desc': '重建均线多头排列选股策略结果'},
            {'id': 'rebuild_screener_blowup_stall', 'name': '重建 爆量滞涨 策略', 'desc': '重建放量滞涨预警策略结果'},
            {'id': 'rebuild_screener_blowup_break', 'name': '重建 爆量突破 策略', 'desc': '重建放量突破策略结果'},
            {'id': 'rebuild_screener_ma_pullback', 'name': '重建 均线回踩 策略', 'desc': '重建多头趋势回踩MA20支撑策略结果'},
            {'id': 'rebuild_macd_signals', 'name': '重建 MACD信号', 'desc': '全市场MACD二次金叉/金叉转强/背离信号检测'},
        ])

        # Determine which tasks are completed (based on current data freshness)
        snapshot_updated = status.get('financial_snapshot', {}).get('updated_at')

        self.respond_json(HTTPStatus.OK, {
            'ok': True,
            'current_status': {
                'financial_snapshot_updated': status.get('financial_snapshot', {}).get('updated_at'),
                'financial_report_date': status.get('financial_snapshot', {}).get('report_date'),
                'industry_valuation_updated': status.get('industry_valuation', {}).get('updated_at'),
                'industry_count': status.get('industry_valuation', {}).get('industry_count'),
                'latest_updated_at': status.get('latest_updated_at'),
            },
            'job': {
                'status': job.get('status', 'idle'),
                'running': job.get('running', False),
                'current_step': job.get('current_step'),
                'progress_index': job.get('progress_index'),
                'progress_total': job.get('progress_total'),
                'current_progress_text': job.get('current_progress_text', ''),
                'error': job.get('error'),
                'can_retry_failed': job.get('can_retry_failed', False),
            },
            'tasks': tasks,
        })

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
        try:
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
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "update_error", "message": str(exc)}},
            )

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

            # Recompute conclusion with short_trend as primary
            _recompute_conclusion_v2(entry)

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

    # ── Bottleneck Discovery Handlers ─────────────────────────

    def _respond_bottleneck(self, data: dict) -> None:
        """Helper: respond with bottleneck data as JSON."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_bottleneck_step1(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id")
        result = step1_select_trend(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_step2(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        custom_desc = qs.get("custom_description", "")
        result = step2_decompose_chain(trend_id, custom_desc)
        self._respond_bottleneck(result)

    def handle_bottleneck_step3(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        result = step3_identify_bottlenecks(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_step4(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        result = step4_map_stocks(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_step5(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        result = step5_verify_stocks(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_step6(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        result = step6_cross_verify(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_auto(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        trend_id = qs.get("trend_id", "")
        if not trend_id:
            self._respond_bottleneck({"ok": False, "error": "缺少 trend_id 参数"})
            return
        result = step7_full_auto(trend_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_list_reports(self, _query: str) -> None:
        result = list_reports()
        self._respond_bottleneck(result)

    def handle_bottleneck_load_report(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        filename = qs.get("filename", "")
        result = load_report(filename)
        self._respond_bottleneck(result)

    def handle_bottleneck_rerun(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        filename = qs.get("filename", "")
        if not filename:
            self._respond_bottleneck({"ok": False, "error": "缺少 filename 参数"})
            return
        result = rerun_report(filename)
        self._respond_bottleneck(result)

    def handle_bottleneck_delete_report(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        filename = qs.get("filename", "")
        if not filename:
            self._respond_bottleneck({"ok": False, "error": "缺少 filename 参数"})
            return
        result = delete_report(filename)
        self._respond_bottleneck(result)

    def handle_bottleneck_custom_status(self, query: str) -> None:
        qs = {k: v[0] for k, v in parse_qs(query).items()}
        session_id = qs.get("session_id", "")
        result = check_custom_status(session_id)
        self._respond_bottleneck(result)

    def handle_bottleneck_save_report(self, _query: str) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_len).decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._respond_bottleneck({"ok": False, "error": "Invalid JSON"})
            return
        trend_id = body.get("trend_id", "")
        step_results = body.get("step_results", {})
        result = save_report(trend_id, step_results)
        self._respond_bottleneck(result)

    # ── End Bottleneck Handlers ──────────────────────────────

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


