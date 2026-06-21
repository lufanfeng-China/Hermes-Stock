#!/usr/bin/env python3
"""
RPS首次策略多维度回测对比:
  - RPS阈值: 360, 365, 370
  - 持有期: 一直持有, 1年(250交易日), 2年(500交易日)
  - 按买入月份展示
"""
import sys, json
from pathlib import Path
from collections import defaultdict, Counter

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/mnt/c/new_tdx64'

sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_THRESHOLDS = [360, 365, 370]
HOLDING_12M = 250   # 1年 ≈ 250交易日
HOLDING_24M = 500   # 2年 ≈ 500交易日

def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def get_all_signals():
    """Load all signals, keep lowest threshold set for data fetching"""
    strat_files = sorted(DS.glob('dataset_stock_screener_strategies_*.json'))
    seen = set()
    signals = []
    for sf in strat_files:
        try:
            rows = load_json(sf)
        except:
            continue
        for r in rows:
            if r.get('strategy') != 'rps_first' or not r.get('passed'):
                continue
            code = str(r.get('symbol', ''))
            if not code or code in seen:
                continue
            rps_total = r.get('conditions', {}).get('rps_total', 0)
            if rps_total < min(RPS_THRESHOLDS):  # keep all >= 360
                continue
            seen.add(code)
            signals.append({
                'code': code,
                'market': r.get('market', 'sh' if code.startswith('6') else 'sz'),
                'date': r.get('trading_day', ''),
                'rps_total': rps_total,
            })
    return signals

def fetch_data(signals):
    """Fetch daily data for all unique stocks"""
    print("Fetching daily data...", file=sys.stderr)
    cache = {}
    unique = set((s['market'], s['code']) for s in signals)
    for i, (m, c) in enumerate(unique):
        if (i+1) % 200 == 0:
            print(f"  daily {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            df = reader.daily(f"{m}{c}")
            if df is not None and not df.empty:
                cache[f"{m}{c}"] = df.sort_index()
        except:
            pass
    print(f"  Cached {len(cache)} stocks", file=sys.stderr)
    return cache

def fetch_xdxr(signals):
    """Fetch xdxr data"""
    print("Fetching xdxr data...", file=sys.stderr)
    xdxr_cache = {}
    unique = set((s['market'], s['code']) for s in signals)
    for i, (m, c) in enumerate(unique):
        if (i+1) % 200 == 0:
            print(f"  xdxr {i+1}/{len(unique)}...", file=sys.stderr)
        try:
            xd = quotes.xdxr(market=m, symbol=c)
            xm = {}
            if xd is not None and not xd.empty:
                for _, row in xd.iterrows():
                    sz = float(row.get('songzhuangu', 0) or 0)
                    if sz > 0:
                        date_str = f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"
                        xm[date_str] = sz
            xdxr_cache[f"{m}{c}"] = xm
        except:
            xdxr_cache[f"{m}{c}"] = {}
    sz_count = sum(1 for v in xdxr_cache.values() if v)
    print(f"  Stocks with送转股: {sz_count}", file=sys.stderr)
    return xdxr_cache

def filter_signals(signals, cache):
    """Filter ex-rights signals"""
    clean = []
    ex = 0
    for s in signals:
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None:
            clean.append(s)
            continue
        bad = False
        # Check signal date
        if s['date'] in df.index:
            idx = df.index.get_loc(s['date'])
            if idx > 0:
                pc = df.iloc[idx-1]['close']
                to = df.iloc[idx]['open']
                if pc > 0 and to > 0 and (to-pc)/pc < -0.10:
                    bad = True
        # Check entry date (next trading day)
        if not bad:
            msk = df.index >= s['date']
            ew = df.loc[msk]
            if not ew.empty:
                ed = ew.index[0]
                if ed in df.index:
                    idx = df.index.get_loc(ed)
                    if idx > 0:
                        pc = df.iloc[idx-1]['close']
                        to = df.iloc[idx]['open']
                        if pc > 0 and to > 0 and (to-pc)/pc < -0.10:
                            bad = True
        if bad:
            ex += 1
        else:
            clean.append(s)
    print(f"  Excluded {ex} ex-rights, {len(clean)} clean", file=sys.stderr)
    return clean

def compute_monthly_snapshots(df, entry_date, entry_price, xdxr_map):
    """
    For a single trade, compute returns at the end of each calendar month.
    Returns dict: { 'YYYY-MM': return_pct }
    
    Also computes the three horizon returns:
    - ret_12m: return after 250 trading days
    - ret_24m: return after 500 trading days  
    - ret_hold: return if held to end of data (一直持有)
    """
    mask = df.index >= entry_date
    window = df.loc[mask]
    if len(window) < 2:
        return {}, None, None, None

    monthly = {}
    ret_12m = None
    ret_24m = None
    
    current_ep = entry_price
    last_month = None
    prev_close = entry_price
    
    for i_day, (idx, row) in enumerate(window.iterrows()):
        idx_str = str(idx)[:10]
        
        # xdxr adjustment
        if idx_str in xdxr_map:
            sz = xdxr_map[idx_str]
            current_ep *= 1.0 / (1.0 + sz / 10.0)
        
        close = row['close']
        month_key = idx_str[:7]  # YYYY-MM
        
        # Record month-end snapshot (last trading day of each month)
        if month_key != last_month:
            if last_month is not None:
                # Save previous month's final close as snapshot
                ret = round((prev_close - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
                monthly[last_month] = ret
            last_month = month_key
        
        prev_close = close
        
        # Check horizon returns
        if ret_12m is None and i_day >= HOLDING_12M:
            epx = window.iloc[i_day+1]['open'] if i_day+1 < len(window) else close
            ret_12m = round((epx - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
        
        if ret_24m is None and i_day >= HOLDING_24M:
            epx = window.iloc[i_day+1]['open'] if i_day+1 < len(window) else close
            ret_24m = round((epx - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    
    # Save last month
    if last_month is not None:
        ret = round((prev_close - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
        monthly[last_month] = ret
    
    # 一直持有 return
    ret_hold = round((window.iloc[-1]['close'] - current_ep) / current_ep * 100, 2) if current_ep > 0 else None
    
    return monthly, ret_12m, ret_24m, ret_hold

def run_backtest():
    # Step 1: Load all signals (RPS >= 360)
    print("Loading signals...", file=sys.stderr)
    all_signals = get_all_signals()
    print(f"Total signals (RPS>=360): {len(all_signals)}", file=sys.stderr)
    
    # Step 2: Fetch data
    cache = fetch_data(all_signals)
    xdxr_cache = fetch_xdxr(all_signals)
    
    # Step 3: Filter
    signals = filter_signals(all_signals, cache)
    
    # Step 4: Simulate each signal
    print("Simulating trades...", file=sys.stderr)
    
    # Results structure:
    # results[threshold][buy_month] = list of {
    #   'ret_12m': float|None,
    #   'ret_24m': float|None,
    #   'ret_hold': float|None,
    #   'monthly': {month: ret}
    # }
    results = {t: defaultdict(list) for t in RPS_THRESHOLDS}
    
    for i, s in enumerate(signals):
        if (i+1) % 200 == 0:
            print(f"  {i+1}/{len(signals)}...", file=sys.stderr)
        
        df = cache.get(f"{s['market']}{s['code']}")
        if df is None:
            continue
        
        msk = df.index >= s['date']
        ew = df.loc[msk]
        if ew.empty:
            continue
        
        entry_date = ew.index[0]
        entry_price = ew.iloc[0]['open']
        if entry_price <= 0:
            continue
        
        xm = xdxr_cache.get(f"{s['market']}{s['code']}", {})
        monthly, ret_12m, ret_24m, ret_hold = compute_monthly_snapshots(
            df, entry_date, entry_price, xm
        )
        
        buy_month = s['date'][:7]
        trade_result = {
            'code': s['code'],
            'ret_12m': ret_12m,
            'ret_24m': ret_24m,
            'ret_hold': ret_hold,
            'monthly': monthly,
        }
        
        # Assign to threshold buckets
        rps = s['rps_total']
        for t in RPS_THRESHOLDS:
            if rps >= t:
                results[t][buy_month].append(trade_result)
    
    # Step 5: Output
    print("\n" + "=" * 120)
    print("  RPS首次策略 — RPS阈值 × 持有期 × 月度回测对比")
    print("=" * 120)
    
    # ---- Summary Table ----
    print(f"\n{'─'*120}")
    print("  【一】总体汇总: RPS阈值 × 持有期")
    print(f"{'─'*120}")
    
    header = f"  {'指标':<20}"
    for t in RPS_THRESHOLDS:
        header += f" | {'RPS≥'+str(t)+' 12月':>14} {'RPS≥'+str(t)+' 24月':>14} {'RPS≥'+str(t)+' 持有':>14}"
    print(header)
    print(f"  {'─'*119}")
    
    for t in RPS_THRESHOLDS:
        all_trades_t = []
        for m_trades in results[t].values():
            all_trades_t.extend(m_trades)
        
        # Counts
        n_all = len(all_trades_t)
        n_12 = sum(1 for tr in all_trades_t if tr['ret_12m'] is not None)
        n_24 = sum(1 for tr in all_trades_t if tr['ret_24m'] is not None)
        n_hold = sum(1 for tr in all_trades_t if tr['ret_hold'] is not None)
        
        r12 = [tr['ret_12m'] for tr in all_trades_t if tr['ret_12m'] is not None]
        r24 = [tr['ret_24m'] for tr in all_trades_t if tr['ret_24m'] is not None]
        rh = [tr['ret_hold'] for tr in all_trades_t if tr['ret_hold'] is not None]
        
        def stats(rlist, label):
            if not rlist:
                return f"{'N/A':>14}"
            avg = sum(rlist)/len(rlist)
            wr = sum(1 for x in rlist if x > 0)/len(rlist)*100
            med = sorted(rlist)[len(rlist)//2]
            return f"{avg:>+7.1f}% {wr:>3.0f}% {med:>+7.1f}%" if len(rlist) >= 5 else f"{avg:>+7.1f}%"
        
        row = f"  RPS≥{t} ({n_all:>3}笔)"
        row += f" | {stats(r12, '12月'):>14}" if r12 else f" | {'N/A':>14}"
        row += f" | {stats(r24, '24月'):>14}" if r24 else f" | {'N/A':>14}"
        row += f" | {stats(rh, '持有'):>14}" if rh else f" | {'N/A':>14}"
        print(row)
    
    print(f"\n  注: 每格格式 = 平均收益 胜率 中位数")
    
    # ---- Monthly Detail Table (for 12-month holding) ----
    print(f"\n{'─'*120}")
    print("  【二】月度明细: 买入月份 → 持有12月/24月/一直持有 的平均收益")
    print(f"{'─'*120}")
    
    # Collect all months
    all_months = set()
    for t in RPS_THRESHOLDS:
        all_months.update(results[t].keys())
    all_months = sorted(all_months)
    
    legend = "  每格: 12月收益 | 24月收益 | 一直持有收益 (笔数)"
    print(legend)
    print()
    
    sub_header = f"  {'买入月份':<10}"
    for t in RPS_THRESHOLDS:
        sub_header += f" | {'RPS≥'+str(t):^42}"
    print(sub_header)
    print(f"  {'─'*120}")
    
    for month in all_months:
        row = f"  {month:<10}"
        for t in RPS_THRESHOLDS:
            m_trades = results[t].get(month, [])
            if not m_trades:
                row += f" | {'':^42}"
                continue
            
            r12 = [tr['ret_12m'] for tr in m_trades if tr['ret_12m'] is not None]
            r24 = [tr['ret_24m'] for tr in m_trades if tr['ret_24m'] is not None]
            rh = [tr['ret_hold'] for tr in m_trades if tr['ret_hold'] is not None]
            
            a12 = f"{sum(r12)/len(r12):+6.1f}%" if r12 else "   N/A"
            a24 = f"{sum(r24)/len(r24):+6.1f}%" if r24 else "   N/A"
            ah = f"{sum(rh)/len(rh):+6.1f}%" if rh else "   N/A"
            
            cell = f"{a12} {a24} {ah} ({len(m_trades):>2})"
            row += f" | {cell:^42}"
        print(row)
    
    # ---- Annual Summary ----
    print(f"\n{'─'*120}")
    print("  【三】年度汇总")
    print(f"{'─'*120}")
    
    for t in RPS_THRESHOLDS:
        print(f"\n  RPS≥{t}:")
        print(f"  {'年度':<10} {'笔数':>5} {'12月退出':>12} {'24月退出':>12} {'一直持有':>12} {'12月胜率':>9} {'24月胜率':>9}")
        print(f"  {'─'*72}")
        
        for year in ['2024', '2025', '2026']:
            y_trades = []
            for m, m_trades in results[t].items():
                if m.startswith(year):
                    y_trades.extend(m_trades)
            
            if not y_trades:
                continue
            
            r12 = [tr['ret_12m'] for tr in y_trades if tr['ret_12m'] is not None]
            r24 = [tr['ret_24m'] for tr in y_trades if tr['ret_24m'] is not None]
            rh = [tr['ret_hold'] for tr in y_trades if tr['ret_hold'] is not None]
            
            a12 = f"{sum(r12)/len(r12):+7.1f}%" if r12 else "    N/A"
            a24 = f"{sum(r24)/len(r24):+7.1f}%" if r24 else "    N/A"
            ah = f"{sum(rh)/len(rh):+7.1f}%" if rh else "    N/A"
            w12 = f"{sum(1 for x in r12 if x>0)/len(r12)*100:>4.0f}%" if r12 else " N/A"
            w24 = f"{sum(1 for x in r24 if x>0)/len(r24)*100:>4.0f}%" if r24 else " N/A"
            
            print(f"  {year:<10} {len(y_trades):>5} {a12:>12} {a24:>12} {ah:>12} {w12:>9} {w24:>9}")
    
    # ---- Threshold Comparison (fair: same signals, different thresholds) ----
    print(f"\n{'─'*120}")
    print("  【四】阈值敏感度: 同一批已完成12月的信号，不同阈值下的表现")
    print(f"{'─'*120}")
    
    # Find signals common across thresholds with completed 12-month
    # Start with RPS≥370 set (smallest)
    common_codes_370 = set()
    for m_trades in results[370].values():
        for tr in m_trades:
            if tr['ret_12m'] is not None:
                common_codes_370.add(tr['code'])
    
    # For each threshold, compute stats on the same set
    for t in RPS_THRESHOLDS:
        subset = []
        for m_trades in results[t].values():
            for tr in m_trades:
                if tr['code'] in common_codes_370 and tr['ret_12m'] is not None:
                    subset.append(tr)
        
        if subset:
            r12 = [tr['ret_12m'] for tr in subset]
            r24 = [tr['ret_24m'] for tr in subset if tr['ret_24m'] is not None]
            rh = [tr['ret_hold'] for tr in subset if tr['ret_hold'] is not None]
            
            a12 = sum(r12)/len(r12)
            w12 = sum(1 for x in r12 if x>0)/len(r12)*100
            a24 = sum(r24)/len(r24) if r24 else 0
            ah = sum(rh)/len(rh) if rh else 0
            
            print(f"  RPS≥{t}: {len(subset):>3}笔 | 12月 {a12:>+7.1f}% (胜率{w12:.0f}%)", end="")
            if r24:
                print(f" | 24月 {a24:>+7.1f}%", end="")
            print(f" | 一直持有 {ah:>+7.1f}%")
    
    # ---- Distribution ----
    print(f"\n{'─'*120}")
    print("  【五】收益分布: 已完成12月的交易")
    print(f"{'─'*120}")
    
    for t in RPS_THRESHOLDS:
        all_t = []
        for m_trades in results[t].values():
            all_t.extend(m_trades)
        
        r12_done = [tr['ret_12m'] for tr in all_t if tr['ret_12m'] is not None]
        if not r12_done:
            continue
        
        buckets = [(-100, -50), (-50, -25), (-25, -10), (-10, 0), (0, 10), (10, 25),
                    (25, 50), (50, 100), (100, 200), (200, 9999)]
        
        print(f"\n  RPS≥{t} ({len(r12_done)}笔已完成12月):")
        print(f"  {'区间':>12} {'笔数':>5} {'占比':>7} {'累计':>7}")
        cum = 0
        for lo, hi in buckets:
            cnt = sum(1 for r in r12_done if lo <= r < hi)
            cum += cnt
            pct = cnt/len(r12_done)*100
            cpct = cum/len(r12_done)*100
            bar = '█' * int(pct/2)
            rng = f"{lo:+d}~{hi:+d}" if hi < 9999 else f">{lo:+d}"
            print(f"  {rng:>12} {cnt:>5} {pct:>6.1f}% {cpct:>6.1f}% {bar}")

if __name__ == '__main__':
    run_backtest()
