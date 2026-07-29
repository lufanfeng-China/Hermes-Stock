#!/usr/bin/env python3
"""Run backtest + generate FULL mark-to-market weekly equity curve"""
import json, numpy as np, pandas as pd, os, sys
from collections import defaultdict
from pathlib import Path
from mootdx.reader import Reader

args = json.loads(sys.argv[1])
START = args["start"]
INIT = args["capital"]
LOT = args["lot"]
END = "2026-07-25"
LOOKBACK = f"{int(START[:4])-1}-07-01" if int(START[:4]) > 2011 else "2011-12-01"
STATE_FILE = "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_state.json"
MTM_FILE = "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_equity_weekly.json"

CONSTITUENT_FILES = (
    Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/csi300_constituents_current_20260728.json"),
    Path("/tmp/csi300_constituents.json"),  # legacy temporary cache fallback
)
constituent_file = next((path for path in CONSTITUENT_FILES if path.is_file()), None)
if constituent_file is None:
    searched = ", ".join(str(path) for path in CONSTITUENT_FILES)
    raise FileNotFoundError(f"CSI300 constituent list is unavailable; searched: {searched}")
with constituent_file.open(encoding="utf-8") as f:
    codes = sorted(set(str(c).zfill(6) for c in json.load(f)))
if len(codes) != 300:
    raise ValueError(f"Expected 300 CSI300 constituents in {constituent_file}; got {len(codes)}")
reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")

# ── Step 1: generate all signals ──
all_signals = []
stock_data = {}  # code -> DataFrame for MTM later
for code in codes:
    try:
        df = reader.daily(code)
        if df is None or len(df) < 100: continue
    except: continue
    df = df.sort_index()
    mask = (df.index >= LOOKBACK) & (df.index <= END)
    df = df[mask].copy(); n = len(df)
    if n < 100: continue
    
    # Save for MTM
    stock_data[code] = df.copy()
    
    c = df["close"].values.astype(float); o = df["open"].values.astype(float)
    dates = pd.DatetimeIndex(df.index)
    e12 = pd.Series(c).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c).ewm(span=26, adjust=False).mean().values
    d = e12 - e26; de = pd.Series(d).ewm(span=9, adjust=False).mean().values
    nd = np.where(c != 0, d/c*100, 0); na = np.where(c != 0, de/c*100, 0)
    ma = np.full(n, np.nan)
    for i in range(9, n): ma[i] = np.mean(c[i-9:i+1])
    
    lots = []; ed = None; en = None; triggered = False
    for i in range(60, n):
        cp = c[i]
        if np.isnan(cp) or cp <= 0: continue
        if lots:
            tc = sum(p*q for p,q in lots); tq = sum(q for _,q in lots)
            if triggered:
                is_dc = nd[i] < na[i] and nd[i-1] >= na[i-1]
                fell = cp * tq / tc - 1 < 0.15
                if is_dc or fell:
                    si = i+1
                    if si < n:
                        sp = o[si]; sv = sp * tq
                        reason = "死叉卖出" if is_dc else "止盈卖出(破15%)"
                        if is_dc and fell: reason = "死叉+破15%卖出"
                        all_signals.append(("exit", ed, code, dates[si], tc, sv, sv-tc, en, reason))
                        lots = []; ed = None; en = None; triggered = False
                    continue
            elif cp * tq / tc - 1 > 0.20: triggered = True
        if np.isnan(nd[i]) or np.isnan(na[i]) or np.isnan(nd[i-1]) or np.isnan(na[i-1]): continue
        if not (nd[i] > na[i] and nd[i-1] <= na[i-1] and nd[i] < -1.0): continue
        if np.isnan(ma[i]) or np.isnan(ma[i-1]): continue
        if ma[i] <= ma[i-1]: continue
        if lots:
            tc = sum(p*q for p,q in lots); tq = sum(q for _,q in lots)
            if cp * tq / tc - 1 < -0.20 and nd[i] < -3.0:
                ri = i+1
                if ri < n:
                    rq = int(LOT / o[ri])
                    if rq > 0: lots.append((o[ri], rq))
        if not lots:
            bi = i+1
            if bi < n:
                qty = int(LOT / o[bi])
                if qty > 0 and dates[bi] >= pd.Timestamp(START):
                    lots = [(o[bi], qty)]; ed = dates[bi]; en = nd[i]; triggered = False
                    all_signals.append(("entry", ed, code, None, sum(p*q for p,q in lots), qty, o[bi], en))

all_signals.sort(key=lambda x: x[1])
entries = [s for s in all_signals if s[0] == "entry"]
exits_d = defaultdict(list)
for s in all_signals:
    if s[0] == "exit":
        _, entry_d, code, exit_d, cost, rev, pnl, _, reason = s
        exits_d[exit_d].append((entry_d, code, rev, pnl, cost, reason))

# ── Step 2: simulate with daily granularity, capture weekly MTM ──
active = {}; eq = INIT; cash = INIT
active_shares = {}  # (entry_d, code) -> shares
dr = pd.date_range(START, END, freq="D")
ei = 0; acc = 0; rej = 0; tot = len(entries)
history = []
active_details = {}

weeks = pd.date_range(pd.Timestamp(f"{START[:4]}-01-01"), pd.Timestamp.today(), freq="W")
mtm_result = []
wi = 0

for d in dr:
    d_str = str(d.date())
    
    if d in exits_d:
        for ed2, code, rev, pnl, cost, reason in exits_d[d]:
            k = (ed2, code)
            if k in active:
                del active[k]
                if k in active_shares: del active_shares[k]
                eq += pnl; cash += rev
                history.append({
                    "date": d_str, "entry_date": str(ed2.date()), "code": code,
                    "exit_reason": reason, "buy_cost": round(cost,2), "sell_rev": round(rev,2), "pnl": round(pnl,2)
                })
    while ei < tot:
        _, entry_d, code, _, cost, shares, price, ndif_v = entries[ei]
        if entry_d > d: break
        if entry_d == d:
            if len(active) < int(eq / LOT):
                active[(entry_d, code)] = cost
                active_shares[(entry_d, code)] = shares
                active_details[(entry_d, code)] = {"shares": shares, "price": price, "ndif": ndif_v}
                cash -= price * shares; acc += 1
            else: rej += 1
            ei += 1
        else: ei += 1
    
    # Weekly MTM snapshot
    while wi < len(weeks) and str(weeks[wi].date()) <= d_str:
        # Compute MTM: cash + market value of all open positions at this day's prices
        total_mv = 0
        for k, cost in active.items():
            entry_d2, code = k
            df = stock_data.get(code)
            if df is not None and len(df) > 0:
                # Find the row for this date (or closest before)
                date_key = str(weeks[wi].date())
                try:
                    idx = df.index.searchsorted(pd.Timestamp(date_key))
                    if idx >= len(df): idx = len(df) - 1
                    if idx > 0 and df.index[idx] > pd.Timestamp(date_key): idx -= 1
                    close = float(df["close"].iloc[idx])
                except:
                    close = 0
                if close > 0:
                    shares = active_shares.get(k, 0)
                    total_mv += close * shares
                else:
                    total_mv += cost
            else:
                total_mv += cost
        
        mtm_result.append({"week": str(weeks[wi].date()), "equity": cash + total_mv})
        eq = cash + total_mv  # update tracking equity to MTM
        wi += 1

# ── Step 3: save state ──
sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.search.index import _stock_name_lookup
name_lookup = _stock_name_lookup()
def get_name(code):
    market = "sh" if code.startswith(("6","9")) else "sz"
    return str(name_lookup.get((market, code), code))

positions = {}
for k, cost in active.items():
    ed2, code = k
    det = active_details[k]
    positions[code] = {
        "name": get_name(code),
        "entries": [{"date": str(ed2.date()), "type": "开仓", "price": round(float(det["price"]),2), "shares": det["shares"], "ndif": round(float(det["ndif"]),2)}],
        "profit_triggered": False, "trigger_date": ""
    }

state = {"config": {"capital": INIT, "lot": LOT}, "cash": round(cash,2), "positions": positions, "history": history}
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

# Save MTM curve
os.makedirs(os.path.dirname(MTM_FILE), exist_ok=True)
with open(MTM_FILE, "w") as f:
    json.dump(mtm_result, f)

# Summary
end_val = mtm_result[-1]["equity"] if mtm_result else INIT
print(f"OK|{len(positions)}|{len(history)}|{acc}|{rej}|{eq:.0f}")
print(f"MTM: {len(mtm_result)} weeks, {mtm_result[0]['equity']:,} -> {end_val:,} ({(end_val/INIT-1)*100:+.2f}%)", file=sys.stderr)
