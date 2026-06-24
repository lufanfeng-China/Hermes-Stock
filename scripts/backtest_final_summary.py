#!/usr/bin/env python3
"""
RPS首次策略 最终回测结论 — 60日窗口, RPS≥360
输出: 每月信号数 + 24月退出 + 一直持有
"""
import sys, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/home/lufanfeng/tdx_data'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING_24M = 500

# ── Load signals with 60-day window dedup ──
def load_signals():
    strat_files = sorted(DS.glob('dataset_stock_screener_strategies_*.json'))
    
    all_td = sorted(set(
        f.stem.replace('dataset_stock_screener_strategies_','')
        for f in strat_files if f.stem.startswith('dataset_stock_screener_strategies_20')
    ))
    
    signals = []
    last_signal_day = {}
    
    for sf in strat_files:
        try: rows = json.loads(sf.read_text(encoding='utf-8'))
        except: continue
        td = sf.stem.replace('dataset_stock_screener_strategies_','')
        if not td.startswith('20'): continue
        
        for r in rows:
            if r.get('strategy') != 'rps_first': continue
            if not r.get('passed'): continue
            code = str(r.get('symbol',''))
            rps = r.get('conditions',{}).get('rps_total',0)
            if rps < RPS_MIN: continue
            
            market = r.get('market', 'sh' if code.startswith('6') else 'sz')
            prev = last_signal_day.get(code)
            if prev is not None:
                try:
                    pi = all_td.index(prev)
                    ci = all_td.index(td)
                    if ci - pi <= 60: continue
                except ValueError: pass
            
            last_signal_day[code] = td
            signals.append({'code': code, 'market': market, 'date': td, 'rps_total': rps})
    
    return signals


# ── Fetch data ──
def fetch_data(signals):
    unique = set((s['market'], s['code']) for s in signals)
    print(f"Fetching daily data for {len(unique)} stocks...", file=sys.stderr)
    cache = {}
    for i, (m, c) in enumerate(unique):
        if (i+1) % 200 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            df = reader.daily(f"{m}{c}")
            if df is not None and not df.empty: cache[f"{m}{c}"] = df.sort_index()
        except: pass
    
    print("Fetching xdxr...", file=sys.stderr)
    xdxr_cache = {}
    for i, (m, c) in enumerate(unique):
        if (i+1) % 200 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
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
    return cache, xdxr_cache


# ── Ex-rights filter ──
def filter_signals(signals, cache):
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
    return clean


# ── Simulate ──
def sim_trade(df, entry_date, entry_price, xdxr_map):
    mask = df.index >= entry_date
    window = df.loc[mask]
    if len(window) < 2: return None, None
    
    ret_24m = None
    current_ep = entry_price
    
    for i_day, (idx, row) in enumerate(window.iterrows()):
        idx_str = str(idx)[:10]
        if idx_str in xdxr_map:
            current_ep *= 1.0 / (1.0 + xdxr_map[idx_str] / 10.0)
        
        if ret_24m is None and i_day >= HOLDING_24M:
            close = row['close']
            epx = window.iloc[i_day+1]['open'] if i_day+1 < len(window) else close
            ret_24m = round((epx - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    
    ret_hold = round((window.iloc[-1]['close'] - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    return ret_24m, ret_hold


def main():
    # ── 2023 data (from pre-computed RPS history backtests) ──
    y2023 = {
        '2023-03': (1,  1, +49.5, +739.4),
        '2023-05': (1,  1,  -8.5,  +40.7),
        '2023-06': (1,  1,  +0.5, +156.4),
        '2023-07': (2,  2, +129.4, +531.1),  # 2笔的均收
        '2023-08': (2,  2,  +89.5, +492.6),
        '2023-09': (1,  1,  -17.6,  +37.0),
        '2023-11': (1,  1,  +14.5,  +55.9),
        '2023-12': (3,  3, +167.1, +270.2),
    }
    # months with 0 signals: Jan, Feb, Apr, Oct
    
    # ── 2024-2026 data (compute from strategy files) ──
    print("Loading 2024-2026 signals (60日窗口)...", file=sys.stderr)
    signals = load_signals()
    print(f"  {len(signals)} signals", file=sys.stderr)
    
    cache, xdxr_cache = fetch_data(signals)
    signals = filter_signals(signals, cache)
    print(f"  {len(signals)} after ex-rights filter", file=sys.stderr)
    
    print("Simulating...", file=sys.stderr)
    for i, s in enumerate(signals):
        if (i+1) % 200 == 0: print(f"  {i+1}/{len(signals)}...", file=sys.stderr)
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None: continue
        m = df.index >= s['date']; ew = df.loc[m]
        if ew.empty: continue
        ed = ew.index[0]; ep = ew.iloc[0]['open']
        if ep <= 0: continue
        xm = xdxr_cache.get(f"{s['market']}{s['code']}", {})
        r24, rh = sim_trade(df, ed, ep, xm)
        s['_r24'] = r24; s['_rh'] = rh
    
    # ── Build monthly table ──
    by_month = defaultdict(list)
    for s in signals:
        by_month[s['date'][:7]].append(s)
    
    all_months = sorted(list(by_month.keys()))
    
    # Merge 2023 data
    for m in y2023:
        # y2023[m] = (total_signals, on_parade, avg_24m, avg_hold)
        pass
    
    # Print merged table
    print()
    print("=" * 95)
    print("  RPS首次策略 最终回测结论")
    print("  规则: RPS≥360 | 60日窗口去重 | T+1开盘买入 | 无止损")
    print("=" * 95)
    
    # Sort all months from 2023 to 2026
    year_months = []
    for y in range(2023, 2027):
        for m in range(1, 13):
            ym = f"{y}-{m:02d}"
            if ym in y2023 or ym in by_month:
                year_months.append(ym)
    
    print()
    print(f"  {'月份':<10} {'信号数':>6} | {'24月退出':>12} {'一直持有':>12}")
    print(f"  {'─'*48}")
    
    all_24m = []
    all_hold = []
    total_signals = 0
    
    for ym in year_months:
        if ym in y2023:
            total_s, complete_s, avg24, avgh = y2023[ym]
            s24_str = f"{avg24:>+8.1f}%" if avg24 is not None else "     N/A"
            sh_str = f"{avgh:>+8.1f}%" if avgh is not None else "     N/A"
            print(f"  {ym:<10} {total_s:>6} | {s24_str}      {sh_str}")
            # Add to aggregates (treat each signal individually for avg)
            all_24m.extend([avg24] * complete_s)
            all_hold.extend([avgh] * complete_s)
            total_signals += total_s
        elif ym in by_month:
            trades = by_month[ym]
            n = len(trades)
            r24s = [t['_r24'] for t in trades if t.get('_r24') is not None]
            rhs = [t['_rh'] for t in trades if t.get('_rh') is not None]
            a24 = sum(r24s)/len(r24s) if r24s else None
            ah = sum(rhs)/len(rhs) if rhs else None
            s24_str = f"{a24:>+8.1f}%" if a24 is not None else "     N/A"
            sh_str = f"{ah:>+8.1f}%" if ah is not None else "     N/A"
            print(f"  {ym:<10} {n:>6} | {s24_str}      {sh_str}")
            all_24m.extend(r24s)
            all_hold.extend(rhs)
            total_signals += n
    
    # Annual summary
    print(f"\n  {'─'*48}")
    print(f"  【年度汇总】")
    print(f"  {'年度':<10} {'信号数':>6} | {'24月退出':>12} {'一直持有':>12}")
    print(f"  {'─'*48}")
    
    for year in ['2023', '2024', '2025', '2026']:
        y_total = 0
        y_24m = []
        y_hold = []
        
        for ym in year_months:
            if not ym.startswith(year): continue
            if ym in y2023:
                ts, cs, a24, ah = y2023[ym]
                y_total += ts
                y_24m.extend([a24] * cs)
                y_hold.extend([ah] * cs)
            elif ym in by_month:
                trades = by_month[ym]
                y_total += len(trades)
                y_24m.extend([t['_r24'] for t in trades if t.get('_r24') is not None])
                y_hold.extend([t['_rh'] for t in trades if t.get('_rh') is not None])
        
        a24 = f"{sum(y_24m)/len(y_24m):>+8.1f}%" if y_24m else "     N/A"
        ah = f"{sum(y_hold)/len(y_hold):>+8.1f}%" if y_hold else "     N/A"
        print(f"  {year:<10} {y_total:>6} | {a24}      {ah}")
    
    # Grand total
    a24 = f"{sum(all_24m)/len(all_24m):>+8.1f}%" if all_24m else "N/A"
    ah = f"{sum(all_hold)/len(all_hold):>+8.1f}%" if all_hold else "N/A"
    wr24 = f"{sum(1 for v in all_24m if v>0)/len(all_24m)*100:.0f}%" if all_24m else "N/A"
    wrh = f"{sum(1 for v in all_hold if v>0)/len(all_hold)*100:.0f}%" if all_hold else "N/A"
    
    print(f"  {'─'*48}")
    print(f"  {'合计':<10} {total_signals:>6} | {a24}      {ah}")
    print(f"  {'24月胜率':<10} {'':>6} | {wr24:>12}")
    print(f"  {'持有胜率':<10} {'':>6} | {'':>12} {wrh:>12}")
    
    # Summary stats
    print(f"\n  【核心统计】(2023-01 ~ 2026-06, RPS≥360, 60日窗口)")
    print(f"  {'─'*60}")
    print(f"  总信号数:           {total_signals} 笔")
    print(f"  月均信号:           {total_signals/42:.1f} 笔 ({len(year_months)}个有信号月/42个月)")
    print(f"  24月退出均收:       {a24}")
    print(f"  24月退出胜率:       {wr24}")
    print(f"  一直持有均收:       {ah}")
    print(f"  一直持有胜率:       {wrh}")
    
    # Zero-signal months
    zero_months = []
    for y in range(2023, 2027):
        for m in range(1, 13):
            if m == 7 and y == 2026: break  # only through June 2026
            ym = f"{y}-{m:02d}"
            if ym not in y2023 and ym not in by_month:
                zero_months.append(ym)
    
    print(f"\n  零信号月份:         {len(zero_months)}个月")
    print(f"                    {', '.join(zero_months) if zero_months else '无'}")


if __name__ == '__main__':
    main()
