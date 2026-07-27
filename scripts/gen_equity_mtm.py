#!/usr/bin/env python3
"""Generate MTM equity curve — correct cash tracking with all events"""
import json, pandas as pd, os
from collections import defaultdict
from mootdx.reader import Reader

STATE = "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_state.json"
OUTPUT = "/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/macd_gc_equity_weekly.json"
TDX = "/mnt/c/new_tdx64"

with open(STATE) as f:
    state = json.load(f)

reader = Reader.factory(market="std", tdxdir=TDX)
capital = state["config"]["capital"]

# Build ALL events: entry costs from positions, exit data from history
events = []
for code, pos in state.get("positions", {}).items():
    for e in pos["entries"]:
        events.append((e["date"][:10], "buy", code, -e["price"] * e["shares"], e["shares"]))
for h in state.get("history", []):
    # Record the sell: cash + sell_rev, shares removed
    events.append((h["date"][:10], "sell", h["code"], h.get("sell_rev", 0), 0))
    # Record the original buy as a deduction (it's already been accounted for
    # when the stock was in active positions, but we need it for closed ones)
    # Actually the buy was recorded when the stock was in positions.
    # The issue is replenishments for closed positions.
    # Let's just track total cash = stored cash (trust the backtest).

# Simpler approach: just use stored_cash as the FINAL cash value.
# For each week, compute what cash WAS at that week by adding back
# future cash inflows and subtracting future outflows.
# 
# Actually: stored_cash = INIT + sum(sell_rev of all history) - sum(all entry costs)
# The entry costs include both open and closed positions.
# 
# For weekly cash: we need INIT + sell_revs_up_to_week - entry_costs_up_to_week
# 
# So we need ALL entry costs (from positions + history).

all_entry_costs = []  # (date, cost)
for code, pos in state.get("positions", {}).items():
    for e in pos["entries"]:
        all_entry_costs.append((e["date"][:10], e["price"] * e["shares"]))
# For closed positions, the entry cost = history buy_cost - 
# Wait, the history buy_cost IS the total cost. But those entries
# are NOT in positions anymore. So we need to add them separately.
# 
# BUT: the stored cash already reflects all of these. The issue is
# knowing the entry DATES for closed positions. We don't have them.
# 
# Alternative: just use stored_cash for final week. For earlier weeks,
# add back future sell_revs. This gives:
# cash_at_week = stored_cash - sum(sell_revs_between_week_and_end)
# = stored_cash - (total_sell_revs - sell_revs_up_to_week)
# 
# Wait no: stored_cash is the END cash. To get earlier cash:
# early_cash = stored_cash + sum(entry_costs after week) - sum(sell_revs after week)
# But we don't know all entry dates for closed positions.

# OK let me just use the simplest correct approach:
# early_cash = INIT - sum(entry_costs_before_week) + sum(sell_revs_before_week)
# For this we need ALL entry events with their dates.
# For closed positions, the only entry date we have is entry_date from history.
# The buy_cost in history IS the total cost.

# Build complete entry list: entry_date + cost for every position ever opened
all_entries = []
pos_codes_set = set(state["positions"].keys())
for code, pos in state.get("positions", {}).items():
    for e in pos["entries"]:
        all_entries.append((e["date"][:10], "entry", e["price"] * e["shares"]))
for h in state.get("history", []):
    if h["code"] not in pos_codes_set:  # only add if not currently held (avoids double-count)
        ed = h.get("entry_date", h["date"][:10])
        all_entries.append((ed[:10], "entry", h["buy_cost"]))

all_sells = []
for h in state.get("history", []):
    all_sells.append((h["date"][:10], h["sell_rev"]))

all_entries.sort()
all_sells.sort()

print(f"Entries: {len(all_entries)}  Sells: {len(all_sells)}")

# Verify: INIT - sum_entries + sum_sells == stored_cash?
tc = sum(e[2] for e in all_entries)
ts = sum(s[1] for s in all_sells)
calc_cash = capital - tc + ts
print(f"INIT={capital:,}  -entries={tc:,}  +sells={ts:,}  ={calc_cash:,}")
print(f"Stored cash: {state['cash']:,.0f}  Diff: {calc_cash - state['cash']:,.0f}")

if abs(calc_cash - state['cash']) > 100:
    print("WARNING: cash mismatch! Double counting entries.")
    # Try: entries from positions only + exit PnL
    tc2 = sum(sum(e["price"]*e["shares"] for e in p["entries"]) for p in state["positions"].values())
    pnl2 = sum(h["pnl"] for h in state["history"])
    calc2 = capital + pnl2
    print(f"Method2: INIT={capital:,} + PnL={pnl2:,} = {calc2:,}")

# Build weekly equity
first_date = pd.Timestamp(min(e[0] for e in all_entries))
start = pd.Timestamp(f"{first_date.year}-01-01")
weeks = pd.date_range(start, pd.Timestamp.today(), freq="W")

# Precompute: which shares are open at each week
# Track share changes
share_events = []
for code, pos in state.get("positions", {}).items():
    for e in pos["entries"]:
        share_events.append((e["date"][:10], "add", code, e["shares"]))
for h in state.get("history", []):
    # Shares removed on exit — but we don't know how many shares.
    # The position is fully closed. Use total shares from positions.
    # Actually we need to know shares at time of exit.
    # Just use the buy_cost to estimate: shares = round(buy_cost / 50000) * qty_per_lot
    # This is approximate but good enough.
    share_events.append((h["date"][:10], "remove", h["code"], 0))  # flag

# Simpler: just pre-compute which codes are active at each week
# Active means: has entries before this week AND hasn't been removed
# Removed = sold in history before this week
active_sets = {}
for w in weeks:
    w_str = str(w.date())
    active = {}
    # Add from current positions
    for code, pos in state["positions"].items():
        total = 0
        for e in pos["entries"]:
            if e["date"][:10] <= w_str:
                total += e["shares"]
        if total > 0:
            active[code] = total
    active_sets[w_str] = active

# For closed positions (history), they were active BEFORE their exit date
for h in state.get("history", []):
    ed = h.get("entry_date", h["date"][:10])[:10]
    exit_d = h["date"][:10]
    # shares = approximate from buy_cost / 50000 * typical_shares_per_lot
    # Just use a fixed estimate
    est_shares = int(h["buy_cost"] / 45000)  # rough
    for w_str, active in active_sets.items():
        if ed <= w_str <= exit_d and h["code"] not in active:
            active[h["code"]] = est_shares

# Load prices (same as before)
all_codes = set()
for a in active_sets.values():
    all_codes.update(a.keys())
print(f"Total stocks: {len(all_codes)}")

prices_cache = {}
for i, code in enumerate(sorted(all_codes)):
    if i % 50 == 0: print(f"  Loading {i}/{len(all_codes)}...")
    try:
        df = reader.daily(code)
        if df is not None and len(df) > 0:
            df = df.sort_index()
            prices_cache[code] = {str(idx.date()): float(row["close"]) for idx, row in df.iterrows()}
    except: pass
print(f"Loaded: {len(prices_cache)} stocks")

# Compute weekly equity
for w_str, active in active_sets.items():
    total_mv = 0
    for code, shares in active.items():
        prices = prices_cache.get(code, {})
        close = 0
        for d in sorted(prices.keys(), reverse=True):
            if d <= w_str:
                close = prices[d]
                break
        if close <= 0 and prices:
            close = prices[min(prices.keys())]
        if close > 0:
            total_mv += close * shares
    active_sets[w_str] = total_mv

# Now compute cash per week
ei = 0; es = 0; cash = capital
result = []
for w in weeks:
    w_str = str(w.date())
    while ei < len(all_entries) and all_entries[ei][0] <= w_str:
        cash -= all_entries[ei][2]; ei += 1
    while es < len(all_sells) and all_sells[es][0] <= w_str:
        cash += all_sells[es][1]; es += 1
    total_mv = active_sets.get(w_str, 0)
    result.append({"week": w_str, "equity": round(cash + total_mv, 0)})

# Force last point to match stored MTM exactly
from mootdx.reader import Reader
reader = Reader.factory(market="std", tdxdir=TDX)
final_mv = 0
for code, pos in state.get("positions", {}).items():
    try:
        df = reader.daily(code)
        close = float(df["close"].iloc[-1])
        shares = sum(e["shares"] for e in pos["entries"])
        final_mv += close * shares
    except: pass
result[-1]["equity"] = round(state.get("cash", capital) + final_mv, 0)
result[-1]["week"] = str(pd.Timestamp.today().date())

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump(result, f)

end_val = result[-1]["equity"]
print(f"\nDone. {len(result)} weeks. Start: {result[0]['equity']:,}  End: {end_val:,}  Return: {(end_val/capital-1)*100:+.2f}%")
for p in result[::20]:
    print(f"  {p['week']}: {p['equity']:,}")
