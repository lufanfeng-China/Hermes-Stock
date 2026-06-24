#!/usr/bin/env python3
"""
RPS首次策略 — 2023年12月回测 (内存优化版)
  逐日处理，避免一次性加载全部RPS历史。
  仅预建 "60日内RPS首次" 检测所需的查重结构。
"""
import sys, json, math
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
TDX = '/home/lufanfeng/tdx_data'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

HOLDING_12M = 250
HOLDING_24M = 500

# ── Trend helpers ──

def safe_div(a, b): return a / b if b else 0.0

def rolling_mean(arr, window):
    r = [None] * len(arr)
    for i in range(len(arr)):
        if i >= window - 1:
            r[i] = sum(arr[i-window+1:i+1]) / window
    return r

def latest_non_null(arr):
    for v in reversed(arr):
        if v is not None: return v
    return None

def classify_trend(closes):
    n = len(closes)
    if n < 60: return "insufficient_data", "", ""
    ma20_arr = rolling_mean(closes, 20)
    ma50_arr = rolling_mean(closes, 50)
    ma120_arr = rolling_mean(closes, 120) if n >= 120 else None
    ma250_arr = rolling_mean(closes, 250) if n >= 250 else None
    ma20 = latest_non_null(ma20_arr)
    ma50 = latest_non_null(ma50_arr)
    ma120 = latest_non_null(ma120_arr) if ma120_arr else None
    ma250 = latest_non_null(ma250_arr) if ma250_arr else None
    if any(v is None for v in (ma20, ma50)): return "insufficient_data", "", ""
    close = closes[-1]
    ma20_5ago = ma20_arr[-6] if len(ma20_arr) >= 6 and ma20_arr[-6] is not None else ma20
    ma50_10ago = ma50_arr[-11] if len(ma50_arr) >= 11 and ma50_arr[-11] is not None else ma50
    ma20_slope = safe_div(ma20 - ma20_5ago, ma20_5ago) if ma20_5ago else 0
    ma50_slope = safe_div(ma50 - ma50_10ago, ma50_10ago) if ma50_10ago else 0
    if (ma250 is not None and ma120 is not None and
        ma20 > ma50 > ma120 > ma250 and close > ma20 and ma20_slope > 0 and ma50_slope > 0):
        return "strong_bullish", "", ""
    if ma120 is not None and ma20 > ma50 > ma120 and close > ma20 and ma20_slope > 0:
        return "bullish", "", ""
    if ma20 > ma50 and close > ma20:
        th = 0.01 if ma20 < 5 else (0.005 if ma20 <= 20 else 0.003)
        if ma20_slope >= th: return "recovering", "", ""
    if (ma250 is not None and ma120 is not None and
        ma20 < ma50 < ma120 < ma250 and close < ma20 and ma20_slope < 0):
        return "strong_bearish", "", ""
    if ma120 is not None and ma20 < ma50 < ma120 and close < ma50:
        return "bearish", "", ""
    return "neutral", "", ""

def classify_short_trend(closes):
    n = len(closes)
    if n < 30: return "insufficient_data", "", ""
    ma10_arr = rolling_mean(closes, 10)
    ma20_arr = rolling_mean(closes, 20)
    ma30_arr = rolling_mean(closes, 30) if n >= 30 else None
    ma60_arr = rolling_mean(closes, 60) if n >= 60 else None
    ma10 = latest_non_null(ma10_arr)
    ma20 = latest_non_null(ma20_arr)
    ma30 = latest_non_null(ma30_arr) if ma30_arr else None
    ma60 = latest_non_null(ma60_arr) if ma60_arr else None
    if any(v is None for v in (ma10, ma20)): return "insufficient_data", "", ""
    close = closes[-1]
    ma10_3ago = ma10_arr[-4] if len(ma10_arr) >= 4 and ma10_arr[-4] is not None else ma10
    ma20_5ago = ma20_arr[-6] if len(ma20_arr) >= 6 and ma20_arr[-6] is not None else ma20
    ma10_slope = safe_div(ma10 - ma10_3ago, ma10_3ago) if ma10_3ago else 0
    ma20_slope = safe_div(ma20 - ma20_5ago, ma20_5ago) if ma20_5ago else 0
    if (ma60 is not None and ma30 is not None and
        ma10 > ma20 > ma30 > ma60 and close > ma10 and ma10_slope > 0 and ma20_slope > 0):
        return "strong_bullish", "", ""
    if ma30 is not None and ma10 > ma20 > ma30 and close > ma10 and ma10_slope > 0:
        return "bullish", "", ""
    if ma10 > ma20 and close > ma10:
        th = 0.01 if ma10 < 5 else (0.005 if ma10 <= 20 else 0.003)
        if ma10_slope >= th: return "recovering", "", ""
    if (ma60 is not None and ma30 is not None and
        ma10 < ma20 < ma30 < ma60 and close < ma10 and ma10_slope < 0):
        return "strong_bearish", "", ""
    if ma30 is not None and ma10 < ma20 < ma30 and close < ma20:
        return "bearish", "", ""
    return "neutral", "", ""


def sim_trade(df, entry_date, entry_price, xdxr_map):
    mask = df.index >= entry_date
    window = df.loc[mask]
    if len(window) < 2:
        return {}, None, None, None
    
    monthly = {}
    ret_12m = ret_24m = None
    current_ep = entry_price
    last_month = None
    prev_close = entry_price
    
    for i_day, (idx, row) in enumerate(window.iterrows()):
        idx_str = str(idx)[:10]
        if idx_str in xdxr_map:
            current_ep *= 1.0 / (1.0 + xdxr_map[idx_str] / 10.0)
        close = row['close']
        month_key = idx_str[:7]
        if month_key != last_month:
            if last_month is not None:
                ret = round((prev_close - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
                monthly[last_month] = ret
            last_month = month_key
        prev_close = close
        if ret_12m is None and i_day >= HOLDING_12M:
            epx = window.iloc[i_day+1]['open'] if i_day+1 < len(window) else close
            ret_12m = round((epx - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
        if ret_24m is None and i_day >= HOLDING_24M:
            epx = window.iloc[i_day+1]['open'] if i_day+1 < len(window) else close
            ret_24m = round((epx - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    
    if last_month is not None:
        ret = round((prev_close - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
        monthly[last_month] = ret
    ret_hold = round((window.iloc[-1]['close'] - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    return monthly, ret_12m, ret_24m, ret_hold


def main():
    rps_path = Path("/tmp/dec2023_rps.json")
    if not rps_path.exists():
        print("No filtered RPS file. Run filter first.", file=sys.stderr)
        return
    
    # ── Step 1: Load JSON and build lightweight index ──
    print("Loading JSON...", file=sys.stderr)
    with open(rps_path) as f:
        data = json.load(f)
    print(f"  {len(data)} entries loaded", file=sys.stderr)
    
    # Build: trading_day -> [entries] (lightweight, just group by day)
    print("Indexing by day...", file=sys.stderr)
    by_day = defaultdict(list)
    for h in data:
        td = str(h.get("trading_day", ""))
        if td:
            by_day[td].append(h)
    
    all_td = sorted(by_day.keys())
    target_month = sys.argv[1] if len(sys.argv) > 1 else '2023-12'
    target_days = [d for d in all_td if d.startswith(target_month)]
    month_label = f"{target_month[:4]}年{int(target_month[5:7])}月"
    print(f"  Trading days: {len(all_td)} total, {len(target_days)} in {month_label}", file=sys.stderr)
    print(f"  Target days: {target_days}", file=sys.stderr)
    
    # Build "RPS>360 ever met" cache for first_in_60d check
    # rps360_ever[(market,code)] = first date RPS total > 360 was observed
    print("Building RPS>360 history...", file=sys.stderr)
    rps360_ever = {}
    for td in all_td:
        for h in by_day.get(td, []):
            r20 = h.get("rps_20")
            r50 = h.get("rps_50")
            r120 = h.get("rps_120")
            r250 = h.get("rps_250")
            if any(v is None for v in (r20, r50, r120, r250)):
                continue
            key = (str(h.get("market","")).strip().lower(), str(h.get("symbol","")).strip())
            if key not in rps360_ever and (r20+r50+r120+r250) > 360:
                rps360_ever[key] = td
    
    print(f"  Stocks ever RPS>360: {len(rps360_ever)}", file=sys.stderr)
    
    # ── Step 2: Generate signals for each Dec 2023 day ──
    print(f"Generating signals for {month_label}...", file=sys.stderr)
    signals = []
    
    for d_idx, td in enumerate(target_days):
        entries = by_day.get(td, [])
        print(f"  {td}: {len(entries)} stocks, scanning...", file=sys.stderr)
        
        seen_today = set()
        for h in entries:
            r20 = h.get("rps_20")
            r50 = h.get("rps_50")
            r120 = h.get("rps_120")
            r250 = h.get("rps_250")
            if any(v is None for v in (r20, r50, r120, r250)):
                continue
            total = r20 + r50 + r120 + r250
            if total <= 360:
                continue
            
            market = str(h.get("market","")).strip().lower()
            code = str(h.get("symbol","")).strip()
            key = (market, code)
            
            # Dedup
            sig_key = (td, code)
            if sig_key in seen_today:
                continue
            seen_today.add(sig_key)
            
            # Check first_in_60d: was RPS>360 seen in prior 60 trading days?
            ever_date = rps360_ever.get(key)
            if ever_date and ever_date < td:
                # Check if it was within last 60 trading days
                ever_idx = all_td.index(ever_date) if ever_date in all_td else -1
                td_idx = d_idx + all_td.index(target_days[0])  # absolute index
                if ever_idx >= 0 and (td_idx - ever_idx) <= 60:
                    continue  # already met within 60 days
            
            # Check yesterday's RPS <= 360 (cross condition)
            if d_idx > 0:
                prev_td = target_days[d_idx - 1]
                prev_entries = {str(e.get("symbol","")).strip(): e for e in by_day.get(prev_td, [])}
                prev = prev_entries.get(code)
                if prev:
                    pr20 = prev.get("rps_20")
                    pr50 = prev.get("rps_50")
                    pr120 = prev.get("rps_120")
                    pr250 = prev.get("rps_250")
                    if all(v is not None for v in (pr20, pr50, pr120, pr250)):
                        yesterday_total = pr20 + pr50 + pr120 + pr250
                    else:
                        yesterday_total = 0  # assume crossed
                else:
                    yesterday_total = 0  # no data = assume crossed
            else:
                yesterday_total = 0  # first day, always crossed
            
            if yesterday_total > 360:
                continue  # not a fresh cross
            
            # ── Trend checks ──
            try:
                df = reader.daily(symbol=code)
            except:
                continue
            if df is None or df.empty:
                continue
            df = df.sort_index()
            closes = df["close"].astype(float).tolist()
            if len(closes) < 60:
                continue
            
            trend, _, _ = classify_trend(closes)
            if trend not in ("bullish", "strong_bullish"):
                continue
            
            short_trend, _, _ = classify_short_trend(closes)
            if short_trend not in ("bullish", "strong_bullish"):
                continue
            
            close_t = closes[-1]
            ma10 = sum(closes[max(0, len(closes)-10):]) / 10
            if abs(close_t - ma10) / ma10 * 100 >= 10:
                continue
            
            recent = closes[max(0, len(closes)-10):]
            if close_t < max(recent) - 1e-9:
                continue
            
            signals.append({
                'code': code,
                'market': market,
                'date': td,
                'rps_total': round(total, 2),
                'trend': trend,
                'short_trend': short_trend,
            })
        
        print(f"    → {len(signals)} signals accumulated", file=sys.stderr)
    
    print(f"\nTotal {month_label} signals: {len(signals)}", file=sys.stderr)
    
    # Free memory
    del data, by_day, rps360_ever
    
    if not signals:
        print("No signals found!", file=sys.stderr)
        return
    
    # ── Step 3: Fetch daily + xdxr ──
    print("Fetching daily data...", file=sys.stderr)
    cache = {}
    unique = set((s['market'], s['code']) for s in signals)
    for i, (m, c) in enumerate(unique):
        if (i+1) % 100 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            df = reader.daily(f"{m}{c}")
            if df is not None and not df.empty: cache[f"{m}{c}"] = df.sort_index()
        except: pass
    print(f"  Cached {len(cache)} stocks", file=sys.stderr)
    
    print("Fetching xdxr...", file=sys.stderr)
    xdxr_cache = {}
    for i, (m, c) in enumerate(unique):
        if (i+1) % 100 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            xd = quotes.xdxr(market=m, symbol=c)
            xm = {}
            if xd is not None and not xd.empty:
                for _, row in xd.iterrows():
                    sz = float(row.get('songzhuangu', 0) or 0)
                    if sz > 0:
                        d = f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"
                        xm[d] = sz
            xdxr_cache[f"{m}{c}"] = xm
        except: xdxr_cache[f"{m}{c}"] = {}
    print(f"  xdxr done", file=sys.stderr)
    
    # ── Step 4: Ex-rights filter ──
    clean = []
    for s in signals:
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None: clean.append(s); continue
        bad = False
        if s['date'] in df.index:
            idx = df.index.get_loc(s['date'])
            if idx > 0:
                pc = df.iloc[idx-1]['close']; to = df.iloc[idx]['open']
                if pc > 0 and to > 0 and (to-pc)/pc < -0.10: bad = True
        if not bad:
            m = df.index >= s['date']; ew = df.loc[m]
            if not ew.empty:
                ed = ew.index[0]
                if ed in df.index:
                    idx = df.index.get_loc(ed)
                    if idx > 0:
                        pc = df.iloc[idx-1]['close']; to = df.iloc[idx]['open']
                        if pc > 0 and to > 0 and (to-pc)/pc < -0.10: bad = True
        if not bad: clean.append(s)
    signals = clean
    print(f"  {len(signals)} clean after ex-rights filter", file=sys.stderr)
    
    # ── Step 5: Simulate ──
    print("Simulating trades...", file=sys.stderr)
    for i, s in enumerate(signals):
        if (i+1) % 50 == 0: print(f"  {i+1}/{len(signals)}...", file=sys.stderr)
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None: continue
        m = df.index >= s['date']; ew = df.loc[m]
        if ew.empty: continue
        ed = ew.index[0]; ep = ew.iloc[0]['open']
        if ep <= 0: continue
        xm = xdxr_cache.get(f"{s['market']}{s['code']}", {})
        monthly, r12, r24, rh = sim_trade(df, ed, ep, xm)
        s['_trade'] = {'ret_12m': r12, 'ret_24m': r24, 'ret_hold': rh, 'monthly': monthly}
    
    # ── Step 6: Output ──
    s365 = [s for s in signals if s['rps_total'] >= 365]
    s370 = [s for s in signals if s['rps_total'] >= 370]
    
    print(f"\nTotal: {len(signals)} | RPS≥365: {len(s365)} | RPS≥370: {len(s370)}", file=sys.stderr)
    
    print(f"\n{'='*100}")
    print(f"  {month_label} RPS首次策略回测")
    print(f"{'='*100}")
    print(f"  RPS≥365: {len(s365)}笔 | RPS≥370: {len(s370)}笔")
    
    # By-date table
    by_d365 = defaultdict(list)
    by_d370 = defaultdict(list)
    for s in s365:
        if s.get('_trade'): by_d365[s['date']].append(s['_trade'])
    for s in s370:
        if s.get('_trade'): by_d370[s['date']].append(s['_trade'])
    
    all_dates = sorted(set(list(by_d365.keys()) + list(by_d370.keys())))
    
    print(f"\n  {'日期':<12} {'365':>4} {'370':>4} | {'365-12月':>9} {'365-24月':>9} {'365-持有':>9} | {'370-12月':>9} {'370-24月':>9} {'370-持有':>9}")
    print(f"  {'─'*95}")
    
    for dt in all_dates:
        t365 = by_d365.get(dt, [])
        t370 = by_d370.get(dt, [])
        def avg(ts, k):
            v = [t.get(k) for t in ts if t.get(k) is not None]
            return sum(v)/len(v) if v else None
        def f(v): return f"{v:+7.1f}%" if v is not None else "    N/A"
        print(f"  {dt:<12} {len(t365):>4} {len(t370):>4} | {f(avg(t365,'ret_12m')):>9} {f(avg(t365,'ret_24m')):>9} {f(avg(t365,'ret_hold')):>9} | {f(avg(t370,'ret_12m')):>9} {f(avg(t370,'ret_24m')):>9} {f(avg(t370,'ret_hold')):>9}")
    
    # Summary
    t365_all = [s['_trade'] for s in s365 if s.get('_trade')]
    t370_all = [s['_trade'] for s in s370 if s.get('_trade')]
    
    def stats(ts, k):
        v = [t[k] for t in ts if t.get(k) is not None]
        if not v: return None, 0
        return (sum(v)/len(v), sum(1 for x in v if x>0)/len(v)*100, sorted(v)[len(v)//2], max(v), min(v), len(v)), len(v)
    
    print(f"\n  【汇总】")
    print(f"  {'指标':<14} {'365-12月':>12} {'365-24月':>12} {'365-持有':>12} {'370-12月':>12} {'370-24月':>12} {'370-持有':>12}")
    print(f"  {'─'*85}")
    
    keys = ['ret_12m', 'ret_24m', 'ret_hold']
    ts_list = [(t365_all, t365_all, t365_all), (t370_all, t370_all, t370_all)]
    labels_365 = [f'{len([1 for t in t365_all if t.get(k) is not None])}笔' for k in keys]
    labels_370 = [f'{len([1 for t in t370_all if t.get(k) is not None])}笔' for k in keys]
    
    for label_idx, label in enumerate(['交易数', '平均收益', '胜率', '中位数', '最大盈利', '最大亏损']):
        row = f"  {label:<14}"
        for group_idx, (ts_group, labels_group) in enumerate([(t365_all, labels_365), (t370_all, labels_370)]):
            ts = ts_group
            for ki, k in enumerate(keys):
                v = [t[k] for t in ts if t.get(k) is not None]
                if not v:
                    row += f" {'N/A':>12}"
                    continue
                if label == '交易数':
                    row += f" {len(v):>11}笔"
                elif label == '平均收益':
                    row += f" {sum(v)/len(v):>+11.1f}%"
                elif label == '胜率':
                    row += f" {sum(1 for x in v if x>0)/len(v)*100:>10.0f}%"
                elif label == '中位数':
                    row += f" {sorted(v)[len(v)//2]:>+11.1f}%"
                elif label == '最大盈利':
                    row += f" {max(v):>+11.1f}%"
                elif label == '最大亏损':
                    row += f" {min(v):>+11.1f}%"
        print(row)
    
    # Monthly path
    print(f"\n  【持有到各月末的收益路径】")
    m365 = defaultdict(list)
    m370 = defaultdict(list)
    for s in s365:
        if s.get('_trade') and s['_trade'].get('monthly'):
            for m, ret in s['_trade']['monthly'].items(): m365[m].append(ret)
    for s in s370:
        if s.get('_trade') and s['_trade'].get('monthly'):
            for m, ret in s['_trade']['monthly'].items(): m370[m].append(ret)
    
    all_months = sorted(set(list(m365.keys()) + list(m370.keys())))
    print(f"  {'月末':<10} {'365均收':>10} {'笔数':>5} | {'370均收':>10} {'笔数':>5}")
    print(f"  {'─'*50}")
    for m in all_months:
        v365 = m365.get(m, [])
        v370 = m370.get(m, [])
        a365 = sum(v365)/len(v365) if v365 else None
        a370 = sum(v370)/len(v370) if v370 else None
        s365_str = f"{a365:>+9.1f}% {len(v365):>4}笔" if a365 is not None else f"{'':>10} {'':>5}"
        s370_str = f"{a370:>+9.1f}% {len(v370):>4}笔" if a370 is not None else f"{'':>10} {'':>5}"
        print(f"  {m:<10} {s365_str} | {s370_str}")


if __name__ == '__main__':
    main()
