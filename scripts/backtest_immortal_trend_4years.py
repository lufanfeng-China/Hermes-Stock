#!/usr/bin/env python3
"""
神仙趋势策略 — 四年全景回测 (2023-2026)
规则: RPS>360 + EMA金叉 + C>EMA108 + MA30斜率>0 + 上证>MA200
出场: 死叉次日开盘
"""
import sys, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/home/lufanfeng/tdx_data'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

# ── Shanghai Composite MA200 ──
print("Loading Shanghai Composite MA200...", file=sys.stderr)
sh_ok = set()
try:
    sh = reader.daily(symbol='sh000001')
    if sh is not None and not sh.empty:
        sh = sh.sort_index()
        c = sh['close'].astype(float)
        ma = c.rolling(200).mean()
        for i in range(200, len(c)):
            if c.iloc[i] > ma.iloc[i]:
                sh_ok.add(str(sh.index[i])[:10])
    print(f"  Above MA200: {len(sh_ok)} days", file=sys.stderr)
except Exception as e:
    print(f"  Failed: {e}", file=sys.stderr)

# ── Universal daily data cache ──
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
    if idx < 140: return False
    closes = df['close'].astype(float).iloc[:idx+1]
    h1 = closes.ewm(span=6, adjust=False).mean()
    h2 = h1.ewm(span=18, adjust=False).mean()
    h3 = closes.ewm(span=108, adjust=False).mean()
    ma30 = closes.rolling(30).mean()
    if not (h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2]): return False
    if not (closes.iloc[-1] > h3.iloc[-1]): return False
    if len(ma30.dropna()) < 6: return False
    if not (ma30.iloc[-1] > ma30.iloc[-6]): return False
    return True

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

# ── Year 2023: from RPS history ──
print("\n=== 2023 ===", file=sys.stderr)
rps_path = Path("/tmp/dec2023_rps.json")
with open(rps_path) as f: rps_data = json.load(f)

rps_by_day = defaultdict(set)
for h in rps_data:
    td = str(h.get('trading_day',''))
    if not td.startswith('2023'): continue
    c = str(h.get('symbol',''))
    if not c: continue
    try:
        if float(h.get('rps_20',0)or 0)+float(h.get('rps_50',0)or 0)+float(h.get('rps_120',0)or 0)+float(h.get('rps_250',0)or 0) > 360:
            rps_by_day[td].add(c)
    except: pass

results_2023 = []
days_2023 = sorted(rps_by_day.keys())
for td in days_2023:
    if td not in sh_ok: continue
    for c in rps_by_day[td]:
        df = load_daily(c)
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
            results_2023.append({'code':c,'date':td,'entry_price':ep,**r})

# ── Years 2024-2026: from strategy files ──
for year in ['2024','2025','2026']:
    print(f"=== {year} ===", file=sys.stderr)
    results = []
    strat_files = sorted(DS.glob(f'dataset_stock_screener_strategies_{year}-*.json'))
    
    for sf in strat_files:
        td = sf.stem.replace('dataset_stock_screener_strategies_','')
        if td not in sh_ok: continue
        try: rows = json.loads(sf.read_text(encoding='utf-8'))
        except: continue
        
        for r in rows:
            c = str(r.get('symbol',''))
            if not c: continue
            conds = r.get('conditions',{})
            try:
                if float(conds.get('rps20',0)or 0)+float(conds.get('rps50',0)or 0)+float(conds.get('rps120',0)or 0)+float(conds.get('rps250',0)or 0) <= 360:
                    continue
            except: continue
            
            df = load_daily(c)
            if df is None: continue
            idx = get_idx(df, td)
            if idx is None: continue
            if not check_signal(df, idx): continue
            ni = idx+1
            if ni >= len(df): continue
            ep = float(df.iloc[ni]['open'])
            if ep <= 0: continue
            entry_date = str(df.index[ni])[:10]
            x = sim_exit(df, entry_date, ep)
            if x:
                results.append({'code':c,'date':td,'entry_price':ep,**x})
    
    if year == '2024': results_2024 = results
    elif year == '2025': results_2025 = results
    else: results_2026 = results

# ── Output ──
print()
print("=" * 110)
print("  神仙趋势策略 — 2023-2026 四年全景")
print("  规则: RPS>360 + EMA金叉 + C>EMA108 + MA30斜率>0 + 上证>MA200 | 出场: 死叉")
print("=" * 110)

all_years = [('2023', results_2023), ('2024', results_2024), ('2025', results_2025), ('2026', results_2026)]
grand_all = []

for year, results in all_years:
    # Monthly
    by_month = defaultdict(list)
    for r in results: by_month[r['date'][:7]].append(r)
    
    print(f"\n  {'─'*108}")
    print(f"  {year}年")
    
    y_rets = []
    for m in sorted(by_month.keys()):
        mr = by_month[m]
        rets = [r['return'] for r in mr]
        n = len(rets); avg = sum(rets)/n; wr = sum(1 for r in rets if r>0)/n*100
        dc = sum(1 for r in mr if r['exit_reason']=='death_cross')
        sh = n-dc
        
        print(f"  {m} | {n:>4}笔 | 均{avg:>+7.1f}% | 胜{wr:>3.0f}% | 中{sorted(rets)[n//2]:>+7.1f}% | 💀{dc} 📌{sh}")
        y_rets.extend(rets)
    
    if y_rets:
        gn = len(y_rets)
        print(f"  {'─'*108}")
        print(f"  {year}全年: {gn}笔 | 均{sum(y_rets)/gn:+.1f}% | 胜{sum(1 for r in y_rets if r>0)/gn*100:.0f}% | 中{sorted(y_rets)[gn//2]:+.1f}%")
        grand_all.extend(y_rets)
    else:
        print(f"  {year}全年: 0笔")

print(f"\n  {'='*108}")
ga = grand_all
if ga:
    print(f"  四年合计: {len(ga)}笔 | 均{sum(ga)/len(ga):+.1f}% | 胜{sum(1 for r in ga if r>0)/len(ga)*100:.0f}% | 中{sorted(ga)[len(ga)//2]:+.1f}%")
    print(f"  最大: {max(ga):+.1f}% | 最小: {min(ga):+.1f}%")
