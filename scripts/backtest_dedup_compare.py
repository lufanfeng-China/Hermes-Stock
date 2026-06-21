#!/usr/bin/env python3
"""
RPS首次策略 — 永久去重 vs 60日窗口去重对比
Rule A: 同一股票只取首次信号（当前回测口径）
Rule B: 同一股票可在 >60交易日 后再次买入
"""
import sys, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/mnt/c/new_tdx64'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 365
HOLDING_12M = 250
HOLDING_24M = 500

def load_all_signals():
    """Load all signals from strategy files, preserving both passed=True and passed=False"""
    strat_files = sorted(DS.glob('dataset_stock_screener_strategies_*.json'))
    
    # Build trading day index for 60-day offset calculation
    all_td = sorted(set(
        f.stem.replace('dataset_stock_screener_strategies_','')
        for f in strat_files if f.stem.startswith('dataset_stock_screener_strategies_20')
    ))
    
    rule_a = []  # permanent dedup
    rule_b_extra = []  # additional signals for 60-day rule
    seen_perm = set()
    last_signal_day = {}  # code -> trading_day of last signal
    
    for sf in strat_files:
        try:
            rows = json.loads(sf.read_text(encoding='utf-8'))
        except:
            continue
        
        td = sf.stem.replace('dataset_stock_screener_strategies_','')
        if not td.startswith('20'):
            continue
        
        for r in rows:
            if r.get('strategy') != 'rps_first':
                continue
            code = str(r.get('symbol',''))
            rps = r.get('conditions',{}).get('rps_total',0)
            if rps < RPS_MIN:
                continue
            
            market = r.get('market', 'sh' if code.startswith('6') else 'sz')
            entry = {
                'code': code, 'market': market, 'date': td,
                'rps_total': rps,
            }
            
            # Rule A: permanent dedup
            if code not in seen_perm:
                seen_perm.add(code)
                if r.get('passed'):
                    rule_a.append(entry)
            
            # Rule B: 60-day window
            passed = r.get('passed', False)
            prev_day = last_signal_day.get(code)
            if prev_day is None:
                if passed:
                    last_signal_day[code] = td
                    # Already counted in rule_a, but also in rule_b
            else:
                try:
                    pi = all_td.index(prev_day)
                    ci = all_td.index(td)
                    if ci - pi > 60 and passed:
                        # Valid re-entry under Rule B
                        rule_b_extra.append(entry)
                        last_signal_day[code] = td
                except ValueError:
                    pass
    
    # Rule B total = Rule A + extras
    rule_b = rule_a + rule_b_extra
    
    print(f"Rule A (永久去重): {len(rule_a)} signals", file=sys.stderr)
    print(f"Rule B extra (二次买入): {len(rule_b_extra)} signals", file=sys.stderr)
    print(f"Rule B total: {len(rule_b)} signals", file=sys.stderr)
    
    return rule_a, rule_b_extra, rule_b, all_td


def fetch_data(signals):
    """Fetch daily data and xdxr"""
    unique = set((s['market'], s['code']) for s in signals)
    
    print(f"Fetching daily data for {len(unique)} stocks...", file=sys.stderr)
    cache = {}
    for i, (m, c) in enumerate(unique):
        if (i+1) % 200 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            df = reader.daily(f"{m}{c}")
            if df is not None and not df.empty: cache[f"{m}{c}"] = df.sort_index()
        except: pass
    print(f"  Cached {len(cache)}", file=sys.stderr)
    
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
    print(f"  xdxr done", file=sys.stderr)
    return cache, xdxr_cache


def filter_ex_rights(signals, cache):
    clean = []
    ex = 0
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
    print(f"  Excluded {len(signals)-len(clean)} ex-rights", file=sys.stderr)
    return clean


def sim_trade(df, entry_date, entry_price, xdxr_map):
    mask = df.index >= entry_date
    window = df.loc[mask]
    if len(window) < 2: return {}, None, None, None
    
    monthly = {}; ret_12m = ret_24m = None
    current_ep = entry_price; last_month = None; prev_close = entry_price
    
    for i_day, (idx, row) in enumerate(window.iterrows()):
        idx_str = str(idx)[:10]
        if idx_str in xdxr_map:
            current_ep *= 1.0 / (1.0 + xdxr_map[idx_str] / 10.0)
        close = row['close']; month_key = idx_str[:7]
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


def run_simulation(signals, cache, xdxr_cache, label):
    print(f"Simulating {label} ({len(signals)} trades)...", file=sys.stderr)
    for i, s in enumerate(signals):
        if (i+1) % 200 == 0: print(f"  {i+1}/{len(signals)}...", file=sys.stderr)
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None: continue
        m = df.index >= s['date']; ew = df.loc[m]
        if ew.empty: continue
        ed = ew.index[0]; ep = ew.iloc[0]['open']
        if ep <= 0: continue
        xm = xdxr_cache.get(f"{s['market']}{s['code']}", {})
        monthly, r12, r24, rh = sim_trade(df, ed, ep, xm)
        s['_trade'] = {'ret_12m': r12, 'ret_24m': r24, 'ret_hold': rh, 'monthly': monthly}
    return [s for s in signals if s.get('_trade')]


def stats(signals, key):
    vals = [s['_trade'][key] for s in signals if s['_trade'].get(key) is not None]
    if not vals: return None
    return {
        'n': len(vals), 'avg': sum(vals)/len(vals),
        'wr': sum(1 for v in vals if v>0)/len(vals)*100,
        'med': sorted(vals)[len(vals)//2],
        'max': max(vals), 'min': min(vals),
    }


def print_comparison(rule_a, rule_b, rule_b_extra, label_a, label_b):
    for horizon, key in [('12月退出', 'ret_12m'), ('24月退出', 'ret_24m'), ('一直持有', 'ret_hold')]:
        sa = stats(rule_a, key)
        sb = stats(rule_b, key)
        sextra = stats(rule_b_extra, key) if rule_b_extra else None
        
        print(f"\n  【{horizon}】")
        hdr = f"  {'指标':<16} {'Rule A':>14} {'Rule B':>14} {'差异':>10}"
        if sextra and sextra['n'] > 0:
            hdr += f" {'二次买入':>14}"
        print(hdr)
        print(f"  {'─'*70}")
        
        if sa is None and sb is None:
            print(f"  {'(无已完成交易)':^60}")
            continue
        
        for metric in ['n', 'avg', 'wr', 'med']:
            va = sa[metric] if sa else None
            vb = sb[metric] if sb else None
            
            labels = {'n': '交易数', 'avg': '平均收益', 'wr': '胜率', 'med': '中位数'}
            row = f"  {labels[metric]:<16}"
            
            if metric == 'n':
                row += f" {va:>13}笔" if va else f" {'N/A':>14}"
                row += f" {vb:>13}笔" if vb else f" {'N/A':>14}"
                if va and vb:
                    diff = vb - va
                    row += f" {diff:>+9}笔"
                else:
                    row += f" {'':>10}"
            elif metric == 'avg':
                row += f" {va:>+13.1f}%" if va is not None else f" {'N/A':>14}"
                row += f" {vb:>+13.1f}%" if vb is not None else f" {'N/A':>14}"
                if va is not None and vb is not None:
                    row += f" {vb-va:>+9.1f}pp"
                else:
                    row += f" {'':>10}"
            elif metric == 'wr':
                row += f" {va:>13.0f}%" if va is not None else f" {'N/A':>14}"
                row += f" {vb:>13.0f}%" if vb is not None else f" {'N/A':>14}"
                if va is not None and vb is not None:
                    row += f" {vb-va:>+9.0f}pp"
                else:
                    row += f" {'':>10}"
            elif metric == 'med':
                row += f" {va:>+13.1f}%" if va is not None else f" {'N/A':>14}"
                row += f" {vb:>+13.1f}%" if vb is not None else f" {'N/A':>14}"
            
            if sextra and sextra['n'] > 0:
                if metric == 'n':
                    row += f" {sextra['n']:>13}笔"
                elif metric == 'avg':
                    row += f" {sextra['avg']:>+13.1f}%"
                elif metric == 'wr':
                    row += f" {sextra['wr']:>13.0f}%"
                elif metric == 'med':
                    row += f" {sextra['med']:>+13.1f}%"
            print(row)


def main():
    print("=" * 70)
    print("  RPS首次策略 — 永久去重 vs 60日窗口去重")
    print("=" * 70)
    
    # Step 1: Load signals
    rule_a, rule_b_extra, rule_b, all_td = load_all_signals()
    
    if not rule_a:
        print("No signals found!", file=sys.stderr)
        return
    
    # Step 2: Fetch data (all unique stocks from both sets)
    all_signals = rule_b  # Rule B is superset
    cache, xdxr_cache = fetch_data(all_signals)
    
    # Step 3: Filter ex-rights
    rule_a = filter_ex_rights(rule_a, cache)
    rule_b_extra = filter_ex_rights(rule_b_extra, cache)
    rule_b = rule_a + rule_b_extra  # rebuild after filtering
    
    # Step 4: Simulate
    rule_a = run_simulation(rule_a, cache, xdxr_cache, "Rule A")
    rule_b = run_simulation(rule_b, cache, xdxr_cache, "Rule B")
    # Re-derive extras from simulated sets
    a_codes = set((s['code'], s['date']) for s in rule_a)
    rule_b_extra_sim = [s for s in rule_b if (s['code'], s['date']) not in a_codes]
    
    print(f"\n  Simulated: Rule A={len(rule_a)}, Rule B={len(rule_b)}, Extra={len(rule_b_extra_sim)}", file=sys.stderr)
    
    # Step 5: Compare
    print("\n" + "=" * 70)
    print("  对比结果")
    print("=" * 70)
    
    print_comparison(rule_a, rule_b, rule_b_extra_sim, "Rule A (永久去重)", "Rule B (60日窗口)")
    
    # Monthly summary difference
    print(f"\n  【月度信号分布对比】")
    print(f"  {'月份':<10} {'Rule A':>8} {'Rule B':>8} {'新增':>6}")
    print(f"  {'─'*36}")
    
    ma = defaultdict(int)
    mb = defaultdict(int)
    for s in rule_a: ma[s['date'][:7]] += 1
    for s in rule_b: mb[s['date'][:7]] += 1
    
    all_months = sorted(set(list(ma.keys()) + list(mb.keys())))
    for m in all_months:
        ca = ma.get(m, 0)
        cb = mb.get(m, 0)
        print(f"  {m:<10} {ca:>8} {cb:>8} {cb-ca:>+5}")
    
    # Annual summary
    print(f"\n  【年度汇总对比】")
    print(f"  {'年度':<8} {'Rule A':>8} {'Rule B':>8} | {'A-12月':>9} {'B-12月':>9} | {'A-24月':>9} {'B-24月':>9}")
    print(f"  {'─'*65}")
    
    for year in ['2023', '2024', '2025', '2026']:
        ta = [s for s in rule_a if s['date'].startswith(year)]
        tb = [s for s in rule_b if s['date'].startswith(year)]
        
        sa12 = stats(ta, 'ret_12m')
        sb12 = stats(tb, 'ret_12m')
        sa24 = stats(ta, 'ret_24m')
        sb24 = stats(tb, 'ret_24m')
        
        a12 = f"{sa12['avg']:>+8.1f}%" if sa12 else "     N/A"
        b12 = f"{sb12['avg']:>+8.1f}%" if sb12 else "     N/A"
        a24 = f"{sa24['avg']:>+8.1f}%" if sa24 else "     N/A"
        b24 = f"{sb24['avg']:>+8.1f}%" if sb24 else "     N/A"
        
        print(f"  {year:<8} {len(ta):>8} {len(tb):>8} | {a12:>9} {b12:>9} | {a24:>9} {b24:>9}")


if __name__ == '__main__':
    main()
