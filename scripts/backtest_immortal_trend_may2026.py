#!/usr/bin/env python3
"""
神仙趋势策略回测 — 2026年5月 (RPS预过滤优化版)
买入: 信号日次日开盘 | 卖出: CROSS(H2,H1)死亡交叉
预过滤: 仅加载 RPS>360 的股票日线数据
"""
import sys, json
from pathlib import Path

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/mnt/c/new_tdx64'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
reader = Reader.factory(market='std', tdxdir=TDX)

# ── Step 1: filter to RPS>360 stocks ──
print("Filtering RPS>360 stocks...", file=sys.stderr)
cur = json.loads((DS / 'dataset_stock_screener_strategies_current.json').read_text(encoding='utf-8'))
rps_stocks = {}
for r in cur:
    c = str(r.get('symbol',''))
    m = r.get('market','sh' if c.startswith('6') else 'sz')
    if c in rps_stocks: continue
    conds = r.get('conditions',{})
    r20=conds.get('rps20') or conds.get('rps_20',0)
    r50=conds.get('rps50') or conds.get('rps_50',0)
    r120=conds.get('rps120') or conds.get('rps_120',0)
    r250=conds.get('rps250') or conds.get('rps_250',0)
    try:
        total = float(r20)+float(r50)+float(r120)+float(r250)
        if total > 360:
            rps_stocks[c] = {'code':c,'market':m,'rps_total':total}
    except: pass
print(f"  RPS>360 stocks: {len(rps_stocks)}", file=sys.stderr)

# ── Step 2: preload daily data ──
print("Preloading daily data...", file=sys.stderr)
stocks_list = list(rps_stocks.values())
daily = {}
for i, s in enumerate(stocks_list):
    if (i+1) % 200 == 0: print(f"  {i+1}/{len(stocks_list)}...", file=sys.stderr)
    try:
        df = reader.daily(symbol=s['code'])
        if df is not None and not df.empty:
            daily[s['code']] = df.sort_index()
    except: pass
print(f"  Loaded {len(daily)}", file=sys.stderr)

# ── Step 3: scan May 2026 ──
may_files = sorted(DS.glob('dataset_stock_screener_strategies_2026-05-*.json'))
trading_days = [f.stem.replace('dataset_stock_screener_strategies_','') for f in may_files]
print(f"May 2026: {len(trading_days)} days, scanning...", file=sys.stderr)

signals = []
for td in trading_days:
    count = 0
    for s in stocks_list:
        c = s['code']
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
        
        h1_t=h1.iloc[-1]; h1_y=h1.iloc[-2]
        h2_t=h2.iloc[-1]; h2_y=h2.iloc[-2]
        
        if not (h1_t > h2_t and h1_y <= h2_y): continue
        if not (closes.iloc[-1] > h3.iloc[-1]): continue
        
        ni = idx+1
        if ni >= len(df): continue
        ep = float(df.iloc[ni]['open'])
        if ep <= 0: continue
        
        signals.append({'code':c,'date':td,'entry_date':str(df.index[ni])[:10],
                        'entry_price':ep,'df':df,'rps':s['rps_total']})
        count += 1
    print(f"  {td}: {count} signals (total {len(signals)})", file=sys.stderr)

print(f"\nTotal: {len(signals)} signals", file=sys.stderr)

# ── Step 4: simulate exits ──
print("Simulating exits...", file=sys.stderr)
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
                'entry_price':s['entry_price'],'exit_date':ed,
                'exit_price':round(ep,2),'exit_reason':'death_cross',
                'return':ret,'holding_days':i,'rps':s['rps']})
            exited = True
            break
    if not exited:
        ep = float(w.iloc[-1]['close'])
        ed = str(w.index[-1])[:10]
        ret = round((ep-s['entry_price'])/s['entry_price']*100,2)
        results.append({'code':s['code'],'signal_date':s['date'],
            'entry_price':s['entry_price'],'exit_date':ed,
            'exit_price':round(ep,2),'exit_reason':'still_holding',
            'return':ret,'holding_days':len(w)-1,'rps':s['rps']})

# ── Output ──
print()
print("=" * 105)
print("  神仙趋势策略回测 — 2026年5月 (RPS>360)")
print("  买入: 信号日次日开盘 | 卖出: H2上穿H1死亡交叉次日开盘")
print("=" * 105)

results.sort(key=lambda r: r['signal_date'])
print(f"\n  {'信号日':<12} {'代码':<10} {'RPS':>5} {'买入':>8} {'卖出日':<12} {'卖出':>8} {'收益':>9} {'天':>4} {'退出':<14}")
print(f"  {'─'*92}")

rets = []
for r in results:
    rl = {'death_cross':'💀死叉','still_holding':'📌持有中'}
    print(f"  {r['signal_date']:<12} {r['code']:<10} {r['rps']:>5.0f} {r['entry_price']:>8.2f} {r['exit_date']:<12} {r['exit_price']:>8.2f} {r['return']:>+8.2f}% {r['holding_days']:>3}天 {rl.get(r['exit_reason'],r['exit_reason']):<14}")
    rets.append(r['return'])

n=len(rets); dc=sum(1 for r in results if r['exit_reason']=='death_cross'); sh=n-dc
print(f"\n  {'─'*92}")
print(f"  总交易:{n}笔 | 平均:{sum(rets)/n:+.2f}% | 胜率:{sum(1 for r in rets if r>0)/n*100:.0f}% | 中位数:{sorted(rets)[n//2]:+.2f}%")
print(f"  最大:{max(rets):+.2f}% | 最小:{min(rets):+.2f}% | 死叉退出:{dc}笔 | 持有:{sh}笔")
