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
)
from app.industry.heatmap import DEFAULT_INDUSTRY_LIMIT, industry_heatmap_response
from app.relative_valuation.service import build_relative_valuation_result
from app.search.macd_gc import (  # MACD Extreme Golden Cross
    scan_all, handle_open, handle_replenish, handle_sell, handle_edit_entry, handle_config,
    _load_state, _init_if_needed,
)
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


def _prev_year_period(period: str) -> str:
    """返回上年同期财报期，如 2026Q1 → 2025Q1, 2025A → 2024A"""
    year = int(period[:4])
    suffix = period[4:]
    return f"{year - 1}{suffix}"


def _next_period(period: str) -> str:
    """返回下一财报期，如 2026Q1 → 2026Q2, 2025Q3 → 2025A"""
    year = int(period[:4])
    suffix = period[4:]
    if suffix == "Q1":
        return f"{year}Q2"
    elif suffix == "Q2":
        return f"{year}Q3"
    elif suffix == "Q3":
        return f"{year}A"
    else:  # A
        return f"{year + 1}Q1"


def _enrich_rows_pe_pct(rows: list) -> None:
    """给rows列表中的每行添加pe_pct字段（5年PE-TTM分位）"""
    try:
        from pathlib import Path as _Path
        import pandas as _pd
        db_path = _Path("data/derived/pe_ttm_quarterly.parquet")
        if not db_path.exists():
            return
        pe_db = _pd.read_parquet(db_path)
        latest = pe_db.sort_values("period").groupby("code").last()
        pe_lookup = latest["pe_pct"].to_dict()
        for row in rows:
            code = str(row.get("symbol", "")).zfill(6)
            val = pe_lookup.get(code)
            row["pe_pct"] = round(float(val), 1) if val is not None and not _pd.isna(val) else None
    except Exception:
        pass


def _enrich_rows_gap_up(rows: list) -> None:
    """给rows列表中的每行添加gap_up字段：
    Y-未补: 公告日后第一个交易日跳空高开（最低价 > 前日最高价），至今未回补
    Y-已补: 公告日后第一个交易日跳空高开，但后续有交易日最低价 <= 前日最高价
    N: 未跳空高开（最低价 <= 前日最高价）
    """
    import pandas as pd
    from mootdx.reader import Reader

    reader = Reader.factory(market="std", tdxdir="/home/lufanfeng/tdx_data")

    for row in rows:
        sym = row["symbol"]
        ad_str = row.get("announce_date", "")
        if not ad_str:
            row["gap_up"] = "N"
            continue

        try:
            daily = reader.daily(symbol=sym)
        except Exception:
            row["gap_up"] = "N"
            continue
        if daily is None or daily.empty:
            row["gap_up"] = "N"
            continue

        daily = daily.sort_index()
        try:
            ad_ts = pd.Timestamp(ad_str)
        except Exception:
            row["gap_up"] = "N"
            continue

        # 找公告日之后的第一个交易日
        after = daily[daily.index > ad_ts]
        if len(after) == 0:
            row["gap_up"] = "N"
            continue

        post_day = after.iloc[0]
        post_day_ts = after.index[0]
        post_low = float(post_day["low"])

        # 找post_day之前的那个交易日
        before = daily[daily.index < post_day_ts]
        if len(before) == 0:
            row["gap_up"] = "N"
            continue
        prev_high = float(before.iloc[-1]["high"])

        # 判断是否跳空高开：后一日最低价 > 前一日最高价
        if post_low <= prev_high:
            row["gap_up"] = "N"
            continue

        # 跳空高开，检查后续是否有交易日回补（最低价 <= 前日最高价即回补）
        after_post = daily[daily.index > post_day_ts]
        filled = False
        for i in range(len(after_post)):
            day_low = float(after_post.iloc[i]["low"])
            if day_low <= prev_high:
                filled = True
                break

        row["gap_up"] = "Y-已补" if filled else "Y-未补"


def _compute_forecast_3d_returns(rows: list) -> None:
    """计算业绩预告的3日涨跌幅：预告日收盘买入，T+3日收盘卖出"""
    import pandas as pd
    from mootdx.reader import Reader

    reader = Reader.factory(market="std", tdxdir="/home/lufanfeng/tdx_data")

    for row in rows:
        sym = row["symbol"]
        fcast_date = row.get("forecast_date", "")
        if not fcast_date:
            row["return_3d"] = None
            continue

        try:
            daily = reader.daily(symbol=sym)
        except Exception:
            row["return_3d"] = None
            continue
        if daily is None or daily.empty:
            row["return_3d"] = None
            row["current_price"] = None
            continue

        daily = daily.sort_index()
        # 当前股价 = 最新收盘价
        row["current_price"] = float(daily.iloc[-1]["close"])

        # 预告日期格式: "YY-MM-DD" → "20YY-MM-DD"
        parts = fcast_date.split("-")
        if len(parts) != 3:
            row["return_3d"] = None
            continue
        full_date = f"20{parts[0]}-{parts[1]}-{parts[2]}"
        try:
            fcast_ts = pd.Timestamp(full_date)
        except Exception:
            row["return_3d"] = None
            continue

        # 找预告日当天或之前最近的一个交易日作为入场日
        up_to = daily[daily.index <= fcast_ts]
        if len(up_to) == 0:
            row["return_3d"] = None
            continue

        entry_bar = up_to.iloc[-1]  # 最近交易日
        entry = float(entry_bar["close"])
        entry_date = entry_bar.name

        # 从入场日开始往后找3个交易日
        after_entry = daily[daily.index > entry_date]
        if len(after_entry) >= 3:
            exit_p = float(after_entry.iloc[2]["close"])  # T+3 收盘
        elif len(after_entry) > 0:
            exit_p = float(daily.iloc[-1]["close"])  # 未满3日，用最新收盘价
        else:
            exit_p = entry  # 无后续数据

        if entry == 0:
            row["return_3d"] = None
        else:
            row["return_3d"] = round((exit_p - entry) / entry * 100, 2)


def _compute_returns(rows: list, current_period: str) -> None:
    """计算每只股票的收益率：公告日后第2个交易日开盘买入，下期公告日收盘或当前价卖出"""
    import pandas as pd
    from pathlib import Path
    from mootdx.reader import Reader

    next_pd = _next_period(current_period)
    ds_dir = Path("data/derived/financial_ts/by_quarter")

    # 加载下一期公告日期
    next_announce = {}
    np_path = ds_dir / f"{next_pd}.parquet"
    if np_path.exists():
        ndf = pd.read_parquet(np_path)
        ndf["ad"] = ndf["announce_date"].astype("Int64")
        for code in ndf.index:
            ad = ndf.loc[code, "ad"]
            if pd.notna(ad):
                next_announce[str(code).zfill(6)] = str(int(ad))

    reader = Reader.factory(market="std", tdxdir="/home/lufanfeng/tdx_data")
    today_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    for row in rows:
        sym = row["symbol"]
        ad_str = row.get("announce_date", "")
        if not ad_str:
            row["return_pct"] = None
            continue

        try:
            daily = reader.daily(symbol=sym)
        except Exception:
            row["return_pct"] = None
            continue
        if daily is None or daily.empty:
            row["return_pct"] = None
            continue

        daily = daily.sort_index()
        ad_ts = pd.Timestamp(ad_str)

        # 找公告日后第2个交易日
        after = daily[daily.index > ad_ts]
        if len(after) < 2:
            row["return_pct"] = None
            continue
        entry = float(after.iloc[1]["open"])  # 第2个交易日开盘价

        # 找卖出价：下一期公告日收盘 或 当前最新收盘
        exit_price = None
        nxt = next_announce.get(sym)
        if nxt:
            nxt_ts = pd.Timestamp(f"{nxt[:4]}-{nxt[4:6]}-{nxt[6:]}")
            nxt_bars = daily[daily.index == nxt_ts]
            if len(nxt_bars) > 0:
                exit_price = float(nxt_bars.iloc[0]["close"])

        if exit_price is None:
            exit_price = float(daily.iloc[-1]["close"])

        pct = round((exit_price - entry) / entry * 100, 2)
        row["return_pct"] = pct


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
        if parsed.path == "/api/stock-pe-history":
            self.handle_stock_pe_history(parsed.query)
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
        if parsed.path == "/api/concept-temperature":
            self.handle_concept_temperature(parsed.query)
            return
        if parsed.path == "/api/concept-temperature/members":
            self.handle_concept_temperature_members(parsed.query)
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
        if parsed.path == "/api/stock-buyback":
            self.handle_stock_buyback(parsed.query)
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
        if parsed.path == "/api/concept-list":
            self.handle_concept_list(parsed.query)
            return
        # ── MACD Extreme Golden Cross ──
        if parsed.path == "/api/macd-extreme-gc":
            self.handle_macd_gc_scan(parsed.query)
            return
        if parsed.path == "/api/macd-extreme-gc/equity-history":
            self.handle_macd_gc_equity_history()
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
        if parsed.path == "/api/financial-periods":
            self.handle_financial_periods()
            return
        if parsed.path == "/api/financial-upcoming":
            self.handle_financial_upcoming(parsed.query)
            return
        if parsed.path == "/api/financial-published":
            self.handle_financial_published(parsed.query)
            return
        if parsed.path == "/api/financial-forecast":
            self.handle_financial_forecast(parsed.query)
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
        # ── MACD Extreme Golden Cross ──
        if parsed.path == "/api/macd-extreme-gc/open":
            self.handle_macd_gc_open()
            return
        if parsed.path == "/api/macd-extreme-gc/replenish":
            self.handle_macd_gc_replenish()
            return
        if parsed.path == "/api/macd-extreme-gc/sell":
            self.handle_macd_gc_sell()
            return
        if parsed.path == "/api/macd-extreme-gc/entry":
            self.handle_macd_gc_edit_entry()
            return
        if parsed.path == "/api/macd-extreme-gc/config":
            self.handle_macd_gc_config()
            return
        if parsed.path == "/api/macd-extreme-gc/backtest-summary":
            self.handle_macd_gc_backtest_summary()
            return
        if parsed.path == "/api/macd-extreme-gc/backtest":
            self.handle_macd_gc_backtest()
            return
        # ── MACD Extreme Golden Cross ──
        if parsed.path == "/api/macd-extreme-gc/equity-history":
            self.handle_macd_gc_equity_history()
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

    def handle_stock_pe_history(self, query: str) -> None:
        """Return quarterly PE-TTM history for a stock."""
        import pandas as pd
        from pathlib import Path
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            db_path = Path(PROJECT_ROOT) / "data" / "derived" / "pe_ttm_quarterly.parquet"
            if not db_path.exists():
                self.respond_json(HTTPStatus.OK, {"ok": False, "error": "PE database not found"})
                return
            pe_db = pd.read_parquet(db_path)
            stock_data = pe_db[pe_db["code"] == symbol].copy()
            # Sort chronologically: Q1(1) < Q2(2) < Q3(3) < A(4)
            def _period_sort_key(p):
                year = int(p[:4])
                suffix = p[4:]
                q = {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}.get(suffix, 0)
                return year * 10 + q
            stock_data["_sort_key"] = stock_data["period"].apply(_period_sort_key)
            stock_data = stock_data.sort_values("_sort_key").drop(columns=["_sort_key"])
            if stock_data.empty:
                self.respond_json(HTTPStatus.OK, {"ok": True, "symbol": symbol, "history": []})
                return
            # Select and format the data
            cols = ["period", "pe_ad", "eps", "ttm_eps", "close_ad", "pe_pct", "ind_median_pe"]
            available = [c for c in cols if c in stock_data.columns]
            history = stock_data[available].to_dict(orient="records")
            # Convert NaN to None for JSON
            for row in history:
                for k, v in list(row.items()):
                    if pd.isna(v):
                        row[k] = None
            # Compute current real-time PE (latest close / latest ttm_eps)
            current_pe = None
            try:
                latest_row = stock_data.iloc[-1]
                latest_ttm = latest_row.get("ttm_eps")
                if latest_ttm is not None and not pd.isna(latest_ttm) and float(latest_ttm) > 0:
                    from mootdx.reader import Reader
                    reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
                    daily = reader.daily(symbol=symbol)
                    if daily is not None and not daily.empty:
                        daily = daily.sort_index()
                        cur_close = float(daily.iloc[-1]["close"])
                        current_pe = round(cur_close / float(latest_ttm), 2)
            except Exception:
                pass
            self.respond_json(HTTPStatus.OK, {"ok": True, "symbol": symbol, "history": history, "current_pe": current_pe})
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "pe_history_unavailable", "message": str(exc)}},
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

    def handle_financial_periods(self) -> None:
        """返回可选的财报期列表"""
        import os
        from pathlib import Path
        p = Path("data/derived/financial_ts/by_quarter")
        periods = sorted(
            [f.stem for f in p.glob("*.parquet") if f.stem != "latest"],
            reverse=True
        )
        periods = [p for p in periods if len(p) >= 5 and (p.endswith("A") or p.endswith(("1", "2", "3")))]
        self.respond_json(HTTPStatus.OK, {"ok": True, "periods": periods})

    def handle_financial_upcoming(self, query: str) -> None:
        """未来3天将公布财报的股票"""
        import pandas as pd
        from datetime import datetime, timedelta
        from app.search.index import load_security_rows

        params = parse_qs(query)
        period = params.get("period", [""])[0].strip()
        if not period:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少period参数"})
            return

        path = f"data/derived/financial_ts/by_quarter/{period}.parquet"
        df = pd.read_parquet(path)
        df["ann_date_int"] = df["announce_date"].astype("Int64")

        today = datetime.now()
        cutoff = int((today + timedelta(days=3)).strftime("%Y%m%d"))
        today_int = int(today.strftime("%Y%m%d"))

        upcoming = df[(df["ann_date_int"] >= today_int) & (df["ann_date_int"] <= cutoff)]
        if upcoming.empty:
            self.respond_json(HTTPStatus.OK, {"ok": True, "rows": []})
            return

        securities = {str(s.get("symbol")).strip(): str(s.get("stock_name", "")).strip()
                      for s in load_security_rows()}
        rows = []
        for code in upcoming.index:
            name = securities.get(str(code).zfill(6), code)
            ad = upcoming.loc[code, "ann_date_int"]
            if pd.isna(ad):
                continue
            ad_str = str(int(ad))
            rows.append({
                "symbol": str(code).zfill(6),
                "stock_name": name,
                "announce_date": f"{ad_str[:4]}-{ad_str[4:6]}-{ad_str[6:]}",
            })
        self.respond_json(HTTPStatus.OK, {"ok": True, "rows": rows})

    def handle_financial_published(self, query: str) -> None:
        """已公布财报列表，支持排序和分页"""
        import pandas as pd
        from app.search.index import load_security_rows

        params = parse_qs(query)
        period = params.get("period", [""])[0].strip()
        sort_by = params.get("sort", ["deducted_roe"])[0].strip()
        order = params.get("order", ["desc"])[0].strip()
        compute_return = params.get("compute_return", ["0"])[0].strip() == "1"
        page = int(params.get("page", ["1"])[0].strip())
        page_size = min(int(params.get("page_size", ["100"])[0].strip()), 200)
        if page < 1:
            page = 1

        if not period:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少period参数"})
            return

        path = f"data/derived/financial_ts/by_quarter/{period}.parquet"
        df = pd.read_parquet(path)
        df["ann_date_int"] = df["announce_date"].astype("Int64")

        # Only stocks that have announced (announce_date <= today)
        today_int = int(__import__("datetime").datetime.now().strftime("%Y%m%d"))
        published = df[df["ann_date_int"] <= today_int]

        securities = {str(s.get("symbol")).strip(): str(s.get("stock_name", "")).strip()
                      for s in load_security_rows()}

        # Load same period last year for YoY comparison
        prev_period = _prev_year_period(period)
        prev_path = f"data/derived/financial_ts/by_quarter/{prev_period}.parquet"
        prev_df = None
        try:
            prev_df = pd.read_parquet(prev_path)
        except Exception:
            pass

        rows = []
        for code in published.index:
            name = securities.get(str(code).zfill(6), str(code))
            row = published.loc[code]

            # 扣非ROE = 扣非净利润 / 归母权益 * 100
            deducted_np = float(row.get("扣除非经常性损益后的净利润", 0) or 0)
            equity = float(row.get("归属于母公司股东权益(资产负债表)", 0) or 0)
            deducted_roe = round(deducted_np / equity * 100, 2) if equity else None

            # 归母净利润
            net_profit = float(row.get("归属于母公司所有者的净利润", 0) or 0)

            # 扣非净利润同比
            deducted_np_yoy = float(row.get("扣非净利润同比(%)", 0) or 0)

            # YoY comparison
            prev_deducted_roe = None
            prev_net_profit = None
            prev_deducted_np_yoy = None
            if prev_df is not None and code in prev_df.index:
                pr = prev_df.loc[code]
                p_dnp = float(pr.get("扣除非经常性损益后的净利润", 0) or 0)
                p_eq = float(pr.get("归属于母公司股东权益(资产负债表)", 0) or 0)
                prev_deducted_roe = round(p_dnp / p_eq * 100, 2) if p_eq else None
                prev_net_profit = float(pr.get("归属于母公司所有者的净利润", 0) or 0)
                prev_deducted_np_yoy = float(pr.get("扣非净利润同比(%)", 0) or 0)

            ad = row.get("ann_date_int")
            ad_str = f"{str(int(ad))[:4]}-{str(int(ad))[4:6]}-{str(int(ad))[6:]}" if pd.notna(ad) else ""

            rows.append({
                "symbol": str(code).zfill(6),
                "stock_name": name,
                "announce_date": ad_str,
                "deducted_roe": deducted_roe,
                "deducted_roe_prev": prev_deducted_roe,
                "net_profit": round(net_profit / 10000, 2),  # 转为亿
                "net_profit_prev": round(prev_net_profit / 10000, 2) if prev_net_profit else None,
                "deducted_np_yoy": round(deducted_np_yoy, 2),
                "deducted_np_yoy_prev": round(prev_deducted_np_yoy, 2) if prev_deducted_np_yoy else None,
            })

        # Sort
        if sort_by == "deducted_roe":
            rows.sort(key=lambda r: r["deducted_roe"] or -9999, reverse=(order == "desc"))
        elif sort_by == "net_profit":
            rows.sort(key=lambda r: r["net_profit"] or -9999, reverse=(order == "desc"))
        elif sort_by == "deducted_np_yoy":
            rows.sort(key=lambda r: r["deducted_np_yoy"] or -9999, reverse=(order == "desc"))
        elif sort_by == "return_pct":
            rows.sort(key=lambda r: r["return_pct"] if r["return_pct"] is not None else -9999, reverse=(order == "desc"))
        elif sort_by == "pe_pct":
            rows.sort(key=lambda r: r.get("pe_pct") if r.get("pe_pct") is not None else -1, reverse=(order == "desc"))

        # ── 计算收益率（按需）──
        if compute_return:
            _compute_returns(rows, period)
            # 如果按收益率排序，需要重排
            if sort_by == "return_pct":
                rows.sort(key=lambda r: r.get("return_pct") if r.get("return_pct") is not None else -9999, reverse=(order == "desc"))

        # PE分位 enrichment
        _enrich_rows_pe_pct(rows)

        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        end = start + page_size
        paged_rows = rows[start:end]

        # 高开 enrichment（仅当前页，避免全量加载日线超时）
        _enrich_rows_gap_up(paged_rows)

        self.respond_json(HTTPStatus.OK, {
            "ok": True,
            "rows": paged_rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })

    def handle_financial_forecast(self, query: str) -> None:
        """返回最新业绩预告列表（基于监控快照），支持分页"""
        import json
        import pandas as pd
        from pathlib import Path
        from app.search.index import load_security_rows

        params = parse_qs(query)
        page = int(params.get("page", ["1"])[0].strip())
        page_size = min(int(params.get("page_size", ["50"])[0].strip()), 200)
        if page < 1:
            page = 1
        sort_by = params.get("sort", ["forecast_date"])[0].strip()
        order = params.get("order", ["desc"])[0].strip()
        # 过滤参数
        growth_min = params.get("growth_min", [""])[0].strip()
        profit_min_yi = params.get("profit_min", [""])[0].strip()  # 亿
        date_from = params.get("date_from", [""])[0].strip()

        snapshot_dir = Path("data/derived/financial_ts/forecast_snapshots")
        if not snapshot_dir.exists():
            self.respond_json(HTTPStatus.OK, {"ok": True, "rows": [], "total": 0,
                                              "message": "暂无业绩预告快照"})
            return

        snapshots = sorted(snapshot_dir.glob("forecast_*.parquet"))
        if not snapshots:
            self.respond_json(HTTPStatus.OK, {"ok": True, "rows": [], "total": 0,
                                              "message": "暂无业绩预告快照"})
            return

        df = pd.read_parquet(snapshots[-1])

        securities = {str(s.get("symbol")).strip(): str(s.get("stock_name", "")).strip()
                      for s in load_security_rows()}

        # 加载行业映射
        import json as _json
        industry_map = {}
        try:
            ind_data = _json.loads(Path("data/derived/datasets/final/dataset_stock_industry_current.json").read_text())
            for item in ind_data:
                sym = str(item.get("symbol", "")).strip()
                l2 = item.get("industry_level_2_name", "")
                if sym and l2:
                    industry_map[sym] = l2
        except Exception:
            pass

        # 加载细分龙头映射
        niche_map = {}  # code -> niche_category
        try:
            niche_path = Path("data/derived/datasets/final/dataset_niche_leaders.parquet")
            if niche_path.exists():
                niche_df = pd.read_parquet(niche_path)
                for _, nr in niche_df.iterrows():
                    if nr.get("is_niche_leader"):
                        code = str(nr.get("symbol", "")).zfill(6)
                        cat = str(nr.get("niche_category", ""))
                        if code and cat and cat != "未明确":
                            niche_map[code] = cat
        except Exception:
            pass

        rows = []
        for code in df.index:
            name = df.loc[code, "name"] if "name" in df.columns and pd.notna(df.loc[code, "name"]) and str(df.loc[code, "name"]).strip() else ""
            if not name:
                name = securities.get(str(code).zfill(6), str(code))

            fcast_date = str(df.loc[code, "预告日期"]) if "预告日期" in df.columns else ""
            lo_pct = float(df.loc[code, "业绩预告-本期净利润同比增幅下限%"]) if "业绩预告-本期净利润同比增幅下限%" in df.columns and pd.notna(df.loc[code, "业绩预告-本期净利润同比增幅下限%"]) else None
            hi_pct = float(df.loc[code, "业绩预告-本期净利润同比增幅上限%"]) if "业绩预告-本期净利润同比增幅上限%" in df.columns and pd.notna(df.loc[code, "业绩预告-本期净利润同比增幅上限%"]) else None
            lo_amt = float(df.loc[code, "业绩预告-本期净利润下限(万元)"]) if "业绩预告-本期净利润下限(万元)" in df.columns and pd.notna(df.loc[code, "业绩预告-本期净利润下限(万元)"]) else None
            hi_amt = float(df.loc[code, "业绩预告-本期净利润上限(万元)"]) if "业绩预告-本期净利润上限(万元)" in df.columns and pd.notna(df.loc[code, "业绩预告-本期净利润上限(万元)"]) else None

            rows.append({
                "symbol": str(code).zfill(6),
                "stock_name": name,
                "forecast_date": fcast_date,
                "profit_growth_lo": round(lo_pct, 1) if lo_pct is not None else None,
                "profit_growth_hi": round(hi_pct, 1) if hi_pct is not None else None,
                "net_profit_lo": lo_amt,
                "net_profit_hi": hi_amt,
                "industry_l2": industry_map.get(str(code).zfill(6), ""),
                "current_price": None,
                "niche_leader": niche_map.get(str(code).zfill(6), ""),
            })

        # ── 计算3日涨跌幅和当前股价 ──
        _compute_forecast_3d_returns(rows)

        # 排序
        reverse = order == "desc"
        if sort_by == "forecast_date":
            rows.sort(key=lambda r: r["forecast_date"] or "", reverse=reverse)
        elif sort_by == "profit_growth":
            rows.sort(key=lambda r: r["profit_growth_lo"] if r["profit_growth_lo"] is not None else -99999, reverse=reverse)
        elif sort_by == "net_profit":
            def _avg_np(r):
                lo = r["net_profit_lo"] or 0
                hi = r["net_profit_hi"] or 0
                return (lo + hi) / 2
            rows.sort(key=_avg_np, reverse=reverse)
        elif sort_by == "return_3d":
            rows.sort(key=lambda r: r.get("return_3d") if r.get("return_3d") is not None else -99999, reverse=reverse)
        elif sort_by == "current_price":
            rows.sort(key=lambda r: r.get("current_price") if r.get("current_price") is not None else -1, reverse=reverse)
        elif sort_by == "pe_pct":
            rows.sort(key=lambda r: r.get("pe_pct") if r.get("pe_pct") is not None else -1, reverse=reverse)
        else:
            rows.sort(key=lambda r: r["forecast_date"] or "", reverse=reverse)

        # 过滤
        if growth_min:
            try:
                gmin = float(growth_min)
                rows = [r for r in rows if r["profit_growth_lo"] is not None and r["profit_growth_lo"] >= gmin]
            except ValueError:
                pass
        if profit_min_yi:
            try:
                pmin = float(profit_min_yi) * 10000  # 亿→万
                rows = [r for r in rows if r["net_profit_lo"] is not None and r["net_profit_lo"] >= pmin]
            except ValueError:
                pass
        if date_from:
            rows = [r for r in rows if r.get("forecast_date", "") >= date_from]

        # PE分位 enrichment
        _enrich_rows_pe_pct(rows)

        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        end = start + page_size
        paged_rows = rows[start:end]

        self.respond_json(HTTPStatus.OK, {
            "ok": True,
            "rows": paged_rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })

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
            # Augment with PE分位 from quarterly database + apply filter
            if result.get("rows"):
                self._enrich_pe_percentile(result, params)
            # Apply 股价新高 filter
            new_high = params.get("price_new_high", "").strip()
            if new_high and result.get("rows"):
                result["rows"] = self._filter_price_new_high(result["rows"], new_high, TONGDAXIN_DIR, as_of_date)
                result["total"] = len(result["rows"])
                result["total_pages"] = max(1, (result["total"] + int(params.get("page_size", "50") or "50") - 1) // int(params.get("page_size", "50") or "50"))
            self.respond_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "stock_screener_error", "message": str(exc)}},
            )

    @staticmethod

    def _enrich_pe_percentile(result: dict, params: dict) -> None:
        """Load PE分位 data and enrich screener rows. Apply min/max pe_pct filter."""
        import pandas as pd
        from pathlib import Path
        try:
            db_path = Path(PROJECT_ROOT) / "data" / "derived" / "pe_ttm_quarterly.parquet"
            if not db_path.exists():
                return
            pe_db = pd.read_parquet(db_path)
            # Get latest period's pe_pct for each code
            latest = pe_db.sort_values("period").groupby("code").last()
            pe_lookup = latest["pe_pct"].to_dict()
            # Enrich rows
            for row in result["rows"]:
                code = row.get("symbol", "")
                row["pe_pct"] = pe_lookup.get(code)
            # Apply filter if requested
            min_raw = params.get("min_pe_pct", "").strip()
            max_raw = params.get("max_pe_pct", "").strip()
            if min_raw or max_raw:
                min_val = float(min_raw) if min_raw else None
                max_val = float(max_raw) if max_raw else None
                filtered = []
                for row in result["rows"]:
                    pct = row.get("pe_pct")
                    if pct is None:
                        continue
                    if min_val is not None and pct < min_val:
                        continue
                    if max_val is not None and pct > max_val:
                        continue
                    filtered.append(row)
                result["rows"] = filtered
                result["total"] = len(filtered)
        except Exception:
            pass

    @staticmethod
    def _enrich_pe_divergence(result: dict, params: dict) -> None:
        """PE背离: EPS-TTM连增但股价连跌，连续N期。"""
        import pandas as pd
        from pathlib import Path
        try:
            n_raw = params.get("pe_divergence", "").strip()
            if not n_raw:
                return
            N = int(n_raw)
            if N < 1:
                return
            db_path = Path(PROJECT_ROOT) / "data" / "derived" / "pe_ttm_quarterly.parquet"
            if not db_path.exists():
                return
            pe_db = pd.read_parquet(db_path)
            # For each stock, check last N+1 periods
            filtered = []
            for row in result["rows"]:
                code = row.get("symbol", "")
                stock_data = pe_db[pe_db["code"] == code].sort_values("period")
                if len(stock_data) < N + 1:
                    continue
                # Check last N consecutive pairs
                last_N1 = stock_data.tail(N + 1)
                eps_vals = last_N1["ttm_eps"].values
                close_vals = last_N1["close_ad"].values
                ok = True
                for i in range(1, N + 1):
                    eps_up = eps_vals[i] > eps_vals[i - 1]
                    price_down = close_vals[i] < close_vals[i - 1]
                    if not (eps_up and price_down):
                        ok = False
                        break
                if ok:
                    row["pe_divergence"] = True
                    filtered.append(row)
                # else: skip this row entirely (filter it out)
            result["rows"] = filtered
            result["total"] = len(filtered)
        except Exception:
            pass

    @staticmethod
    def _filter_price_new_high(rows: list, mode: str, tdxdir: str, as_of_date: str) -> list:
        """Filter rows to only those at a price new high (1y/2y/3y/all)."""
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir=tdxdir)
        days_map = {"1y": 250, "2y": 500, "3y": 750}
        lookback = days_map.get(mode, None)  # None = all history
        filtered = []
        for row in rows:
            try:
                daily = reader.daily(symbol=row["symbol"])
                if daily is None or daily.empty:
                    continue
                daily = daily.sort_index()
                if as_of_date:
                    daily = daily[daily.index <= as_of_date]
                closes = daily["close"].astype(float).values
                if len(closes) < 2:
                    filtered.append(row)
                    continue
                current = closes[-1]
                if lookback:
                    window = closes[-(lookback + 1):-1] if len(closes) > lookback else closes[:-1]
                else:
                    window = closes[:-1]  # all history except today
                if len(window) == 0 or current >= window.max():
                    filtered.append(row)
            except Exception:
                pass  # skip stocks we can't read
        return filtered

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

    def handle_concept_temperature(self, query: str) -> None:
        """Return precomputed concept heat rows, optionally filtered by temperature."""
        try:
            from app.api.concept_temperature import handle_concept_temperature as _handle
            result = _handle(query)
            status = result.pop('status', HTTPStatus.OK)
            self.respond_json(status, result)
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'ok': False, 'error': str(exc)})

    def handle_concept_temperature_members(self, query: str) -> None:
        """Return a selected concept's members ordered by QFQ interval return."""
        try:
            from app.api.concept_temperature import handle_concept_temperature_members as _handle
            result = _handle(query)
            status = result.pop('status', HTTPStatus.OK)
            self.respond_json(status, result)
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'ok': False, 'error': str(exc)})

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

    def handle_stock_buyback(self, query: str) -> None:
        """返回股票的回购/增持记录"""
        import json as _json
        from pathlib import Path
        params = parse_qs(query)
        symbol = str(params.get("symbol", [""])[0]).strip()
        if not symbol:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing symbol"})
            return
        symbol = symbol.zfill(6)

        # Load buyback dataset
        ds_path = Path("data/derived/datasets/final/dataset_stock_buyback.json")
        if not ds_path.exists():
            self.respond_json(HTTPStatus.OK, {"ok": True, "has_buyback": False, "has_increase": False, "records": []})
            return

        data = _json.loads(ds_path.read_text(encoding="utf-8"))
        match = None
        for r in data:
            if r.get("symbol") == symbol:
                match = r
                break

        if not match:
            self.respond_json(HTTPStatus.OK, {"ok": True, "has_buyback": False, "has_increase": False, "records": []})
            return

        # Get detailed concept records from extern_sys.txt
        detail_records = []
        try:
            with open("/mnt/c/new_tdx64/T0002/signals/extern_sys.txt", "r", encoding="gbk", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split("|")
                    if len(parts) < 4:
                        continue
                    if parts[1] != symbol:
                        continue
                    concepts = parts[3]
                    if "回购" not in concepts and "增持" not in concepts:
                        continue
                    if "股票质押回购" in concepts or "卖出回购" in concepts or "约定购回" in concepts:
                        if "回购计划" not in concepts and "回购注销" not in concepts and "股份回购" not in concepts:
                            continue
                    # Skip analyst ratings
                    import re
                    if re.match(r'^\S+证券\s+增持\s+(维持|首次|调低|调高|未知)\s+目标价:', concepts):
                        continue
                    detail_records.append(concepts)
        except Exception:
            pass

        self.respond_json(HTTPStatus.OK, {
            "ok": True,
            "has_buyback": match.get("has_buyback", False),
            "has_increase": match.get("has_increase", False),
            "buyback_types": match.get("buyback_types", []),
            "increase_count": match.get("increase_count", 0),
            "records": detail_records,
        })

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
            {'id': 'fetch_financial_online', 'name': '在线获取最新财报', 'desc': '从新浪财经接口拉取最新财报数据（含 Q2 季报）'},
            {'id': 'build_financial_snapshot', 'name': '构建财务快照', 'desc': '基于最新财报生成全市场六维评分快照'},
            {'id': 'build_industry_relative_valuation_snapshot', 'name': '构建行业估值快照', 'desc': '逐行业计算 PE/PS 经验分位，覆盖 127 个二级行业'},
            {'id': 'build_rps_history', 'name': '构建 RPS 历史', 'desc': '计算全市场截面 RPS20/50/120/250，回溯 120 天'},
            {'id': 'update_rps_current', 'name': '更新当前 RPS', 'desc': '从历史 RPS 提取最新交易日数据'},
            {'id': 'rebuild_screener_rps_first', 'name': '重建 RPS首次 策略', 'desc': '重建 RPS首次进入前50 的选股策略结果'},
            {'id': 'rebuild_screener_ath', 'name': '重建 历史新高 策略', 'desc': '重建 历史新高 + RPS>360 选股策略结果'},
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

    # ── MACD Extreme Golden Cross Handlers ────────────────────

    def handle_macd_gc_scan(self, query: str) -> None:
        params = {k: v[0] for k, v in parse_qs(query).items()}
        df_param = params.get("date_from", "")
        dt_param = params.get("date_to", "")
        stock = params.get("stock", "")

        state = _load_state()
        _init_if_needed(state)

        try:
            result = scan_all(state, df_param, dt_param, stock)
            self.respond_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": str(exc)})

    def handle_macd_gc_open(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        result = handle_open(body["code"], body["shares"], body["price"],
                             body.get("signal_date", ""), body.get("ndif"))
        self.respond_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)

    def handle_macd_gc_replenish(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        result = handle_replenish(body["code"], body["shares"], body["price"])
        self.respond_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)

    def handle_macd_gc_sell(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        result = handle_sell(body["code"])
        self.respond_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)

    def handle_macd_gc_edit_entry(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        result = handle_edit_entry(body["code"], body["index"], body["price"], body["shares"],
                                   body.get("date", ""))
        self.respond_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)

    def handle_macd_gc_config(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        result = handle_config(body["capital"], body["lot"])
        self.respond_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)

    def handle_macd_gc_equity_history(self) -> None:
        from app.search.macd_gc import compute_equity_history
        result = compute_equity_history()
        self.respond_json(HTTPStatus.OK, {"ok": True, "history": result})

    def handle_macd_gc_backtest_summary(self) -> None:
        """Run isolated QFQ backtests for the page's exit parameters and three capital tiers."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        start = str(body.get("start") or "2012-01-01")
        lot = int(body.get("lot", 50_000))
        profit_target = float(body.get("profit_target", 20))
        retrace_floor = float(body.get("retrace_floor", 15))
        if lot <= 0 or profit_target <= 0 or retrace_floor < 0 or retrace_floor >= profit_target:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "参数无效：卖出触发必须大于回撤触发"})
            return
        import subprocess
        from datetime import date as _date
        rows = []
        for capital in (3_000_000, 6_000_000, 10_000_000):
            payload = {"start": start, "capital": capital, "lot": lot,
                       "profit_target": profit_target, "retrace_floor": retrace_floor,
                       "write_output": False}
            result = subprocess.run(
                ["/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python3",
                 "/home/lufanfeng/Project-Hermes-Stock/scripts/run_macd_backtest_v2_cash_mtm.py",
                 json.dumps(payload)], capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0 or "OK|" not in result.stdout:
                self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": result.stderr or result.stdout})
                return
            parts = next(line for line in result.stdout.splitlines() if line.startswith("OK|")).split("|")
            equity = float(parts[5])
            years = max((_date(2026, 7, 24) - _date.fromisoformat(start)).days / 365.25, 1 / 365.25)
            rows.append({"capital": capital, "finalEquity": round(equity, 2),
                         "totalReturnPct": round((equity / capital - 1) * 100, 2),
                         "annualizedReturnPct": round(((equity / capital) ** (1 / years) - 1) * 100, 2),
                         "openPositions": int(parts[1]), "closedPositions": int(parts[2]),
                         "executed": int(parts[3]), "rejectedForCash": int(parts[4])})
        self.respond_json(HTTPStatus.OK, {"ok": True, "start": start, "asOf": "2026-07-24", "lotCash": lot,
                                          "profitTarget": profit_target, "retraceFloor": retrace_floor,
                                          "entryRule": f"NDIF<-1% + MACD金叉 + MA10上升；浮盈>{profit_target:g}%后，回撤<{retrace_floor:g}%或死叉卖出",
                                          "method": "QFQ 信号 + 原始价成交/严格 MTM", "rows": rows})

    def handle_macd_gc_backtest(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        start = body.get("start", "2024-01-01")
        capital = int(body.get("capital", 10_000_000))
        lot = int(body.get("lot", 50_000))
        profit_target = float(body.get("profit_target", 20))
        retrace_floor = float(body.get("retrace_floor", 15))
        if profit_target <= 0 or retrace_floor < 0 or retrace_floor >= profit_target:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "卖出触发必须大于回撤触发，且回撤触发不能为负数"})
            return

        import subprocess, os
        # Clear old MTM caches
        eq_paths = (
            "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_equity_weekly.json",
            "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_equity_monthly.json",
        )
        for eq_path in eq_paths:
            if os.path.exists(eq_path):
                os.remove(eq_path)
        
        # Run backtest
        result = subprocess.run(
            ["/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python3",
             "/home/lufanfeng/Project-Hermes-Stock/scripts/run_macd_backtest_v2_cash_mtm.py",
             json.dumps({"start": start, "capital": capital, "lot": lot,
                         "profit_target": profit_target, "retrace_floor": retrace_floor})],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0 and "OK" in result.stdout:
            parts = result.stdout.strip().split("|")
            self.respond_json(HTTPStatus.OK, {
                "ok": True,
                "positions": int(parts[1]),
                "history": int(parts[2]),
                "executed": int(parts[3]),
                "rejected": int(parts[4]),
                "equity": int(parts[5]),
            })
        else:
            self.respond_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": result.stderr or result.stdout})

    # ── End MACD GC Handlers ──────────────────────────────────
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


