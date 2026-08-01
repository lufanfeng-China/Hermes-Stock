#!/usr/bin/env python3
"""CSI300 H1/H2/H3 QFQ-signal, raw-execution strict-MTM backtest."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from mootdx.reader import Reader

ROOT=Path('/home/lufanfeng/Project-Hermes-Stock')
import sys; sys.path.insert(0,str(ROOT))
TAKE_PROFIT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.40
START = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp('2015-01-01')
ANNUAL_RESET = (sys.argv[3].strip().lower() in {'1', 'true', 'yes', 'annual-reset'}) if len(sys.argv) > 3 else False
if not 0 < TAKE_PROFIT < 1:
    raise ValueError('take-profit threshold must be in (0, 1)')
from app.tdx.qfq_kline import load_tdx_qfq_daily, align_qfq_signal_with_raw_execution

END=pd.Timestamp('2026-07-31')
CAPITAL=10_000_000.; LOT=50_000.
CODES=json.loads((ROOT/'data/derived/datasets/final/csi300_constituents_current_20260728.json').read_text())
OUT=Path('/mnt/c/Users/Sky.Lu/Desktop/output')


def bars_for(code, reader):
    try:
        raw=reader.daily(code).sort_index(); qfq=load_tdx_qfq_daily(code)
        x=align_qfq_signal_with_raw_execution(raw,qfq).sort_index()
    except Exception: return None
    if len(x)<120: return None
    c=x.signal_close.astype(float)
    h1=c.ewm(span=6,adjust=False).mean(); h2=h1.ewm(span=18,adjust=False).mean(); h3=c.ewm(span=108,adjust=False).mean()
    x['entry']=(h1>h2)&(h1.shift(1)<=h2.shift(1))&(h1>h3)&(h2>h3)&((h1/h3-1)<.10)&(h3>h3.shift(1))
    x['h3']=h3; x['h3_break']=c<h3; x['h3_distance']=c/h3-1
    x=x.loc[x.index>=START].copy()
    return x if len(x)>1 else None


def run(variant, frames):
    days=sorted({d for f in frames.values() for d in f.index}); lookup={c:{d:r for d,r in f.iterrows()} for c,f in frames.items()}
    cash=CAPITAL; pos={}; hist=[]; pending=defaultdict(list); pending_keys=set(); last={}; equity=[]; executed=rejected=0
    for day_i, day in enumerate(days):
        for order in sorted(pending.pop(day,[]),key=lambda o:0 if o['kind']=='exit' else 1):
            pending_keys.discard((order['kind'],order['code'])); c=order['code']; r=lookup[c].get(day); op=float(r.raw_open) if r is not None else 0
            if op<=0: rejected+=1; continue
            if order['kind']=='exit':
                p=pos.get(c)
                if not p: continue
                shares=sum(e['shares'] for e in p['entries']); cost=sum(e['price']*e['shares'] for e in p['entries']); rev=op*shares; cash+=rev
                hist.append({'code':c,'entry_date':p['entries'][0]['date'],'exit_date':str(day.date()),'reason':order['reason'],'cost':cost,'revenue':rev,'pnl':rev-cost,'days':(day-p['entries'][0]['ts']).days})
                del pos[c]; executed+=1; continue
            p=pos.get(c); shares=int(LOT/op); cost=shares*op
            if shares<=0 or cost>cash: rejected+=1; continue
            if order['kind']=='entry' and p: continue
            if order['kind']=='replenish' and not p: continue
            cash-=cost
            if not p: pos[c]={'entries':[],'below_h3_days':0}
            pos[c]['entries'].append({'date':str(day.date()),'ts':day,'price':op,'shares':shares}); executed+=1
        for c, rows in lookup.items():
            r=rows.get(day)
            if r is not None: last[c]=float(r.raw_close)
        for c,r in ((c,rows.get(day)) for c,rows in lookup.items()):
            if r is None or c not in pos: continue
            p=pos[c]; cost=sum(e['price']*e['shares'] for e in p['entries']); shares=sum(e['shares'] for e in p['entries']); raw_close=float(r.raw_close); pnl=raw_close*shares/cost-1
            h3_break=bool(r.h3_break); p['below_h3_days']=p['below_h3_days']+1 if h3_break else 0
            reason=None
            if variant=='v1' and p['below_h3_days']>=2: reason='H3连续两日失守'
            elif variant=='v2':
                if h3_break: reason='H3严格跌破止损'
                elif float(r.h3_distance)>TAKE_PROFIT: reason=f'H3乖离>{TAKE_PROFIT:.0%}止盈'
            elif variant=='v3':
                if float(r.h3_distance)>TAKE_PROFIT: reason=f'H3乖离>{TAKE_PROFIT:.0%}止盈'
                elif h3_break and pnl>=0: reason='跌破H3且非亏损退出'
            if reason and ('exit',c) not in pending_keys:
                ix=days.index(day)+1
                if ix<len(days): pending[days[ix]].append({'kind':'exit','code':c,'reason':reason}); pending_keys.add(('exit',c))
            # replenish only when no exit is pending
            elif bool(r.entry) and pnl<-.30 and ('replenish',c) not in pending_keys:
                ix=days.index(day)+1
                if ix<len(days): pending[days[ix]].append({'kind':'replenish','code':c}); pending_keys.add(('replenish',c))
        # At the final trading day of each year, liquidate at that day's raw close.
        # This is an explicit annual rebalance exception to the normal T+1 rule.
        is_year_end = day_i + 1 == len(days) or days[day_i + 1].year != day.year
        if ANNUAL_RESET and is_year_end:
            for c, p in list(pos.items()):
                shares=sum(e['shares'] for e in p['entries']); cost=sum(e['price']*e['shares'] for e in p['entries'])
                close=last.get(c, 0.0); revenue=shares*close; cash += revenue
                hist.append({'code':c,'entry_date':p['entries'][0]['date'],'exit_date':str(day.date()),'reason':'年末强制平仓','cost':cost,'revenue':revenue,'pnl':revenue-cost,'days':(day-p['entries'][0]['ts']).days})
                del pos[c]; executed += 1
            pending.clear(); pending_keys.clear()
            equity.append((day,cash))
            continue
        for c,r in ((c,rows.get(day)) for c,rows in lookup.items()):
            if r is not None and c not in pos and bool(r.entry) and ('entry',c) not in pending_keys:
                ix=days.index(day)+1
                if ix<len(days): pending[days[ix]].append({'kind':'entry','code':c}); pending_keys.add(('entry',c))
        mv=sum(sum(e['shares'] for e in p['entries'])*last.get(c,0) for c,p in pos.items()); equity.append((day,cash+mv))
    vals=np.array([v for _,v in equity]); peak=np.maximum.accumulate(vals); dd=(vals/peak-1).min()*100
    rets=[h['pnl']/h['cost']*100 for h in hist]; days_held=[h['days'] for h in hist]; wins=[x for x in rets if x>0]
    annual=[]; prior=CAPITAL
    equity_frame=pd.DataFrame(equity,columns=['date','equity']).set_index('date')
    for year, group in equity_frame.groupby(equity_frame.index.year):
        end_equity=float(group['equity'].iloc[-1])
        annual.append({'year':int(year),'as_of':str(group.index[-1].date()),'equity':round(end_equity,2),'return_pct':round((end_equity/prior-1)*100,2)})
        prior=end_equity
    return {'variant':variant,'start':str(START.date()),'end':str(equity[-1][0].date()),'capital':CAPITAL,'lot':LOT,'final_equity':round(float(vals[-1]),2),'return_pct':round((vals[-1]/CAPITAL-1)*100,2),'max_drawdown_pct':round(float(dd),2),'executed':executed,'rejected_cash':rejected,'open_positions':len(pos),'closed_trades':len(hist),'win_rate_pct':round(100*len(wins)/len(rets),2) if rets else None,'closed_avg_return_pct':round(float(np.mean(rets)),2) if rets else None,'closed_median_return_pct':round(float(np.median(rets)),2) if rets else None,'closed_avg_holding_days':round(float(np.mean(days_held)),1) if days_held else None,'closed_median_holding_days':round(float(np.median(days_held)),1) if days_held else None,'exit_reasons':{str(k): int(v) for k,v in pd.Series([h['reason'] for h in hist]).value_counts().items()} if hist else {},'annual_mtm':annual,'mtm_identity':round(float(vals[-1]-(cash+sum(sum(e['shares'] for e in p['entries'])*last.get(c,0) for c,p in pos.items()))),6)}

reader=Reader.factory(market='std',tdxdir='/home/lufanfeng/tdx_data')
frames={c.zfill(6):b for c in CODES if (b:=bars_for(c.zfill(6),reader)) is not None}
results=[run(v,frames) for v in ('v1','v2','v3')]
payload={'data_basis':{'signal':'tdx_export_qfq','execution':'tdx_raw','valuation':'tdx_raw'},'universe':'CSI300 current constituents (survivorship bias)','codes_loaded':len(frames),'take_profit_threshold_pct': TAKE_PROFIT * 100, 'annual_reset': ANNUAL_RESET, 'annual_reset_rule': '每年最后交易日原始收盘价强制平仓，跨年订单取消' if ANNUAL_RESET else None, 'rules':{'v1':'signal_close <= H3 连续2日，T+1卖出','v2':f'signal_close < H3 止损，或 signal_close/H3-1 > {TAKE_PROFIT:.0%} 止盈，T+1卖出','v3':f'signal_close/H3-1 > {TAKE_PROFIT:.0%}止盈，或 signal_close < H3 且 raw MTM非亏损，T+1卖出'},'results':results}
suffix = '_annual_reset_v4' if ANNUAL_RESET else '_v3'
OUT.mkdir(parents=True,exist_ok=True); out=OUT/f'H1_H2_H3_CSI300_QFQ_strict_MTM_{START:%Y%m%d}_20260731_tp{TAKE_PROFIT:.0%}{suffix}.json'; out.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
print(json.dumps(payload,ensure_ascii=False,indent=2)); print(out)
