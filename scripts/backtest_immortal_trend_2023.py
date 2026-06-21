#!/usr/bin/env python3
"""
神仙趋势策略回测 — 上证<MA200不交易
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

# ── Step 1: RPS>360 lookup ──
print("Building RPS>360 from RPS history...", file=sys.stderr)
rps_path = Path("/tmp/dec2023_rps.json")
with open(rps_path) as f:
    rps_data = json.load(f)
print(f"  {len(rps_data)} entries", file=sys.stderr)

rps_stocks_by_day = defaultdict(set)
all_stocks = set()
all_days = sorted(set(h.get('trading_day','') for h in rps_data if h.get('trading_day')))
days_target = [d for d in all_days if d.startswith('2023')]

for h in rps_data:
    td = str(h.get('trading_day',''))
    if not td.startswith('2023'): continue
    c = str(h.get('symbol',''))
    if not c: continue
    try:
        if float(h.get('rps_20',0) or 0)+float(h.get('rps_50',0) or 0)+float(h.get('rps_120',0) or 0)+float(h.get('rps_250',0) or 0) > 360:
            rps_stocks_by_day[td].add(c)
            all_stocks.add(c)
    except: pass

print(f"  Days: {len(days_target)}, RPS>360 stocks: {len(all_stocks)}", file=sys.stderr)

# ── Step 2: preload daily data ──
print("Preloading daily data...", file=sys.stderr)
daily = {}
stocks_list = sorted(all_stocks)
for i, c in enumerate(stocks_list):
    if (i+1) % 200 == 0: print(f"  {i+1}/{len(stocks_list)}...", file=sys.stderr)
    try:
        df = reader.daily(symbol=c)
        if df is not None and not df.empty: daily[c] = df.sort_index()
    except: pass
print(f"  Loaded {len(daily)}", file=sys.stderr)

# ── Step 3: Shanghai Composite MA200 ──
print("Loading Shanghai Composite MA200...", file=sys.stderr)
sh_ok = set()
try:
    sh = reader.daily(symbol='000001')
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

# ── Step 4: scan ──
results_by_month = {}
months_2023 = sorted(set(d[:7] for d in days_target))

for target_month in months_2023:
    month_days = [d for d in days_target if d.startswith(target_month)]
    print(f"  {target_month}: {len(month_days)} days...", file=sys.stderr)
    signals = []
    
    for td in month_days:
        # Index filter: skip if below MA200
        if sh_ok and td not in sh_ok:
            continue
        
        for c in rps_stocks_by_day.get(td, set()):
            df = daily.get(c)
            if df is None: continue
            if td not in df.index:
                m = df.index <= td
                if m.sum() == 0: continue
                idx = df.index.get_loc(df.index[m][-1])
            else:
                idx = df.index.get_loc(td)
            if idx < 140: continue
            
            closes = df['close'].astype(float).iloc[:idx+1]
            h1 = closes.ewm(span=6, adjust=False).mean()
            h2 = h1.ewm(span=18, adjust=False).mean()
            h3 = closes.ewm(span=108, adjust=False).mean()
            ma30 = closes.rolling(30).mean()
            
            if not (h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2]): continue
            if not (closes.iloc[-1] > h3.iloc[-1]): continue
            if len(ma30.dropna()) < 6: continue
            if not (ma30.iloc[-1] > ma30.iloc[-6]): continue
            
            ni = idx+1
            if ni >= len(df): continue
            ep = float(df.iloc[ni]['open'])
            if ep <= 0: continue
            
            signals.append({'code':c,'date':td,'entry_date':str(df.index[ni])[:10],
                           'entry_price':ep,'df':df})
    
    # Simulate — death cross exit
    results = []
    for s in signals:
        mask = s['df'].index >= s['entry_date']
        w = s['df'].loc[mask]
        if len(w) < 3: continue
        cl = w['close'].astype(float)
        h1 = cl.ewm(span=6, adjust=False).mean()
        h2 = h1.ewm(span=18, adjust=False).mean()
        exited = False
        for i in range(2, len(w)):
            if h2.iloc[i] > h1.iloc[i] and h2.iloc[i-1] <= h1.iloc[i-1]:
                ei = i+1 if i+1 < len(w) else i
                ep = float(w.iloc[ei]['open'])
                ed = str(w.index[ei])[:10]
                ret = round((ep-s['entry_price'])/s['entry_price']*100,2)
                results.append({'code':s['code'],'signal_date':s['date'],
                    'entry_price':s['entry_price'],'exit_date':ed,'exit_price':round(ep,2),
                    'exit_reason':'death_cross','return':ret,'holding_days':i})
                exited = True; break
        if not exited:
            ep = float(w.iloc[-1]['close']); ed = str(w.index[-1])[:10]
            ret = round((ep-s['entry_price'])/s['entry_price']*100,2)
            results.append({'code':s['code'],'signal_date':s['date'],
                'entry_price':s['entry_price'],'exit_date':ed,'exit_price':round(ep,2),
                'exit_reason':'still_holding','return':ret,'holding_days':len(w)-1})
    
    results_by_month[target_month] = results
    print(f"    -> {len(signals)} signals, {len(results)} simulated", file=sys.stderr)

# ── Output ──
print()
print("=" * 100)
print("  神仙趋势策略 — 2023年 (上证<MA200不交易)")
print("  入场: RPS>360 + EMA金叉 + C>EMA108 + MA30斜率>0")
print("  出场: 死叉次日开盘")
print("=" * 100)

grand_rets = []
for target_month in months_2023:
    results = results_by_month.get(target_month, [])
    if not results: continue
    results.sort(key=lambda r: r['signal_date'])
    rets = [r['return'] for r in results]
    n = len(rets); dc = sum(1 for r in results if r['exit_reason']=='death_cross')
    sh = n-dc; avg = sum(rets)/n; wr = sum(1 for r in rets if r>0)/n*100
    
    print(f"\n  {target_month} | {n:>4}笔 | 均{avg:>+7.1f}% | 胜{wr:>3.0f}% | 中{sorted(rets)[n//2]:>+7.1f}% | 💀{dc} 📌{sh}")
    if n > 0:
        print(f"    最+{max(rets):+.1f}% | 最{min(rets):+.1f}%")
        for r in sorted(results, key=lambda r: r['return'], reverse=True)[:2]:
            rl = {'death_cross':'💀','still_holding':'📌'}
            print(f"    {r['code']} {r['signal_date']} {r['return']:>+8.2f}% ({r['holding_days']}天 {rl.get(r['exit_reason'],'')})")
    grand_rets.extend(rets)

gn = len(grand_rets)
print(f"\n  {'─'*100}")
if gn > 0:
    print(f"  2023全年: {gn}笔 | 均{sum(grand_rets)/gn:+.1f}% | 胜{sum(1 for r in grand_rets if r>0)/gn*100:.0f}% | 中{sorted(grand_rets)[gn//2]:+.1f}%")
    print(f"  最大:{max(grand_rets):+.1f}% | 最小:{min(grand_rets):+.1f}%")
    print(f"\n  对比原始版: 580笔 -> {gn}笔")
else:
    print("  2023全年: 0笔 (全部被上证MA200过滤)")
