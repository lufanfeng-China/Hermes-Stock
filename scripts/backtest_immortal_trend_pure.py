#!/usr/bin/env python3
"""
神仙趋势策略 — 四年全景 (纯EMA金叉)
规则: EMA6上穿EMA-DEMA18 | 出场: 死叉次日开盘
"""
import sys, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/mnt/c/new_tdx64'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

daily = {}
def load_daily(code):
    if code in daily: return daily[code]
    try:
        df = reader.daily(symbol=code)
        if df is not None and not df.empty:
            daily[code] = df.sort_index()
            return daily[code]
    except: pass
    return None

def get_idx(df, td):
    if td in df.index: return df.index.get_loc(td)
    m = df.index <= td
    if m.sum() == 0: return None
    return df.index.get_loc(df.index[m][-1])

def check_signal(df, idx):
    if idx < 20: return False
    closes = df['close'].astype(float).iloc[:idx+1]
    h1 = closes.ewm(span=6, adjust=False).mean()
    h2 = h1.ewm(span=18, adjust=False).mean()
    return bool(h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2])

def sim_exit(df, entry_date, entry_price):
    mask = df.index >= entry_date
    w = df.loc[mask]
    if len(w) < 3: return None
    cl = w['close'].astype(float)
    h1 = cl.ewm(span=6, adjust=False).mean()
    h2 = h1.ewm(span=18, adjust=False).mean()
    for i in range(2, len(w)):
        if h2.iloc[i] > h1.iloc[i] and h2.iloc[i-1] <= h1.iloc[i-1]:
            ei = i+1 if i+1 < len(w) else i
            ep = float(w.iloc[ei]['open'])
            ed = str(w.index[ei])[:10]
            ret = round((ep-entry_price)/entry_price*100,2)
            return {'exit_date':ed,'exit_price':round(ep,2),'exit_reason':'death_cross','return':ret,'holding_days':i}
    ep = float(w.iloc[-1]['close']); ed = str(w.index[-1])[:10]
    ret = round((ep-entry_price)/entry_price*100,2)
    return {'exit_date':ed,'exit_price':round(ep,2),'exit_reason':'still_holding','return':ret,'holding_days':len(w)-1}

all_results = {}

for year in ['2023','2024','2025','2026']:
    print(f"=== {year} ===", file=sys.stderr)
    results = []
    
    if year == '2023':
        # From RPS history — get all stock codes
        rps_path = Path("/tmp/dec2023_rps.json")
        with open(rps_path) as f: rps_data = json.load(f)
        all_codes = sorted(set(str(h.get('symbol','')) for h in rps_data if h.get('symbol')))
        days = sorted(set(str(h.get('trading_day','')) for h in rps_data if str(h.get('trading_day','')).startswith('2023')))
    else:
        # From current strategy file (has all stocks)
        cur = json.loads((DS / 'dataset_stock_screener_strategies_current.json').read_text(encoding='utf-8'))
        all_codes = sorted(set(str(r.get('symbol','')) for r in cur if r.get('symbol')))
        strat_files = sorted(DS.glob(f'dataset_stock_screener_strategies_{year}-*.json'))
        days = sorted(set(f.stem.replace('dataset_stock_screener_strategies_','') for f in strat_files))
    
    print(f"  {len(all_codes)} stocks, {len(days)} days", file=sys.stderr)
    
    # Preload
    for i, c in enumerate(all_codes):
        if (i+1) % 500 == 0: print(f"  load {i+1}/{len(all_codes)}...", file=sys.stderr)
        load_daily(c)
    
    # Scan
    for td in days:
        for c in all_codes:
            df = daily.get(c)
            if df is None: continue
            idx = get_idx(df, td)
            if idx is None: continue
            if not check_signal(df, idx): continue
            ni = idx+1
            if ni >= len(df): continue
            ep = float(df.iloc[ni]['open'])
            if ep <= 0: continue
            entry_date = str(df.index[ni])[:10]
            r = sim_exit(df, entry_date, ep)
            if r:
                results.append({'code':c,'date':td,'entry_price':ep,**r})
    
    all_results[year] = results
    print(f"  -> {len(results)} trades", file=sys.stderr)

# ── Output ──
print()
print("=" * 105)
print("  神仙趋势策略 — 2023-2026 四年全景 (纯EMA金叉)")
print("  入场: EMA6上穿EMA-DEMA18 | 出场: 死叉次日开盘")
print("=" * 105)

grand_all = []
for year in ['2023','2024','2025','2026']:
    results = all_results[year]
    by_month = defaultdict(list)
    for r in results: by_month[r['date'][:7]].append(r)
    
    print(f"\n  {'─'*103}")
    print(f"  {year}年")
    
    y_rets = []
    for m in sorted(by_month.keys()):
        mr = by_month[m]
        rets = [r['return'] for r in mr]
        n = len(rets); avg = sum(rets)/n; wr = sum(1 for r in rets if r>0)/n*100
        dc = sum(1 for r in mr if r['exit_reason']=='death_cross')
        print(f"  {m} | {n:>5}笔 | 均{avg:>+7.1f}% | 胜{wr:>3.0f}% | 中{sorted(rets)[n//2]:>+7.1f}% | 💀{dc}")
        y_rets.extend(rets)
    
    if y_rets:
        gn = len(y_rets)
        print(f"  {'─'*103}")
        print(f"  {year}全年: {gn}笔 | 均{sum(y_rets)/gn:+.1f}% | 胜{sum(1 for r in y_rets if r>0)/gn*100:.0f}% | 中{sorted(y_rets)[gn//2]:+.1f}%")
        grand_all.extend(y_rets)
    else:
        print(f"  {year}全年: 0笔")

print(f"\n  {'='*103}")
ga = grand_all
if ga:
    print(f"  四年合计: {len(ga)}笔 | 均{sum(ga)/len(ga):+.1f}% | 胜{sum(1 for r in ga if r>0)/len(ga)*100:.0f}% | 中{sorted(ga)[len(ga)//2]:+.1f}%")
    print(f"  最大: {max(ga):+.1f}% | 最小: {min(ga):+.1f}%")
