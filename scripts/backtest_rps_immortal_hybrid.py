#!/usr/bin/env python3
"""
RPS首次 × 神仙趋势 混合策略回测
方案A: 纯RPS首次24月持有 (基准)
方案B: RPS买入→死叉卖出，不循环
方案C: RPS买入→死叉卖出→金叉再买→循环(2年内)
"""
import sys, json
from pathlib import Path
from collections import defaultdict

PROJECT = Path('/home/lufanfeng/Project-Hermes-Stock')
DS = PROJECT / 'data' / 'derived' / 'datasets' / 'final'
TDX = '/home/lufanfeng/tdx_data'
sys.path.insert(0, str(PROJECT))
from mootdx.reader import Reader
from mootdx.quotes import Quotes
reader = Reader.factory(market='std', tdxdir=TDX)
quotes = Quotes.factory(market='std')

RPS_MIN = 360
HOLDING = 500  # 24 months ≈ 500 trading days

# ── Load signals ──
print("Loading RPS-first signals...", file=sys.stderr)
strat_files = sorted(DS.glob('dataset_stock_screener_strategies_*.json'))
seen = set()
signals = []
for sf in strat_files:
    try: rows = json.loads(sf.read_text(encoding='utf-8'))
    except: continue
    td = sf.stem.replace('dataset_stock_screener_strategies_','')
    if not td.startswith('20'): continue
    for r in rows:
        if r.get('strategy') != 'rps_first' or not r.get('passed'): continue
        c = str(r.get('symbol',''))
        rps_total = r.get('conditions',{}).get('rps_total',0)
        if rps_total < RPS_MIN or c in seen: continue
        seen.add(c)
        market = r.get('market','sh' if c.startswith('6') else 'sz')
        # Only pre-2024-07 signals have completed 24 months
        if td >= '2024-07-01': continue
        signals.append({'code':c,'market':market,'date':td,'rps_total':rps_total})

# Apply 60-day dedup
print(f"  Raw: {len(signals)}", file=sys.stderr)
clean = []
last_signal = {}
all_dates = sorted(set(s['date'] for s in signals))
for s in sorted(signals, key=lambda x: x['date']):
    c = s['code']
    prev = last_signal.get(c)
    if prev is None:
        clean.append(s); last_signal[c] = s['date']
    else:
        try:
            if all_dates.index(s['date']) - all_dates.index(prev) > 60:
                clean.append(s); last_signal[c] = s['date']
        except: pass
signals = clean
print(f"  60d dedup: {len(signals)}", file=sys.stderr)

# ── Fetch data ──
print("Fetching daily data...", file=sys.stderr)
daily = {}
xdxr_map = {}
unique = set((s['market'],s['code']) for s in signals)
for i, (m, c) in enumerate(unique):
    if (i+1) % 300 == 0: print(f"  {i+1}/{len(unique)}...", file=sys.stderr)
    try:
        df = reader.daily(f"{m}{c}")
        if df is not None and not df.empty:
            daily[c] = df.sort_index()
    except: pass
    try:
        xd = quotes.xdxr(market=m, symbol=c)
        xm = {}
        if xd is not None and not xd.empty:
            for _, row in xd.iterrows():
                sz = float(row.get('songzhuangu',0) or 0)
                if sz > 0:
                    xm[f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"] = sz
        xdxr_map[c] = xm
    except: xdxr_map[c] = {}
print(f"  Loaded {len(daily)}", file=sys.stderr)

# ── Simulate ──
def get_emas(closes):
    h1 = closes.ewm(span=6, adjust=False).mean()
    h2 = h1.ewm(span=18, adjust=False).mean()
    return h1, h2

def find_first_entry(df, signal_date):
    """Find first entry: if H1>H2 on signal day, buy next day. Else wait for golden cross."""
    if signal_date not in df.index:
        m = df.index >= signal_date
        if m.sum() == 0: return None, None, None
        start_idx = df.index.get_loc(df.index[m][0])
    else:
        start_idx = df.index.get_loc(signal_date)
    
    # Get enough history for EMA
    if start_idx < 20: return None, None, None
    
    closes = df['close'].astype(float).iloc[:start_idx+1]
    h1, h2 = get_emas(closes)
    
    # Check H1 vs H2 on signal day
    if h1.iloc[-1] > h2.iloc[-1]:
        # Golden cross already active → buy next day
        ni = start_idx + 1
        if ni >= len(df): return None, None, None
        return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    
    # Wait for golden cross
    for i in range(start_idx + 1, min(start_idx + 100, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        h1, h2 = get_emas(closes)
        if len(h1) < 3: continue
        if h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2]:
            ni = i + 1
            if ni >= len(df): return None, None, None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    
    return None, None, None  # No golden cross within 100 days

def find_next_golden_cross(df, from_idx):
    """Find next golden cross after from_idx"""
    for i in range(from_idx + 1, min(from_idx + 100, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        h1, h2 = get_emas(closes)
        if len(h1) < 3: continue
        if h1.iloc[-1] > h2.iloc[-1] and h1.iloc[-2] <= h2.iloc[-2]:
            ni = i + 1
            if ni >= len(df): return None, None, None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def find_death_cross(df, from_idx, max_idx):
    """Find next death cross after from_idx, before max_idx"""
    for i in range(from_idx + 2, min(max_idx, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        h1, h2 = get_emas(closes)
        if len(h1) < 3: continue
        if h2.iloc[-1] > h1.iloc[-1] and h2.iloc[-2] <= h1.iloc[-2]:
            ni = i + 1
            if ni >= len(df): return ni-1, float(df.iloc[-1]['close']), str(df.index[-1])[:10]
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def get_macd(closes):
    """MACD(12,26,9): returns dif, dea, macd_bar"""
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea

def find_first_entry_macd(df, signal_date):
    """Find first entry using MACD golden cross"""
    if signal_date not in df.index:
        m = df.index >= signal_date
        if m.sum() == 0: return None, None, None
        start_idx = df.index.get_loc(df.index[m][0])
    else:
        start_idx = df.index.get_loc(signal_date)
    if start_idx < 30: return None, None, None
    closes = df['close'].astype(float).iloc[:start_idx+1]
    dif, dea = get_macd(closes)
    if dif.iloc[-1] > dea.iloc[-1]:
        ni = start_idx + 1
        if ni >= len(df): return None, None, None
        return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    # Wait for golden cross
    for i in range(start_idx+1, min(start_idx+100, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        dif, dea = get_macd(closes)
        if len(dif) < 3: continue
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            ni = i + 1
            if ni >= len(df): return None, None, None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def find_next_golden_macd(df, from_idx):
    for i in range(from_idx+1, min(from_idx+100, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        dif, dea = get_macd(closes)
        if len(dif) < 3: continue
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            ni = i+1
            if ni >= len(df): return None, None, None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def find_death_macd(df, from_idx, max_idx):
    for i in range(from_idx+2, min(max_idx, len(df))):
        closes = df['close'].astype(float).iloc[:i+1]
        dif, dea = get_macd(closes)
        if len(dif) < 3: continue
        if dea.iloc[-1] > dif.iloc[-1] and dea.iloc[-2] <= dif.iloc[-2]:
            ni = i+1
            if ni >= len(df): return i, float(df.iloc[-1]['close']), str(df.index[-1])[:10]
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def classify_trend_all(closes_series):
    """Precompute trend for all days. Returns list of trend strings, one per day."""
    n = len(closes_series)
    if n < 60:
        return ["insufficient"] * n
    
    arr = list(closes_series)
    ma20 = [None]*n; ma50 = [None]*n
    ma120 = [None]*n if n >= 120 else None
    ma250 = [None]*n if n >= 250 else None
    
    # Rolling sums for efficiency
    s20 = s50 = s120 = s250 = 0
    for i in range(n):
        s20 += arr[i]; s50 += arr[i]
        if ma120: s120 += arr[i]
        if ma250: s250 += arr[i]
        if i >= 20: s20 -= arr[i-20]
        if i >= 50: s50 -= arr[i-50]
        if ma120 and i >= 120: s120 -= arr[i-120]
        if ma250 and i >= 250: s250 -= arr[i-250]
        if i >= 19: ma20[i] = s20/20
        if i >= 49: ma50[i] = s50/50
        if ma120 and i >= 119: ma120[i] = s120/120
        if ma250 and i >= 249: ma250[i] = s250/250
    
    trends = ["insufficient"] * 60  # First 60 days
    for i in range(60, n):
        m20 = ma20[i]; m50 = ma50[i]
        m120 = ma120[i] if ma120 else None
        m250 = ma250[i] if ma250 else None
        if m20 is None or m50 is None:
            trends.append("insufficient"); continue
        close = arr[i]
        s20_5 = ma20[i-5] if i>=5 and ma20[i-5] is not None else m20
        s50_10 = ma50[i-10] if i>=10 and ma50[i-10] is not None else m50
        s20_slope = (m20 - s20_5) / (s20_5 or 1)
        s50_slope = (m50 - s50_10) / (s50_10 or 1)
        if m250 and m120 and m20 > m50 > m120 > m250 and close > m20 and s20_slope > 0 and s50_slope > 0:
            trends.append("strong_bullish")
        elif m120 and m20 > m50 > m120 and close > m20 and s20_slope > 0:
            trends.append("bullish")
        elif m250 and m120 and m20 < m50 < m120 < m250 and close < m20 and s20_slope < 0:
            trends.append("strong_bearish")
        elif m120 and m20 < m50 < m120 and close < m50:
            trends.append("bearish")
        elif m20 > m50 and close > m20:
            trends.append("recovering")
        else:
            trends.append("neutral")
    return trends

def is_bullish(trend):
    return trend in ("strong_bullish", "bullish")

def find_first_entry_ma1020(df, signal_date):
    """First entry using MA10/MA20 golden cross"""
    if signal_date not in df.index:
        m = df.index >= signal_date
        if m.sum() == 0: return None, None, None
        start_idx = df.index.get_loc(df.index[m][0])
    else:
        start_idx = df.index.get_loc(signal_date)
    if start_idx < 25: return None, None, None
    closes = df['close'].astype(float)
    ma10 = closes.rolling(10).mean()
    ma20 = closes.rolling(20).mean()
    if start_idx >= 19 and ma10.iloc[start_idx] > ma20.iloc[start_idx]:
        ni = start_idx+1
        if ni >= len(df): return None,None,None
        return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    for i in range(start_idx+1, min(start_idx+100, len(df))):
        if i < 20: continue
        if ma10.iloc[i] > ma20.iloc[i] and ma10.iloc[i-1] <= ma20.iloc[i-1]:
            ni = i+1
            if ni >= len(df): return None,None,None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def find_next_golden_ma1020(df, from_idx):
    closes = df['close'].astype(float)
    ma10 = closes.rolling(10).mean()
    ma20 = closes.rolling(20).mean()
    for i in range(from_idx+1, min(from_idx+100, len(df))):
        if i < 20: continue
        if ma10.iloc[i] > ma20.iloc[i] and ma10.iloc[i-1] <= ma20.iloc[i-1]:
            ni = i+1
            if ni >= len(df): return None,None,None
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def find_death_ma1020(df, from_idx, max_idx):
    closes = df['close'].astype(float)
    ma10 = closes.rolling(10).mean()
    ma20 = closes.rolling(20).mean()
    for i in range(from_idx+2, min(max_idx, len(df))):
        if i < 20: continue
        if ma20.iloc[i] > ma10.iloc[i] and ma20.iloc[i-1] <= ma10.iloc[i-1]:
            ni = i+1
            if ni >= len(df): return i, float(df.iloc[-1]['close']), str(df.index[-1])[:10]
            return ni, float(df.iloc[ni]['open']), str(df.index[ni])[:10]
    return None, None, None

def classify_short_trend_all(closes_series):
    """Precompute SHORT-term trend. Returns list per day."""
    n = len(closes_series)
    if n < 30: return ["insufficient"]*n
    arr = list(closes_series)
    ma10=[None]*n; ma20=[None]*n; ma30=[None]*n; ma60=[None]*n
    s10=s20=s30=s60=0
    for i in range(n):
        s10+=arr[i]; s20+=arr[i]; s30+=arr[i]; s60+=arr[i]
        if i>=10: s10-=arr[i-10]
        if i>=20: s20-=arr[i-20]
        if i>=30: s30-=arr[i-30]
        if i>=60: s60-=arr[i-60]
        if i>=9: ma10[i]=s10/10
        if i>=19: ma20[i]=s20/20
        if i>=29: ma30[i]=s30/30
        if i>=59: ma60[i]=s60/60
    trends=["insufficient"]*60
    for i in range(60,n):
        m10=ma10[i]; m20=ma20[i]; m30=ma30[i]; m60=ma60[i]
        if any(v is None for v in (m10,m20,m30,m60)):
            trends.append("insufficient"); continue
        close=arr[i]
        s10_3=ma10[i-3] if i>=3 and ma10[i-3] is not None else m10
        s20_5=ma20[i-5] if i>=5 and ma20[i-5] is not None else m20
        sl10=(m10-s10_3)/(s10_3 or 1); sl20=(m20-s20_5)/(s20_5 or 1)
        if m10>m20>m30>m60 and close>m10 and sl10>0 and sl20>0:
            trends.append("strong_bullish")
        elif m10>m20>m30 and close>m10 and sl10>0:
            trends.append("bullish")
        elif m10<m20<m30<m60 and close<m10 and sl10<0:
            trends.append("strong_bearish")
        elif m10<m20<m30 and close<m20:
            trends.append("bearish")
        elif m10>m20 and close>m10:
            trends.append("recovering")
        else:
            trends.append("neutral")
    return trends

def adjust_xdxr(entry_price, xm, entry_date_str, to_date_str, df):
    """Adjust entry price for送转股 between entry and exit"""
    ep = entry_price
    if entry_date_str in df.index and to_date_str in df.index:
        mask = (df.index >= entry_date_str) & (df.index <= to_date_str)
        for idx in df.index[mask]:
            ds = str(idx)[:10]
            if ds in xm:
                ep *= 1.0 / (1.0 + xm[ds] / 10.0)
    return ep

print("Simulating...", file=sys.stderr)
results_a = []  # Pure 24M hold
results_b = []  # Single entry → death cross
results_c = []  # Loop within 24M
results_d = []  # Death cross + drawdown > 15% only
results_e = []  # MACD golden/death cross
results_f = []  # Trend-based: bullish/strong_bullish hold
results_g = []  # Short-term trend-based
results_h = []  # MA10/MA20 crossover

for idx, s in enumerate(signals):
    if (idx+1) % 200 == 0: print(f"  {idx+1}/{len(signals)}...", file=sys.stderr)
    
    df = daily.get(s['code'])
    if df is None: continue
    xm = xdxr_map.get(s['code'], {})
    
    # Find signal day index
    if s['date'] not in df.index:
        m = df.index >= s['date']
        if m.sum() == 0: continue
        sig_idx = df.index.get_loc(df.index[m][0])
    else:
        sig_idx = df.index.get_loc(s['date'])
    
    # 24-month boundary
    max_idx = min(sig_idx + HOLDING, len(df) - 1)
    if max_idx <= sig_idx + 20: continue
    
    # ── Scheme A: Pure 24M hold ──
    if sig_idx + HOLDING < len(df):
        exit_a_idx = sig_idx + HOLDING
        ep_a = df.iloc[sig_idx + 1]['open']
        ep_a = adjust_xdxr(ep_a, xm, str(df.index[sig_idx+1])[:10], str(df.index[exit_a_idx])[:10], df)
        exit_px = df.iloc[exit_a_idx + 1]['open'] if exit_a_idx + 1 < len(df) else df.iloc[exit_a_idx]['close']
        ret_a = round((exit_px - ep_a) / ep_a * 100, 2) if ep_a > 0 else None
        if ret_a is not None:
            results_a.append({'code':s['code'],'date':s['date'],'return':ret_a})
    
    # ── Scheme B & C: First entry ──
    entry_idx, entry_price, entry_date = find_first_entry(df, s['date'])
    if entry_idx is None: continue
    
    # Scheme B: Single entry → first death cross or 24M
    dc_idx, dc_px, dc_date = find_death_cross(df, entry_idx, max_idx)
    if dc_idx is not None:
        ep_b = adjust_xdxr(entry_price, xm, entry_date, dc_date, df)
        ret_b = round((dc_px - ep_b) / ep_b * 100, 2) if ep_b > 0 else None
    else:
        # No death cross → hold to 24M
        if max_idx + 1 < len(df):
            end_px = df.iloc[max_idx + 1]['open']
        else:
            end_px = df.iloc[max_idx]['close']
        ep_b = adjust_xdxr(entry_price, xm, entry_date, str(df.index[max_idx])[:10], df)
        ret_b = round((end_px - ep_b) / ep_b * 100, 2) if ep_b > 0 else None
    
    if ret_b is not None:
        results_b.append({'code':s['code'],'date':s['date'],'return':ret_b,
                          'trades': 1, 'exit_reason': 'death_cross' if dc_idx else 'time'})
    
    # Scheme C: Loop within 24M
    trades_c = []
    cur_entry_idx = entry_idx
    cur_entry_price = entry_price
    cur_entry_date = entry_date
    
    while cur_entry_idx < max_idx:
        dc_idx, dc_px, dc_date = find_death_cross(df, cur_entry_idx, max_idx)
        
        if dc_idx is not None and dc_idx < max_idx:
            # Sell at death cross
            ep_c = adjust_xdxr(cur_entry_price, xm, cur_entry_date, dc_date, df)
            if ep_c > 0:
                trades_c.append({'buy_date': cur_entry_date, 'sell_date': dc_date,
                                 'buy_price': cur_entry_price, 'sell_price': dc_px,
                                 'return': round((dc_px - ep_c) / ep_c * 100, 2)})
            
            # Find next golden cross for re-entry
            next_idx, next_price, next_date = find_next_golden_cross(df, dc_idx)
            if next_idx is None or next_idx >= max_idx:
                break
            cur_entry_idx = next_idx
            cur_entry_price = next_price
            cur_entry_date = next_date
        else:
            # No death cross → hold to 24M and exit
            if max_idx + 1 < len(df):
                end_px = df.iloc[max_idx + 1]['open']
            else:
                end_px = df.iloc[max_idx]['close']
            ep_c = adjust_xdxr(cur_entry_price, xm, cur_entry_date, str(df.index[max_idx])[:10], df)
            if ep_c > 0:
                trades_c.append({'buy_date': cur_entry_date, 'sell_date': str(df.index[max_idx])[:10],
                                 'buy_price': cur_entry_price, 'sell_price': end_px,
                                 'return': round((end_px - ep_c) / ep_c * 100, 2)})
            break
    
    if trades_c:
        # Compound return: (1+r1)*(1+r2)*... - 1
        compound = 1.0
        for t in trades_c:
            compound *= (1 + t['return'] / 100)
        total_ret = round((compound - 1) * 100, 2)
        results_c.append({'code': s['code'], 'date': s['date'], 'return': total_ret,
                          'trades': len(trades_c), 'compound': True})
    
    # ── Scheme D: Hold, but sell if death cross AND drawdown from peak > 15% ──
    trades_d = []
    cur_entry_idx = entry_idx
    cur_entry_price = entry_price
    cur_entry_date = entry_date
    peak_price = entry_price
    
    i = entry_idx + 1
    while i < max_idx:
        px = float(df.iloc[i]['close'])
        if px > peak_price:
            peak_price = px
        
        # Check death cross
        if i >= entry_idx + 3:
            closes_check = df['close'].astype(float).iloc[:i+1]
            h1c, h2c = get_emas(closes_check)
            dc_now = bool(h2c.iloc[-1] > h1c.iloc[-1] and h2c.iloc[-2] <= h1c.iloc[-2])
        else:
            dc_now = False
        
        if dc_now:
            # Drawdown from peak
            dd = (peak_price - px) / peak_price * 100
            if dd > 15:
                # Sell at death cross + deep drawdown
                sell_idx = i + 1 if i + 1 < len(df) else i
                sell_px = float(df.iloc[sell_idx]['open']) if sell_idx < len(df) else px
                sell_date = str(df.index[sell_idx])[:10] if sell_idx < len(df) else str(df.index[i])[:10]
                ep_d = adjust_xdxr(cur_entry_price, xm, cur_entry_date, sell_date, df)
                if ep_d > 0:
                    trades_d.append({'buy_date': cur_entry_date, 'sell_date': sell_date,
                                     'return': round((sell_px - ep_d) / ep_d * 100, 2)})
                
                # Find next golden cross for re-entry
                next_idx, next_price, next_date = find_next_golden_cross(df, i)
                if next_idx is None or next_idx >= max_idx:
                    break
                cur_entry_idx = next_idx
                cur_entry_price = next_price
                cur_entry_date = next_date
                peak_price = next_price
                i = next_idx + 1
                continue
        
        i += 1
    else:
        # Reached max_idx without triggering → hold to 24M
        if max_idx + 1 < len(df):
            end_px = df.iloc[max_idx + 1]['open']
        else:
            end_px = df.iloc[max_idx]['close']
        ep_d = adjust_xdxr(cur_entry_price, xm, cur_entry_date, str(df.index[max_idx])[:10], df)
        if ep_d > 0:
            trades_d.append({'buy_date': cur_entry_date, 'sell_date': str(df.index[max_idx])[:10],
                             'return': round((end_px - ep_d) / ep_d * 100, 2)})
    
    if trades_d:
        compound = 1.0
        for t in trades_d:
            compound *= (1 + t['return'] / 100)
        total_ret = round((compound - 1) * 100, 2)
        results_d.append({'code': s['code'], 'date': s['date'], 'return': total_ret,
                          'trades': len(trades_d)})
    
    # ── Scheme E: MACD golden/death cross cycle ──
    entry_idx_e, entry_price_e, entry_date_e = find_first_entry_macd(df, s['date'])
    if entry_idx_e is not None:
        trades_e = []
        cur_idx = entry_idx_e
        cur_px = entry_price_e
        cur_date = entry_date_e
        
        while cur_idx < max_idx:
            dc_idx, dc_px, dc_date = find_death_macd(df, cur_idx, max_idx)
            if dc_idx is not None and dc_idx < max_idx:
                ep_e = adjust_xdxr(cur_px, xm, cur_date, dc_date, df)
                if ep_e > 0:
                    trades_e.append({'return': round((dc_px - ep_e) / ep_e * 100, 2)})
                next_idx, next_px, next_date = find_next_golden_macd(df, dc_idx)
                if next_idx is None or next_idx >= max_idx: break
                cur_idx = next_idx; cur_px = next_px; cur_date = next_date
            else:
                if max_idx + 1 < len(df): end_px = df.iloc[max_idx+1]['open']
                else: end_px = df.iloc[max_idx]['close']
                ep_e = adjust_xdxr(cur_px, xm, cur_date, str(df.index[max_idx])[:10], df)
                if ep_e > 0:
                    trades_e.append({'return': round((end_px - ep_e) / ep_e * 100, 2)})
                break
        
        if trades_e:
            compound = 1.0
            for t in trades_e: compound *= (1 + t['return'] / 100)
            total_ret = round((compound - 1) * 100, 2)
            results_e.append({'code': s['code'], 'date': s['date'], 'return': total_ret,
                              'trades': len(trades_e)})
    
    # Shared precompute for F & G
    entry_idx_f = entry_idx
    entry_price_f = entry_price
    entry_date_f = entry_date
    full_closes = df['close'].astype(float)
    trends = classify_trend_all(full_closes)
    
    # ── Scheme F ──
    if entry_idx_f is not None:
        trades_f = []
        cur_idx = entry_idx_f
        cur_px = entry_price_f
        cur_date = entry_date_f
        in_position = True
        
        i = cur_idx + 1
        while i < max_idx:
            if i >= len(trends): break
            trend = trends[i]
            
            if in_position and not is_bullish(trend):
                # Sell: trend turned non-bullish
                sell_idx = i + 1 if i + 1 < len(df) else i
                sell_px = float(df.iloc[sell_idx]['open']) if sell_idx < len(df) else float(df.iloc[i]['close'])
                sell_date = str(df.index[sell_idx])[:10] if sell_idx < len(df) else str(df.index[i])[:10]
                ep_f = adjust_xdxr(cur_px, xm, cur_date, sell_date, df)
                if ep_f > 0:
                    trades_f.append({'return': round((sell_px - ep_f) / ep_f * 100, 2)})
                in_position = False
                i = sell_idx + 1 if sell_idx < len(df) else max_idx
                continue
            
            if not in_position and is_bullish(trend):
                # Buy: trend returned to bullish
                buy_idx = i + 1 if i + 1 < len(df) else i
                if buy_idx < max_idx:
                    cur_px = float(df.iloc[buy_idx]['open'])
                    cur_date = str(df.index[buy_idx])[:10]
                    cur_idx = buy_idx
                    in_position = True
                    i = buy_idx + 1
                    continue
            
            i += 1
        
        # Close final position at 24M
        if in_position:
            if max_idx + 1 < len(df):
                end_px = df.iloc[max_idx + 1]['open']
            else:
                end_px = df.iloc[max_idx]['close']
            ep_f = adjust_xdxr(cur_px, xm, cur_date, str(df.index[max_idx])[:10], df)
            if ep_f > 0:
                trades_f.append({'return': round((end_px - ep_f) / ep_f * 100, 2)})
        
        if trades_f:
            compound = 1.0
            for t in trades_f: compound *= (1 + t['return'] / 100)
            total_ret = round((compound - 1) * 100, 2)
            results_f.append({'code': s['code'], 'date': s['date'], 'return': total_ret,
                              'trades': len(trades_f)})
    
    # ── Scheme G: Short-term trend version (same logic as F) ──
    if entry_idx_f is not None:
        trades_g = []
        cur_idx = entry_idx_f; cur_px = entry_price_f; cur_date = entry_date_f
        in_position = True
        short_trends = classify_short_trend_all(full_closes)
        
        i = cur_idx + 1
        while i < max_idx:
            if i >= len(short_trends): break
            trend = short_trends[i]
            if in_position and not is_bullish(trend):
                si = i+1 if i+1 < len(df) else i
                sp = float(df.iloc[si]['open']) if si < len(df) else float(df.iloc[i]['close'])
                sd = str(df.index[si])[:10] if si < len(df) else str(df.index[i])[:10]
                ep = adjust_xdxr(cur_px, xm, cur_date, sd, df)
                if ep > 0: trades_g.append({'return': round((sp-ep)/ep*100,2)})
                in_position = False; i = si+1 if si < len(df) else max_idx; continue
            if not in_position and is_bullish(trend):
                bi = i+1 if i+1 < len(df) else i
                if bi < max_idx:
                    cur_px = float(df.iloc[bi]['open']); cur_date = str(df.index[bi])[:10]
                    cur_idx = bi; in_position = True; i = bi+1; continue
            i += 1
        if in_position:
            end_px = df.iloc[max_idx+1]['open'] if max_idx+1 < len(df) else df.iloc[max_idx]['close']
            ep = adjust_xdxr(cur_px, xm, cur_date, str(df.index[max_idx])[:10], df)
            if ep > 0: trades_g.append({'return': round((end_px-ep)/ep*100,2)})
        if trades_g:
            c = 1.0
            for t in trades_g: c *= (1+t['return']/100)
            results_g.append({'code':s['code'],'date':s['date'],'return':round((c-1)*100,2),'trades':len(trades_g)})
    
    # ── Scheme H: MA10/MA20 crossover cycle ──
    entry_h, px_h, date_h = find_first_entry_ma1020(df, s['date'])
    if entry_h is not None:
        trades_h = []
        c_idx, c_px, c_date = entry_h, px_h, date_h
        while c_idx < max_idx:
            dc_idx, dc_px, dc_date = find_death_ma1020(df, c_idx, max_idx)
            if dc_idx is not None and dc_idx < max_idx:
                ep = adjust_xdxr(c_px, xm, c_date, dc_date, df)
                if ep > 0: trades_h.append({'return': round((dc_px-ep)/ep*100,2)})
                nx_idx, nx_px, nx_date = find_next_golden_ma1020(df, dc_idx)
                if nx_idx is None or nx_idx >= max_idx: break
                c_idx, c_px, c_date = nx_idx, nx_px, nx_date
            else:
                end_px = df.iloc[max_idx+1]['open'] if max_idx+1<len(df) else df.iloc[max_idx]['close']
                ep = adjust_xdxr(c_px, xm, c_date, str(df.index[max_idx])[:10], df)
                if ep > 0: trades_h.append({'return': round((end_px-ep)/ep*100,2)})
                break
        if trades_h:
            c = 1.0
            for t in trades_h: c *= (1+t['return']/100)
            results_h.append({'code':s['code'],'date':s['date'],'return':round((c-1)*100,2),'trades':len(trades_h)})

# ── Output ──
def summarize(results, label):
    rets = [r['return'] for r in results]
    if not rets: return
    n = len(rets)
    avg = sum(rets)/n; wr = sum(1 for r in rets if r>0)/n*100
    med = sorted(rets)[n//2]
    print(f"\n  【{label}】")
    print(f"    交易: {n}笔 | 均收: {avg:+.2f}% | 胜率: {wr:.0f}% | 中位数: {med:+.2f}%")
    print(f"    最大: {max(rets):+.2f}% | 最小: {min(rets):+.2f}%")
    if 'trades' in results[0]:
        avg_trades = sum(r.get('trades',0) for r in results) / n
        print(f"    平均循环次数: {avg_trades:.1f}")
    return avg, wr, med, n

def stats_by_horizon(results, label):
    """Break down by year/period"""
    by_year = defaultdict(list)
    for r in results:
        y = r['date'][:4]
        by_year[y].append(r['return'])
    
    print(f"\n  {label} 年度:")
    for y in ['2023','2024','2025','2026']:
        if y not in by_year: continue
        rets = by_year[y]
        if not rets: continue
        n = len(rets); avg = sum(rets)/n
        wr = sum(1 for r in rets if r>0)/n*100
        print(f"    {y}: {n}笔 | 均{avg:+.1f}% | 胜{wr:.0f}%")


print()
print("=" * 80)
print("  RPS首次 × 神仙趋势 混合策略回测")
print("=" * 80)

summarize(results_a, "方案A: 纯RPS首次24月持有")
summarize(results_b, "方案B: RPS买入→死叉卖出(不循环)")
summarize(results_c, "方案C: RPS买入→死叉卖出→金叉再买(2年内循环)")
summarize(results_d, "方案D: 纯持+死叉且回撤>15%才卖→金叉再买")
summarize(results_e, "方案E: MACD金叉买→死叉卖(循环)")
summarize(results_f, "方案F: 长线趋势多头持有→非多头卖出(循环)")
summarize(results_g, "方案G: 短线趋势多头持有→非多头卖出(循环)")
summarize(results_h, "方案H: MA10/MA20金叉买→死叉卖(循环)")

stats_by_horizon(results_a, "方案A")
stats_by_horizon(results_b, "方案B")
stats_by_horizon(results_c, "方案C")

# Comparison table
print(f"\n  {'─'*80}")
print(f"  【三方案对比】")
if results_a and results_b and results_c:
    ra = [r['return'] for r in results_a]
    rb = [r['return'] for r in results_b]
    rc = [r['return'] for r in results_c]
    rd = [r['return'] for r in results_d]
    re_data = [r['return'] for r in results_e]
    rf = [r['return'] for r in results_f]
    rg = [r['return'] for r in results_g]
    
    print(f"  {'指标':<10} {'A纯持':>9} {'B单次':>9} {'C-EMA':>9} {'D深回撤':>9} {'E-MACD':>9} {'F长趋':>9} {'G短趋':>9}")
    print(f"  {'─'*72}")
    
    for label, vals in [('均收', [sum(ra)/len(ra), sum(rb)/len(rb), sum(rc)/len(rc), sum(rd)/len(rd), sum(re_data)/len(re_data), sum(rf)/len(rf), sum(rg)/len(rg)]),
                         ('胜率', [sum(1 for r in ra if r>0)/len(ra)*100, sum(1 for r in rb if r>0)/len(rb)*100, sum(1 for r in rc if r>0)/len(rc)*100, sum(1 for r in rd if r>0)/len(rd)*100, sum(1 for r in re_data if r>0)/len(re_data)*100, sum(1 for r in rf if r>0)/len(rf)*100, sum(1 for r in rg if r>0)/len(rg)*100]),
                         ('中位数', [sorted(ra)[len(ra)//2], sorted(rb)[len(rb)//2], sorted(rc)[len(rc)//2], sorted(rd)[len(rd)//2], sorted(re_data)[len(re_data)//2], sorted(rf)[len(rf)//2], sorted(rg)[len(rg)//2]]),
                         ('最大', [max(ra), max(rb), max(rc), max(rd), max(re_data), max(rf), max(rg)]),
                         ('最小', [min(ra), min(rb), min(rc), min(rd), min(re_data), min(rf), min(rg)])]:
        print(f"  {label:<10}", end="")
        for v in vals:
            if '率' in label: print(f" {v:>8.0f}%", end="")
            else: print(f" {v:>+8.2f}%", end="")
        print()
    
    avg_trades_c = sum(r.get('trades',0) for r in results_c)/len(results_c)
    avg_trades_d = sum(r.get('trades',0) for r in results_d)/len(results_d)
    avg_trades_e = sum(r.get('trades',0) for r in results_e)/len(results_e)
    avg_trades_f = sum(r.get('trades',0) for r in results_f)/len(results_f)
    avg_trades_g = sum(r.get('trades',0) for r in results_g)/len(results_g)
    print(f"  {'循环次数':<10} {'':>9} {'':>9} {avg_trades_c:>8.1f}次 {avg_trades_d:>8.1f}次 {avg_trades_e:>8.1f}次 {avg_trades_f:>8.1f}次 {avg_trades_g:>8.1f}次")
