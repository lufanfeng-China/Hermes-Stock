#!/usr/bin/env python3
"""
神仙趋势策略回测 — 2025全年 (RPS>360过滤版)
买入: 信号日次日开盘 | 卖出: CROSS(H2,H1)死亡交叉
预过滤: 逐日读取策略文件，仅对RPS>360的股票计算EMA信号
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

TARGET_MONTHS = ['2024-01','2024-02','2024-03','2024-04','2024-05','2024-06',
                 '2024-07','2024-08','2024-09','2024-10','2024-11','2024-12']

# ── Step 1: build RPS>360 lookup per day from strategy files ──
print("Building RPS>360 per day...", file=sys.stderr)
rps_stocks_by_day = defaultdict(set)  # trading_day -> set of codes
all_stocks_needed = set()

for target_month in TARGET_MONTHS:
    month_files = sorted(DS.glob(f'dataset_stock_screener_strategies_{target_month}-*.json'))
    for sf in month_files:
        td = sf.stem.replace('dataset_stock_screener_strategies_','')
        try:
            rows = json.loads(sf.read_text(encoding='utf-8'))
        except: continue
        for r in rows:
            c = str(r.get('symbol',''))
            if not c: continue
            conds = r.get('conditions',{})
            r20=conds.get('rps20') or conds.get('rps_20',0)
            r50=conds.get('rps50') or conds.get('rps_50',0)
            r120=conds.get('rps120') or conds.get('rps_120',0)
            r250=conds.get('rps250') or conds.get('rps_250',0)
            try:
                if float(r20)+float(r50)+float(r120)+float(r250) > 360:
                    rps_stocks_by_day[td].add(c)
                    all_stocks_needed.add(c)
            except: pass
    
    print(f"  {target_month}: {len(month_files)} files processed", file=sys.stderr)

print(f"  Total trading days: {len(rps_stocks_by_day)}", file=sys.stderr)
print(f"  Unique stocks with RPS>360: {len(all_stocks_needed)}", file=sys.stderr)

# ── Step 2: preload daily data ──
print("Preloading daily data...", file=sys.stderr)
daily = {}
stocks_list = sorted(all_stocks_needed)
for i, c in enumerate(stocks_list):
    if (i+1) % 200 == 0: print(f"  {i+1}/{len(stocks_list)}...", file=sys.stderr)
    try:
        df = reader.daily(symbol=c)
        if df is not None and not df.empty:
            daily[c] = df.sort_index()
    except: pass
print(f"  Loaded {len(daily)}", file=sys.stderr)

# ── Step 3: scan and simulate ──
all_results = {}
grand_signals = 0

for target_month in TARGET_MONTHS:
    month_files = sorted(DS.glob(f'dataset_stock_screener_strategies_{target_month}-*.json'))
    trading_days = [f.stem.replace('dataset_stock_screener_strategies_','') for f in month_files]
    if not trading_days:
        print(f"  {target_month}: skip", file=sys.stderr)
        continue
    
    print(f"  {target_month}: {len(trading_days)} days...", file=sys.stderr)
    signals = []
    
    for td in trading_days:
        day_stocks = rps_stocks_by_day.get(td, set())
        for c in day_stocks:
            df = daily.get(c)
            if df is None: continue
            if td not in df.index:
                m = df.index <= td
                if m.sum() == 0: continue
                idx = df.index.get_loc(df.index[m][-1])
            else:
                idx = df.index.get_loc(td)
            if idx < 110: continue
            
            closes = df['close'].astype(float).iloc[:idx+1]
            h1 = closes.ewm(span=6, adjust=False).mean()
            h2 = h1.ewm(span=18, adjust=False).mean()
            h3 = closes.ewm(span=108, adjust=False).mean()
            
            if not (h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2]): continue
            if not (closes.iloc[-1] > h3.iloc[-1]): continue
            
            ni = idx+1
            if ni >= len(df): continue
            ep = float(df.iloc[ni]['open'])
            if ep <= 0: continue
            
            signals.append({'code':c,'date':td,'entry_date':str(df.index[ni])[:10],
                           'entry_price':ep,'df':df})
    
    # Simulate
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
    
    all_results[target_month] = results
    grand_signals += len(results)
    print(f"    → {len(signals)} signals, {len(results)} simulated", file=sys.stderr)

# ── Output ──
print()
print("=" * 100)
print("  神仙趋势策略回测 — 2025年 (RPS>360)")
print("  买入: 信号日次日开盘 | 卖出: H2上穿H1死叉 | RPS>360")
print("=" * 100)

grand_rets = []
for target_month in TARGET_MONTHS:
    results = all_results.get(target_month, [])
    if not results: continue
    results.sort(key=lambda r: r['signal_date'])
    rets = [r['return'] for r in results]
    n = len(rets); dc = sum(1 for r in results if r['exit_reason']=='death_cross')
    sh = n-dc; avg = sum(rets)/n; wr = sum(1 for r in rets if r>0)/n*100
    
    print(f"\n  {target_month} | {n:>4}笔 | 均{avg:>+7.1f}% | 胜{wr:>3.0f}% | 中{sorted(rets)[n//2]:>+7.1f}% | 💀{dc} 📌{sh}")
    
    if n > 0:
        print(f"    最+{max(rets):+.1f}% | 最{min(rets):+.1f}%")
        top = sorted(results, key=lambda r: r['return'], reverse=True)[:2]
        for r in top:
            rl = {'death_cross':'💀','still_holding':'📌'}
            print(f"    {r['code']} {r['signal_date']} {r['return']:>+8.2f}% ({r['holding_days']}天 {rl.get(r['exit_reason'],'')})")
    
    grand_rets.extend(rets)

gn = len(grand_rets)
print(f"\n  {'─'*100}")
if gn > 0:
    print(f"  2024全年(RPS>360): {gn}笔 | 均{sum(grand_rets)/gn:+.1f}% | 胜{sum(1 for r in grand_rets if r>0)/gn*100:.0f}% | 中{sorted(grand_rets)[gn//2]:+.1f}%")
    print(f"  最大:{max(grand_rets):+.1f}% | 最小:{min(grand_rets):+.1f}%")
else:
    print(f"  2024全年(RPS>360): 0笔")
