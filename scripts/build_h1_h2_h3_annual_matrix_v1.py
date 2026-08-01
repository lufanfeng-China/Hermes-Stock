#!/usr/bin/env python3
"""Generate MACD-style start-year MTM matrices for H1/H2/H3 V3."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT=Path('/home/lufanfeng/Project-Hermes-Stock')
OUT=Path('/mnt/c/Users/Sky.Lu/Desktop/output')
PY='/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python'
BACKTEST=ROOT/'scripts/backtest_h1_h2_h3_csi300_qfq_mtm_v1.py'
YEARS=list(range(2012,2027)); LABEL='matrix_no_reset_20260801_v1'; TP='0.50'


def load_result(year: int, reset: bool) -> dict:
    mode='annual-reset' if reset else 'no-reset'
    subprocess.run([PY,str(BACKTEST),TP,f'{year}-01-01',mode,LABEL],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=600)
    suffix='annual_reset' if reset else 'no_reset'
    path=OUT/f'H1_H2_H3_CSI300_QFQ_strict_MTM_{year}0101_20260731_tp50%_{suffix}_{LABEL}.json'
    x=json.loads(path.read_text(encoding='utf-8'))
    r=next(v for v in x['results'] if v['variant']=='v3')
    assert x['annual_reset'] is reset and r['mtm_identity']==0
    return r


def build(reset: bool) -> list[dict]:
    return [{'start_year': year, **load_result(year, reset)} for year in YEARS]


def fmt(v): return f'{v:+.1f}%'
def render_section(title: str, rows: list[dict]) -> list[str]:
    lines=[title,'='*148,'起点    ' + '  '.join(f'年{i}' for i in range(1,16)) + '    总收益     最大回撤']
    for row in rows:
        returns=[fmt(a['return_pct']) for a in row['annual_mtm']]
        lines.append(f"{row['start_year']}年  " + '  '.join(f'{v:>7}' for v in returns) + f"  {fmt(row['return_pct']):>8}  {row['max_drawdown_pct']:+.1f}%")
    return lines

no_reset=build(False)
payload={'strategy':'H1/H2/H3 V3; H3乖离>50%止盈','start_years':YEARS,'signal_basis':'tdx_export_qfq','execution_and_valuation':'tdx_raw','initial_capital':10_000_000,'lot_cash':50_000,'annual_reset':False,'no_annual_reset':no_reset}
json_path=OUT/'H1_H2_H3_V3_H3乖离50pct_逐年回报率盯市_2012起不重置矩阵_20260731_v1.json'
json_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['H1/H2/H3 V3 · H3乖离>50%止盈 · 1000万初始资金 每份5万 严格MTM 逐年回报率','信号：通达信前复权；成交：T+1原始开盘价；盯市：原始收盘价；股票池：当前沪深300成分股（幸存者偏差）。','规则：允许跨年持仓；不执行年末强制平仓或资金重置。','总收益=起点至最后MTM权益的累计收益；最大回撤=该起点全程每日严格MTM权益最大回撤。','']
lines += render_section('不年末重置（允许跨年持仓）', no_reset)
txt_path=OUT/'H1_H2_H3_V3_H3乖离50pct_逐年回报率盯市_2012起不重置矩阵_20260731_v1.txt'
txt_path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'json':str(json_path),'txt':str(txt_path),'rows':len(YEARS)},ensure_ascii=False))
