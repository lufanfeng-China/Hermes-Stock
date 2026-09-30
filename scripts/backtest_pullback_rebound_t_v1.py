#!/usr/bin/env python3
"""Fixed-stock pullback/rebound daily-T backtest: QFQ T-close signals, raw T+1 execution."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any
import pandas as pd
from mootdx.reader import Reader

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.config import TDX_QFQ_EXPORT_DIR, TONGDAXIN_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

SAMPLES=[('603129','春风动力','单边上涨'),('600208','衢州发展','震荡行情'),('600363','联创光电','单边下跌')]
INITIAL=1_000_000.0
BUY_SLIPPAGE=SELL_SLIPPAGE=.001
COMMISSION=.0003
STAMP=.0005

def buy_cost(p:float,n:int)->float:return p*n*(1+BUY_SLIPPAGE)*(1+COMMISSION)
def sell_proceeds(p:float,n:int)->float:return p*n*(1-SELL_SLIPPAGE)*(1-COMMISSION-STAMP)
def completed_lot_net_return(sell:float,buy:float)->float:return sell_proceeds(sell,1)/buy_cost(buy,1)-1
def cancel_pullback_buy(open_price:float,previous_close:float)->bool:return previous_close>0 and open_price/previous_close-1>.0400001
def raw_target_reached(raw_close:float,raw_entry:float)->bool:return raw_close/raw_entry-1>=.08

def rsi(close:pd.Series,n:int=6)->pd.Series:
 d=close.diff();u=d.clip(lower=0);dn=-d.clip(upper=0)
 au=u.ewm(alpha=1/n,adjust=False,min_periods=n).mean();ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
 return 100-100/(1+au/ad.where(ad>0))

def frame(raw:pd.DataFrame,qfq:pd.DataFrame,start:str)->pd.DataFrame:
 q=qfq.sort_index().copy();q.index=pd.to_datetime(q.index)
 q['ma10']=q.close.rolling(10).mean();q['ma20']=q.close.rolling(20).mean();q['ma60']=q.close.rolling(60).mean();q['rsi6']=rsi(q.close);q['dd20']=q.close/q.high.rolling(20).max()-1
 q['trend']=(q.ma20>q.ma60)&(q.ma60>=q.ma60.shift(5))&(q.close>=q.ma60*.97)
 q['buy1']=q.trend&(q.dd20<=-.08)&(q.close<=q.ma20)&(q.rsi6<=35)&(q.close>q.open)&(q.close>=q.low*1.015)
 q['buy2']=q.trend&(q.dd20<=-.13)&(q.close<=q.ma60*1.02)&(q.rsi6<=28)&(q.close>q.open)
 q['ma_rebound']=(q.close>=q.ma10)&(q.rsi6>=62)
 q['mid_rebound']=(q.close>=q.ma20)&(q.dd20>=-.02)
 q['below60twice']=(q.close<q.ma60)&(q.close.shift(1)<q.ma60.shift(1))
 r=raw.sort_index().copy();r.index=pd.to_datetime(r.index)
 ix=r.index.intersection(q.index)
 f=r.loc[ix,['open','high','low','close','volume']].join(q.loc[ix,['close','buy1','buy2','ma_rebound','mid_rebound','below60twice']].rename(columns={'close':'qclose'}))
 return f[(f.index>=pd.Timestamp(start))&(f.volume>0)&(f.open>0)].copy()

def simulate(raw:pd.DataFrame,qfq:pd.DataFrame,start:str)->dict[str,Any]:
 f=frame(raw,qfq,start)
 if len(f)<90:raise ValueError(f'need 90 valid bars, got {len(f)}')
 p0=float(f.iloc[0].open); total=int(INITIAL/(p0*(1+BUY_SLIPPAGE)*(1+COMMISSION))//500)*500;unit=total//5;core=unit*3
 cash=INITIAL-buy_cost(p0,core); lots:list[dict[str,Any]]=[];orders=[{'date':f.index[0].date().isoformat(),'action':'core_initial_buy','shares':core,'raw_price':p0}];completed=[];daily=[];pending:dict[str,Any]|None=None;cancelled={'buy_gap_up':0,'no_cash':0}
 for i,(dt,row) in enumerate(f.iterrows()):
  o,c=float(row.open),float(row.close);prev=float(f.iloc[i-1].close) if i else p0
  if pending:
   act=pending['action']
   if act.startswith('buy'):
    if cancel_pullback_buy(o,prev):cancelled['buy_gap_up']+=1
    elif len(lots)<2:
     cost=buy_cost(o,unit)
     if cost<=cash+1e-7:
      cash-=cost;lots.append({'entry_date':dt.date().isoformat(),'entry_raw':o,'shares':unit,'tier':act});orders.append({'date':dt.date().isoformat(),'action':act,'shares':unit,'raw_price':o})
     else:cancelled['no_cash']+=1
   elif act=='risk_exit':
    for lot in lots:
     cash+=sell_proceeds(o,lot['shares']);lot['exit_date']=dt.date().isoformat();lot['exit_raw']=o;lot['reason']='risk';lot['net_return']=completed_lot_net_return(o,lot['entry_raw']);completed.append(lot);orders.append({'date':dt.date().isoformat(),'action':'risk_sell','shares':lot['shares'],'raw_price':o})
    lots=[]
   elif act=='rebound_exit':
    remain=[]
    for lot in lots:
     rawret=c/lot['entry_raw']-1
     if raw_target_reached(c,lot['entry_raw']) or bool(row.ma_rebound) or bool(row.mid_rebound):
      cash+=sell_proceeds(o,lot['shares']);lot['exit_date']=dt.date().isoformat();lot['exit_raw']=o;lot['reason']='rebound';lot['net_return']=completed_lot_net_return(o,lot['entry_raw']);completed.append(lot);orders.append({'date':dt.date().isoformat(),'action':'rebound_sell','shares':lot['shares'],'raw_price':o})
     else:remain.append(lot)
    lots=remain
  pending=None
  if i+1<len(f):
   risk=bool(row.below60twice) or any(c/lot['entry_raw']-1<=-.08 for lot in lots)
   sell=any(raw_target_reached(c,lot['entry_raw']) or bool(row.ma_rebound) or bool(row.mid_rebound) for lot in lots)
   if lots and risk: pending={'action':'risk_exit'}
   elif lots and sell: pending={'action':'rebound_exit'}
   elif len(lots)==1 and bool(row.buy2):pending={'action':'buy2'}
   elif not lots and bool(row.buy1):pending={'action':'buy1'}
  mv=(core+sum(x['shares'] for x in lots))*c;daily.append({'date':dt.date().isoformat(),'cash':cash,'market_value':mv,'equity':cash+mv,'open_lots':len(lots),'pending':None if pending is None else pending['action']})
 d=pd.DataFrame(daily);final=float(d.iloc[-1].equity);bh_cash=INITIAL-buy_cost(p0,total);bh=bh_cash+total*float(f.iloc[-1].close); passive=INITIAL-buy_cost(p0,core)+core*float(f.iloc[-1].close)
 returns=pd.Series([x['net_return'] for x in completed],dtype=float)
 return {'summary':{'start':f.index[0].date().isoformat(),'end':f.index[-1].date().isoformat(),'days':len(f),'qfq_stock_return':float(f.iloc[-1].qclose/f.iloc[0].qclose-1),'raw_buy_hold_return':bh/INITIAL-1,'passive_60_stock_40_cash_return':passive/INITIAL-1,'strategy_strict_mtm_return':final/INITIAL-1,'strategy_excess_over_passive':final/passive-1,'max_drawdown':float((d.equity/d.equity.cummax()-1).min()),'completed_lots':len(completed),'wins':int((returns>0).sum()),'success_rate':None if returns.empty else float((returns>0).mean()),'mean_lot_return':None if returns.empty else float(returns.mean()),'median_lot_return':None if returns.empty else float(returns.median()),'open_lots_end':len(lots),'cancelled':cancelled,'mtm_invariant':bool((d.equity-d.cash-d.market_value).abs().max()<.01)},'orders':orders,'completed_lots':completed,'open_lots':lots,'daily_equity':daily}

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--start',default='2025-01-01');ap.add_argument('--output-dir',type=Path,default=Path('/mnt/c/Users/Sky.Lu/Desktop/output'));ap.add_argument('--tdxdir',default=TONGDAXIN_DIR);ap.add_argument('--qfq-export-dir',type=Path,default=TDX_QFQ_EXPORT_DIR);a=ap.parse_args()
 reader=Reader.factory(market='std',tdxdir=a.tdxdir);stocks=[]
 for code,name,regime in SAMPLES:
  x=simulate(reader.daily(code),load_tdx_qfq_daily(code,a.qfq_export_dir),a.start);stocks.append({'code':code,'name':name,'regime':regime,**x})
 table=[{'code':x['code'],'name':x['name'],'regime':x['regime'],**x['summary']} for x in stocks];a.output_dir.mkdir(parents=True,exist_ok=True);stem='固定单股回撤反弹做T_三类行情验证_2025-01-01_至raw最新_20260930_v1';js=a.output_dir/(stem+'.json');csv=a.output_dir/(stem+'.csv');js.write_text(json.dumps({'rules':'QFQ T-close signals; raw T+1 execution','table':table,'stocks':stocks},ensure_ascii=False,indent=2),encoding='utf-8');pd.DataFrame(table).to_csv(csv,index=False,encoding='utf-8-sig');print(json.dumps({'json':str(js),'csv':str(csv),'table':table},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
