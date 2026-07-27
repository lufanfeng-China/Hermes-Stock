#!/usr/bin/env python3
"""CSI300 MACD极值策略 历年回测"""
import json, time, numpy as np, pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR='/mnt/c/new_tdx64'; LOT=50000
with open('/tmp/csi300_constituents.json') as f:
    codes=sorted(set(str(c) for c in json.load(f)))
reader=Reader.factory(market='std',tdxdir=TDX_DIR)

all_trades=[]; all_open={}

for code in codes:
    try:
        df=reader.daily(code)
        if df is None or len(df)<100: continue
    except: continue
    df=df.sort_index()
    mask=(df.index>='2016-01-01')&(df.index<='2026-07-23')
    df=df[mask].copy(); n=len(df)
    if n<100: continue
    c=df['close'].values.astype(np.float64); o=df['open'].values.astype(np.float64)
    dates=df.index
    ema12=pd.Series(c).ewm(span=12,adjust=False).mean().values
    ema26=pd.Series(c).ewm(span=26,adjust=False).mean().values
    dif=ema12-ema26; dea=pd.Series(dif).ewm(span=9,adjust=False).mean().values
    ndif=np.where(c!=0,dif/c*100,0); ndea=np.where(c!=0,dea/c*100,0)
    ma10=np.full(n,np.nan)
    for i in range(9,n): ma10[i]=np.mean(c[i-9:i+1])
    
    lots=[]; entry_idx=None
    for i in range(60,n):
        cp=c[i]
        if np.isnan(cp) or cp<=0: continue
        if lots:
            tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
            if tc>0 and cp*tq/tc-1>0.20:
                si=i+1
                if si<n:
                    sp=o[si]; sv=sp*tq; pnl=sv-tc; ret=(sv/tc-1)*100
                    y=dates[si].year
                    bd=str(dates[entry_idx].date()) if entry_idx else '?'
                    sd=str(dates[si].date())
                    all_trades.append({'code':code,'year':y,'pnl':pnl,'ret':ret,'hold':si-entry_idx,'lots':len(lots)})
                    lots=[]; entry_idx=None
                continue
        if np.isnan(ndif[i]) or np.isnan(ndea[i]) or np.isnan(ndif[i-1]) or np.isnan(ndea[i-1]): continue
        if not (ndif[i]>ndea[i] and ndif[i-1]<=ndea[i-1] and ndif[i]<-3.0): continue
        if np.isnan(ma10[i]) or np.isnan(ma10[i-1]): continue
        if ma10[i]<=ma10[i-1]: continue
        if lots:
            tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
            if cp*tq/tc-1<-0.20:
                target_avg=cp/0.9; q=int(max(1,round((target_avg*tq-tc)/(cp-target_avg))))
                bi=i+1
                if bi<n: lots.append((o[bi],q))
        else:
            bi=i+1
            if bi<n: lots=[(o[bi],int(LOT/o[bi]))]; entry_idx=bi
    if lots:
        tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
        cur=c[-1]
        all_open[code]={'lots':len(lots),'cost':tc,'pnl':cur*tq-tc,'pct':(cur*tq/tc-1)*100}

df=pd.DataFrame(all_trades)
opp=sum(p['pnl'] for p in all_open.values())
total_net=df['pnl'].sum()+opp

print(f'CSI300 MACD极值策略 历年回测')
print(f'规则: ndif<-5%金叉+MA10上升买入, -20%补仓到-10%, +20%止盈, T+1执行')
print(f'')
print(f'{"年":<6} {"笔数":>4} {"胜率":>5} {"均值":>7} {"盈亏":>10} {"持天":>4}')
print('-'*50)
for y in range(2016,2027):
    sy=df[df['year']==y]
    n=len(sy); m=sy['ret'].mean() if n>0 else 0
    wr=(sy['ret']>0).mean()*100 if n>0 else 0
    tp=sy['pnl'].sum() if n>0 else 0
    h=sy['hold'].mean() if n>0 else 0
    print(f'{y:<6} {n:>4} {wr:>4.0f}% {m:>+6.1f}% {tp:>+10,.0f} {h:>4.0f}')

wr_all = (df["ret"]>0).mean()*100
m_all = df["ret"].mean()
tp_all = df["pnl"].sum()
h_all = df["hold"].mean()
print('-'*50)
print(f'{"合计":<6} {len(df):>4} {wr_all:>4.0f}% {m_all:>+6.1f}% {tp_all:>+10,.0f} {h_all:>4.0f}')
print(f'')
print(f'持仓: {len(all_open)}只 浮亏{opp:+,.0f}')
print(f'全周期合计: {total_net:+,.0f}')
total_lots = len(df) + sum(p["lots"] for p in all_open.values())
total_invested = total_lots * LOT
print(f'总投资(含持仓): {total_invested:,}')

# Profit distribution
print(f'\n收益分布:')
bins=[(14,15),(15,16),(16,18),(18,20),(20,22),(22,25),(25,30),(30,40),(40,100)]
for lo,hi in bins:
    n_bin=sum(1 for r in df['ret'] if lo<=r<hi)
    pct=n_bin/len(df)*100
    bar='#'*int(pct)
    print(f'  [{lo:>3},{hi:>3})%: {n_bin:>3}笔 {pct:>4.1f}% {bar}')
