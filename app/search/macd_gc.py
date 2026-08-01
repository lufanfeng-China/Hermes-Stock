"""MACD Extreme Golden Cross — daily signal scan + portfolio state management.

Provides:
  - Scan CSI300 for buy / replenish / sell signals
  - Manage simulated portfolio state (open, replenish, sell, edit entries)
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.config import DERIVED_FINAL_DIR, TONGDAXIN_DIR

# ── Constants ──────────────────────────────────────────────────
NDIF_LOOSE = -1.0
NDIF_TIGHT = -3.0
PROFIT_TARGET = 0.20
REPLENISH_LOSS = -0.20
FLOOR_PCT = 0.15
CSI300_FILES = (
    DERIVED_FINAL_DIR / "csi300_constituents_current_20260728.json",
    Path("/tmp/csi300_constituents.json"),  # legacy temporary cache fallback
)
# v2 state: QFQ-generated signals must never share positions/history with legacy raw signals.
STATE_FILE = str(DERIVED_FINAL_DIR / "macd_gc_qfq_state.json")
DEFAULT_CAPITAL = 3_000_000
DEFAULT_LOT = 50_000


# ── State persistence ───────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "config": {"capital": DEFAULT_CAPITAL, "lot": DEFAULT_LOT},
        "cash": DEFAULT_CAPITAL,
        "positions": {},
        "history": [],
    }


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _init_if_needed(state: dict[str, Any]) -> None:
    """Ensure config values exist."""
    if "config" not in state:
        state["config"] = {"capital": DEFAULT_CAPITAL, "lot": DEFAULT_LOT}
    if "cash" not in state:
        state["cash"] = state["config"]["capital"]
    if "positions" not in state:
        state["positions"] = {}
    if "history" not in state:
        state["history"] = []


# ── Data helpers ────────────────────────────────────────────────

def _entry_price_percentile(
    frame: pd.DataFrame,
    entry_date: str | pd.Timestamp,
    *,
    window: int = 1200,
    min_periods: int = 240,
) -> float | None:
    """Return the entry-close rank in the trailing 5-year price window.

    The current-position table describes the *first entry's* price percentile,
    so it must be calculated as of that historical entry date rather than from
    today's close.  It matches the strategy's rolling-rank convention and
    returns None when too little price history exists.
    """
    try:
        as_of = pd.Timestamp(entry_date).normalize()
    except (TypeError, ValueError):
        return None
    closes = frame.loc[frame.index <= as_of, "close"].dropna().astype(float).tail(window)
    if len(closes) < min_periods:
        return None
    return round(float(closes.rank(pct=True).iloc[-1] * 100.0), 2)


def _signal_price_percentile(
    closes: np.ndarray | list[float],
    index: int,
    *,
    window: int = 1200,
    min_periods: int = 240,
) -> float | None:
    """Close-time trailing percentile for a signal; never reads a future bar."""
    if index < 0:
        return None
    values = pd.Series(closes[: index + 1], dtype="float64").dropna().tail(window)
    if len(values) < min_periods:
        return None
    return round(float(values.rank(pct=True).iloc[-1] * 100.0), 2)


def _history_rows_with_entry_percentiles(
    rows: list[dict[str, Any]],
    frame: pd.DataFrame,
    *,
    window: int = 1200,
    min_periods: int = 240,
) -> list[dict[str, Any]]:
    """Return API-only history rows enriched with their entry-day percentile.

    Historical state remains immutable: the percentile is a view field computed
    from the source daily bars whenever the scan endpoint is requested.
    """
    enriched = []
    for row in rows:
        copy = dict(row)
        copy["pct5y"] = _entry_price_percentile(
            frame, copy.get("entry_date"), window=window, min_periods=min_periods
        )
        enriched.append(copy)
    return enriched


def _load_csi300_codes() -> list[str]:
    constituent_file = next((path for path in CSI300_FILES if path.is_file()), None)
    if constituent_file is None:
        searched = ", ".join(str(path) for path in CSI300_FILES)
        raise FileNotFoundError(f"CSI300 constituent list is unavailable; searched: {searched}")
    with constituent_file.open(encoding="utf-8") as f:
        codes = sorted(set(str(c).zfill(6) for c in json.load(f)))
    if len(codes) != 300:
        raise ValueError(f"Expected 300 CSI300 constituents in {constituent_file}; got {len(codes)}")
    return codes


def _compute_indicators(c: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (ndif, ndea, ma10) arrays."""
    ema12 = pd.Series(c).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    ndif = np.zeros_like(c, dtype=float)
    ndea = np.zeros_like(c, dtype=float)
    np.divide(dif, c, out=ndif, where=c != 0)
    np.divide(dea, c, out=ndea, where=c != 0)
    ndif *= 100.0
    ndea *= 100.0
    n = len(c)
    ma10 = np.full(n, np.nan)
    for i in range(9, n):
        ma10[i] = float(np.mean(c[i - 9 : i + 1]))
    return ndif, ndea, ma10


def _get_stock_name(code: str) -> str:
    """Try to read stock name from project's security lookup."""
    try:
        from app.search.index import _stock_name_lookup
        market = "sh" if code.startswith(("6", "9")) else "sz"
        name = _stock_name_lookup().get((market, code), "")
        if name:
            return str(name)
    except Exception:
        pass
    return code


# ── Signal scan ─────────────────────────────────────────────────

def _scan_stock(code: str, dates: pd.DatetimeIndex,
                c: np.ndarray, o: np.ndarray,
                ndif: np.ndarray, ndea: np.ndarray, ma10: np.ndarray,
                positions_state: dict[str, Any],
                raw_closes: np.ndarray | None = None,
                date_from: pd.Timestamp | None = None,
                date_to: pd.Timestamp | None = None,
                ) -> tuple[list[dict], list[dict], list[dict]]:
    """Scan one stock using QFQ signal prices and raw execution/valuation prices."""
    n = len(c)
    if n < 61:
        return [], [], []
    raw_c = c if raw_closes is None else raw_closes
    if len(raw_c) != n:
        raise ValueError("raw_closes must have the same length as signal closes")

    name = _get_stock_name(code)
    buy_signals = []
    replenish_signals = []
    sell_candidates = []

    # Determine bar range to scan
    if date_from is not None or date_to is not None:
        # Scan all bars in range
        bar_range = range(60, n)
    else:
        # Scan only last bar
        bar_range = range(n - 1, n)

    for i in bar_range:
        if date_from is not None and dates[i] < date_from:
            continue
        if date_to is not None and dates[i] > date_to:
            continue

        signal_cp = c[i]
        raw_cp = raw_c[i]
        if np.isnan(signal_cp) or signal_cp <= 0 or np.isnan(raw_cp) or raw_cp <= 0:
            continue

        ndif_i, ndea_i = ndif[i], ndea[i]
        ndif_prev, ndea_prev = ndif[i - 1], ndea[i - 1]

        # ── Buy signal (ndif golden cross at extreme) ──
        if (not np.isnan(ndif_i) and not np.isnan(ndea_i)
                and not np.isnan(ndif_prev) and not np.isnan(ndea_prev)):
            is_golden = ndif_i > ndea_i and ndif_prev <= ndea_prev
            ma10_ok = (not np.isnan(ma10[i]) and not np.isnan(ma10[i - 1])
                       and ma10[i] > ma10[i - 1])
            signal_pct5y = _signal_price_percentile(c, i)
            if is_golden and ndif_i < NDIF_LOOSE and ma10_ok:
                tomorrow_open = o[i + 1] if i + 1 < n else None
                signal_date = str(dates[i].date()) if hasattr(dates[i], 'date') else str(dates[i])
                # Count consecutive MA10 rising days
                rise_days = 0
                for j in range(i, 0, -1):
                    if not np.isnan(ma10[j]) and not np.isnan(ma10[j - 1]) and ma10[j] > ma10[j - 1]:
                        rise_days += 1
                    else:
                        break
                buy_signals.append({
                    "code": code,
                    "name": name,
                    "signal_date": signal_date,
                    "close": round(float(raw_cp), 2),
                    "signal_close": round(float(signal_cp), 2),
                    "ndif": round(float(ndif_i), 2),
                    "signal_pct5y": signal_pct5y,
                    "ma10_rise_days": rise_days,
                    "tomorrow_open": round(float(tomorrow_open), 2) if tomorrow_open else None,
                    "lot": positions_state.get("config", {}).get("lot", DEFAULT_LOT),
                })

                # ── Replenish: this buy signal is also a replenish candidate if:
                #     the stock is already held AND signal date > entry date
                #     AND meets strategy conditions: loss > 20% AND ndif < -3%
                pos = positions_state.get("positions", {}).get(code)
                if pos:
                    entry_dates = [e["date"] for e in pos.get("entries", []) if e.get("date")]
                    earliest_entry = min(entry_dates) if entry_dates else ""
                    if not earliest_entry or signal_date > earliest_entry:
                        # Check strategy replenish conditions
                        entries = pos.get("entries", [])
                        total_cost = sum(e["price"] * e["shares"] for e in entries)
                        total_shares = sum(e["shares"] for e in entries)
                        loss_pct = (raw_cp * total_shares / total_cost - 1) * 100 if total_cost > 0 else 0
                        if loss_pct < REPLENISH_LOSS * 100 and ndif_i < NDIF_TIGHT:
                            lot = positions_state.get("config", {}).get("lot", DEFAULT_LOT)
                            replenish_signals.append({
                            "code": code,
                            "name": name,
                            "signal_date": signal_date,
                            "close": round(float(raw_cp), 2),
                            "signal_close": round(float(signal_cp), 2),
                            "loss_pct": 0,  # will be filled below
                            "ndif": round(float(ndif_i), 2),
                            "total_cost": 0,
                            "total_shares": 0,
                            "avg_cost": 0,
                            "lot": lot,
                            "replenish_qty": None,
                            "tomorrow_open": round(float(tomorrow_open), 2) if tomorrow_open else None,
                        })

        # ── Sell candidates (checked every bar, not just buy signal bars) ──
        pos = positions_state.get("positions", {}).get(code)
        if pos and not np.isnan(ndif_i) and not np.isnan(ndea_i) and not np.isnan(ndif_prev) and not np.isnan(ndea_prev):
            entries = pos.get("entries", [])
            total_cost = sum(e["price"] * e["shares"] for e in entries)
            total_shares = sum(e["shares"] for e in entries)
            current_value = raw_cp * total_shares
            pnl_pct = (current_value / total_cost - 1) * 100 if total_cost > 0 else 0

            # Sell candidates
            pos_triggered = pos.get("profit_triggered", False)
            if not pos_triggered and pnl_pct > PROFIT_TARGET * 100:
                pos_triggered = True

            if pos_triggered:
                is_deadcross = bool(ndif_i < ndea_i and ndif_prev >= ndea_prev)
                fell_below = bool(pnl_pct < FLOOR_PCT * 100)
                status = "等死叉"
                if fell_below:
                    status = "⚠破15%"
                if is_deadcross:
                    status = ("⚠死叉" + ("+破15%" if fell_below else ""))
                trigger_date = pos.get("trigger_date", str(dates[i]))
                # Earliest entry date
                entry_dates = [e["date"] for e in entries if e.get("date")]
                earliest = min(entry_dates) if entry_dates else ""
                sell_candidates.append({
                    "code": code,
                    "name": name,
                    "entry_date": earliest,
                    "close": round(float(raw_cp), 2),
                    "signal_close": round(float(signal_cp), 2),
                    "pnl_pct": round(float(pnl_pct), 2),
                    "total_cost": round(float(total_cost), 2),
                    "total_shares": total_shares,
                    "current_value": round(float(current_value), 2),
                    "status": status,
                    "is_deadcross": is_deadcross,
                    "fell_below": fell_below,
                    "trigger_date": trigger_date,
                    "tomorrow_open": round(float(o[i]), 2) if i + 1 >= n else round(float(o[i]), 2) if i < n else None,
                })

    return buy_signals, replenish_signals, sell_candidates


def scan_all(state: dict[str, Any], date_from: str = "", date_to: str = "", stock_code: str = "") -> dict[str, Any]:
    """Full scan with TDX-QFQ indicators and raw-price execution/MTM."""
    from mootdx.reader import Reader
    from app.tdx.qfq_kline import align_qfq_signal_with_raw_execution, load_tdx_qfq_daily

    # Determine codes to scan
    if stock_code:
        codes = [stock_code]
    else:
        codes = _load_csi300_codes()
        # Historical rows may include a former constituent.  Include it so the
        # page can still derive its entry-date percentile when local data exists.
        history_codes = {str(h.get("code", "")).zfill(6) for h in state.get("history", []) if h.get("code")}
        codes = sorted(set(codes) | history_codes)
    reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)

    # Parse dates
    df_ts = None
    dt_ts = None
    if date_from:
        try: df_ts = pd.Timestamp(date_from)
        except Exception: pass
    if date_to:
        try: dt_ts = pd.Timestamp(date_to)
        except Exception: pass

    # A persisted historical backtest must be valued at its own last MTM date,
    # not silently repriced with later daily bars.
    state_as_of = str(state.get("config", {}).get("as_of", "")).strip()
    state_as_of_ts = None
    if state_as_of:
        try:
            state_as_of_ts = pd.Timestamp(state_as_of)
        except Exception:
            state_as_of_ts = None

    has_range = df_ts is not None or dt_ts is not None or bool(stock_code)  # stock mode = scan all

    all_buy = []
    all_replenish = []
    all_sell = []
    positions_summary = []
    history_summary = [dict(row) for row in state.get("history", [])]
    history_indexes_by_code: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(history_summary):
        code = str(row.get("code", "")).zfill(6)
        if code:
            history_indexes_by_code[code].append(index)

    # Load industry map once
    from app.search.index import _load_industry_map as _load_ind_map
    industry_map = _load_ind_map()

    qfq_missing_codes: list[str] = []
    for code in codes:
        try:
            raw_df = reader.daily(code)
            if raw_df is None or len(raw_df) < 100:
                continue
            raw_df = raw_df.sort_index()
            qfq_df = load_tdx_qfq_daily(code)
            df = align_qfq_signal_with_raw_execution(raw_df, qfq_df)
            if len(df) < 100:
                continue
        except FileNotFoundError:
            qfq_missing_codes.append(code)
            continue
        except Exception:
            continue

        latest_close = float(df["raw_close"].iloc[-1])
        history_indexes = history_indexes_by_code.get(code, [])
        signal_frame = df[["signal_close"]].rename(columns={"signal_close": "close"})
        if history_indexes:
            history_rows = [history_summary[index] for index in history_indexes]
            enriched_rows = _history_rows_with_entry_percentiles(history_rows, signal_frame)
            for index, enriched in zip(history_indexes, enriched_rows):
                history_summary[index] = enriched
        # Truncate to the end of range if specified
        end_date = dt_ts or df_ts or state_as_of_ts
        if end_date is not None:
            df = df[df.index <= end_date]
            if len(df) < 100:
                continue
        c = df["signal_close"].values.astype(np.float64)
        o = df["raw_open"].values.astype(np.float64)
        raw_c = df["raw_close"].values.astype(np.float64)
        dates = pd.DatetimeIndex(df.index)
        ndif, ndea, ma10 = _compute_indicators(c)

        buys, reps, sells = _scan_stock(code, dates, c, o, ndif, ndea, ma10, state,
                                         raw_closes=raw_c, date_from=df_ts, date_to=dt_ts)
        # Add latest_close to buy signals
        for b in buys:
            b["latest_close"] = round(latest_close, 2)
        all_buy.extend(buys)
        all_replenish.extend(reps)
        all_sell.extend(sells)

        # Position summary
        pos = state.get("positions", {}).get(code)
        if pos:
            entries = pos.get("entries", [])
            total_cost = sum(e["price"] * e["shares"] for e in entries)
            total_shares = sum(e["shares"] for e in entries)
            cp = float(raw_c[-1]) if len(raw_c) > 0 else 0
            current_value = cp * total_shares
            pnl_pct = (current_value / total_cost - 1) * 100 if total_cost > 0 else 0

            entry_date = entries[0].get("date") if entries else None
            entry_pct5y = _entry_price_percentile(signal_frame, entry_date) if entry_date else None
            p_market = "sh" if code.startswith(("6", "9")) else "sz"
            positions_summary.append({
                "code": code,
                "name": pos.get("name", _get_stock_name(code)),
                "industry": industry_map.get((p_market, code), ("", ""))[0] or "其他",
                "entries": entries,
                "entry_pct5y": entry_pct5y,
                "total_cost": round(total_cost, 2),
                "total_shares": total_shares,
                "avg_cost": round(total_cost / total_shares, 2) if total_shares > 0 else 0,
                "close": round(cp, 2),
                "pnl_pct": round(pnl_pct, 2),
                "current_value": round(current_value, 2),
                "profit_triggered": pos.get("profit_triggered", False),
                "trigger_date": pos.get("trigger_date", ""),
            })

    # Sort buy signals by date
    all_buy.sort(key=lambda s: s.get("signal_date", ""))

    # Fill replenish signals with position cost data
    for r in all_replenish:
        pos = state.get("positions", {}).get(r["code"])
        if pos:
            entries = pos.get("entries", [])
            tc = sum(e["price"] * e["shares"] for e in entries)
            tq = sum(e["shares"] for e in entries)
            r["total_cost"] = round(tc, 2)
            r["total_shares"] = tq
            r["avg_cost"] = round(tc / tq, 2) if tq > 0 else 0
            r["loss_pct"] = round((r["close"] * tq / tc - 1) * 100, 2) if tc > 0 else 0
            r["replenish_qty"] = int(r["lot"] / r["close"]) if r["close"] > 0 else None

    # For replenish and sell, only dedupe in full-market mode
    # (specific stock mode: user wants to see all historical opportunities)
    if not stock_code:
        seen_rep = {}
        for r in all_replenish:
            seen_rep[r["code"]] = r
        all_replenish = list(seen_rep.values())

        seen_sell = {}
        for s in all_sell:
            seen_sell[s["code"]] = s
        all_sell = list(seen_sell.values())

    # Summary
    deployed = sum(p["current_value"] for p in positions_summary)
    cash = state.get("cash", state["config"]["capital"])
    realized_pnl = sum(h.get("pnl", 0) for h in state.get("history", []))
    realized_cost = sum(h.get("buy_cost", 0) for h in state.get("history", []))

    # Industry distribution
    industry_counts = {}
    for p in positions_summary:
        market = "sh" if p["code"].startswith(("6", "9")) else "sz"
        l2_name = industry_map.get((market, p["code"]), ("", ""))[0] or "其他"
        industry_counts[l2_name] = industry_counts.get(l2_name, 0) + 1
    industry_dist = [{"name": k, "count": v} for k, v in sorted(industry_counts.items(), key=lambda x: -x[1])]

    # History industry distribution
    history_industry_counts = {}
    for h in state.get("history", []):
        market = "sh" if h["code"].startswith(("6", "9")) else "sz"
        l2_name = industry_map.get((market, h["code"]), ("", ""))[0] or "其他"
        history_industry_counts[l2_name] = history_industry_counts.get(l2_name, 0) + 1
    history_industry_dist = [{"name": k, "count": v} for k, v in sorted(history_industry_counts.items(), key=lambda x: -x[1])]

    return {
        "today": state_as_of or str(date.today()),
        "data_basis": {
            "signal": "tdx_export_qfq",
            "execution": "tdx_raw",
            "valuation": "tdx_raw",
            "missing_qfq_codes": qfq_missing_codes,
        },
        "config": state.get("config", {}),
        "buy_signals": all_buy,
        "replenish_signals": all_replenish,
        "sell_candidates": all_sell,
        "positions": positions_summary,
        "history": history_summary,
        "industry_distribution": industry_dist,
        "history_industry_distribution": history_industry_dist,
        "summary": {
            "total_capital": state["config"]["capital"],
            "deployed": round(deployed, 2),
            "cash": round(cash, 2),
            "unrealized_pnl": round(sum(p["current_value"] - p["total_cost"] for p in positions_summary), 2),
            "equity": round(cash + sum(p["current_value"] for p in positions_summary), 2),
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl / realized_cost * 100, 2) if realized_cost > 0 else 0,
        },
    }


# ── State mutation API ──────────────────────────────────────────

def handle_open(code: str, shares: int, price: float, signal_date: str = "", ndif: float | None = None) -> dict[str, Any]:
    """Confirm a new position entry. Entry date = signal_date + 1 (T+1)."""
    state = _load_state()
    _init_if_needed(state)

    lot = state["config"]["lot"]
    name = _get_stock_name(code)

    if code in state.setdefault("positions", {}):
        return {"ok": False, "error": f"{code} 已有持仓，不能重复开仓"}

    # Default entry date: signal_date + 1 day (T+1), fallback to today
    if signal_date:
        from datetime import timedelta
        try:
            sd = datetime.strptime(signal_date, "%Y-%m-%d")
            entry_date = (sd + timedelta(days=1)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            entry_date = str(date.today())
    else:
        entry_date = str(date.today())

    entry = {"date": entry_date, "type": "开仓", "price": price, "shares": shares}
    if ndif is not None:
        entry["ndif"] = round(ndif, 2)

    state["positions"][code] = {
        "name": name,
        "entries": [entry],
        "profit_triggered": False,
        "trigger_date": "",
    }
    state["cash"] = state.get("cash", state["config"]["capital"]) - price * shares
    _save_state(state)

    return {"ok": True, "code": code, "name": name}


def handle_replenish(code: str, shares: int, price: float) -> dict[str, Any]:
    """Confirm a replenishment for an existing position."""
    state = _load_state()
    _init_if_needed(state)

    if code not in state.get("positions", {}):
        return {"ok": False, "error": f"{code} 无持仓，无法补仓"}

    state["positions"][code]["entries"].append({
        "date": str(date.today()), "type": "补仓", "price": price, "shares": shares,
    })
    state["cash"] = state.get("cash", state["config"]["capital"]) - price * shares
    _save_state(state)

    return {"ok": True, "code": code}


def handle_sell(code: str) -> dict[str, Any]:
    """Confirm a sale. Auto-detects exit reason from position state."""
    state = _load_state()
    _init_if_needed(state)

    if code not in state.get("positions", {}):
        return {"ok": False, "error": f"{code} 无持仓"}

    pos = state["positions"][code]
    entries = pos.get("entries", [])
    total_cost = sum(e["price"] * e["shares"] for e in entries)
    total_shares = sum(e["shares"] for e in entries)

    # Need current price — scan just this stock
    from mootdx.reader import Reader
    reader = Reader.factory(market="std", tdxdir=TONGDAXIN_DIR)
    try:
        df = reader.daily(code)
        if df is None or len(df) < 10:
            return {"ok": False, "error": "无法获取行情"}
        df = df.sort_index()
        close_price = float(df["close"].iloc[-1])
        open_next = float(df["open"].iloc[-1])  # approximate
        c = df["close"].values.astype(np.float64)
        ndif, ndea, ma10 = _compute_indicators(c)
    except Exception:
        return {"ok": False, "error": "获取行情异常"}

    sell_price = open_next if open_next > 0 else close_price
    sell_revenue = sell_price * total_shares
    pnl = sell_revenue - total_cost

    # Determine exit reason
    triggered = pos.get("profit_triggered", False)
    if not triggered:
        exit_reason = "手动卖出"
    else:
        i = len(c) - 1
        is_dc = bool(ndif[i] < ndea[i] and ndif[i - 1] >= ndea[i - 1])
        pnl_pct = (sell_revenue / total_cost - 1) * 100 if total_cost > 0 else 0
        fell = pnl_pct < FLOOR_PCT * 100

        if is_dc and fell:
            exit_reason = "死叉+破15%卖出"
        elif is_dc:
            exit_reason = "死叉卖出"
        elif fell:
            exit_reason = "止盈卖出(破15%)"
        else:
            exit_reason = "止盈卖出"

    state.setdefault("history", []).append({
        "date": str(date.today()),
        "code": code,
        "name": pos.get("name", ""),
        "exit_reason": exit_reason,
        "buy_cost": round(total_cost, 2),
        "sell_rev": round(sell_revenue, 2),
        "pnl": round(pnl, 2),
    })

    # Add proceeds to cash
    state["cash"] = state.get("cash", state["config"]["capital"]) + sell_revenue
    del state["positions"][code]
    _save_state(state)

    return {"ok": True, "code": code, "exit_reason": exit_reason, "pnl": round(pnl, 2)}


def handle_edit_entry(code: str, index: int, price: float, shares: int, date_str: str = "") -> dict[str, Any]:
    """Edit an existing entry (open or replenish) for a position."""
    state = _load_state()
    _init_if_needed(state)

    if code not in state.get("positions", {}):
        return {"ok": False, "error": f"{code} 无持仓"}

    entries = state["positions"][code]["entries"]
    if index < 0 or index >= len(entries):
        return {"ok": False, "error": f"序号 {index} 超出范围"}

    old = entries[index]
    old_cost = old["price"] * old["shares"]

    entries[index]["price"] = price
    entries[index]["shares"] = shares
    if date_str:
        entries[index]["date"] = date_str
    new_cost = price * shares

    # Adjust cash for the difference
    state["cash"] = state.get("cash", state["config"]["capital"]) + (old_cost - new_cost)
    _save_state(state)

    return {"ok": True, "code": code, "index": index}


def handle_config(capital: int, lot: int) -> dict[str, Any]:
    """Update global config."""
    state = _load_state()
    _init_if_needed(state)
    state["config"]["capital"] = capital
    state["config"]["lot"] = lot
    state["cash"] = capital  # reset cash
    _save_state(state)
    return {"ok": True, "config": state["config"]}


def build_monthly_mtm(daily_equity: list[dict]) -> list[dict]:
    """Compress strict daily MTM components to the last trading day of each month."""
    if not daily_equity:
        return []
    frame = pd.DataFrame(daily_equity)
    required = {"date", "cash", "market_value", "equity"}
    if not required.issubset(frame.columns):
        return []
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").set_index("date")
    monthly = frame[["cash", "market_value", "equity"]].resample("ME").last().dropna()
    return [
        {
            "month": index.strftime("%Y-%m"),
            "cash": round(float(row.cash), 2),
            "market_value": round(float(row.market_value), 2),
            "equity": round(float(row.equity), 2),
        }
        for index, row in monthly.iterrows()
    ]


def compute_equity_history() -> list[dict]:
    """Return monthly strict-MTM cash, market value, and equity trend data."""
    import json

    monthly_path = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final" / "macd_gc_equity_monthly.json"
    if monthly_path.exists():
        try:
            with monthly_path.open(encoding="utf-8") as handle:
                history = json.load(handle)
            if isinstance(history, list) and history:
                return history
        except (OSError, json.JSONDecodeError):
            pass
    return []
