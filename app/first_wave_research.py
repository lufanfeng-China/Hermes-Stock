"""Continuous no-lookahead first-wave cohort scanning and raw-price outcomes."""
from __future__ import annotations
from typing import Any
import pandas as pd
from app.first_wave_start import scan_symbol


def scan_continuous_events(bars: pd.DataFrame, *, market: str, symbol: str, stock_name: str) -> list[dict[str, Any]]:
    """Scan one full QFQ series once, testing only plausible B days and freezing each B."""
    data = bars.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(data) < 69:
        return []
    prior_high = data["high"].shift(1).rolling(30, min_periods=8).max()
    prior_close = data["close"].shift(1).rolling(30, min_periods=8).max()
    above = (data["close"] >= prior_high * 1.01) | (data["close"] >= prior_close * 1.01)
    # Test a state transition only.  Persisting above the threshold is not a new B event.
    candidates = above & ~above.shift(1, fill_value=False)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx in data.index[candidates.fillna(False)]:
        if idx < 68:
            continue
        as_of = str(pd.Timestamp(data.at[idx, "date"]).date())
        event = scan_symbol(data.iloc[:idx + 1], market=market, symbol=symbol, stock_name=stock_name, as_of_date=as_of)
        if event and event["b_date"] == as_of and as_of not in seen:
            seen.add(as_of)
            events.append(event)
    return events


def attach_raw_outcomes(events: list[dict[str, Any]], raw_by_key: dict[tuple[str, str], pd.DataFrame]) -> list[dict[str, Any]]:
    """Attach raw T+1 entry/outcomes only; incomplete horizons remain explicitly unavailable."""
    output=[]
    for original in events:
        row=dict(original); raw=raw_by_key.get((row["market"], row["symbol"]))
        result={"entry_date":None,"entry_open_raw":None,"execution_status":"raw_data_unavailable","future_window_complete_20d":False}
        for h in (5,10,20): result[f"return_{h}d_pct"]=None; result[f"max_drawdown_{h}d_pct"]=None
        if raw is None or raw.empty:
            row["outcome"]=result; output.append({**row,**result}); continue
        frame=raw.copy()
        if "date" in frame.columns: frame["date"]=pd.to_datetime(frame["date"]);frame=frame.set_index("date")
        frame=frame.sort_index()
        dates=list(frame.index); signal=pd.Timestamp(row["b_date"])
        if signal not in frame.index:
            row["outcome"]=result;output.append({**row,**result});continue
        entry_i=dates.index(signal)+1
        if entry_i>=len(frame):
            result["execution_status"]="no_next_trading_day";row["outcome"]=result;output.append({**row,**result});continue
        entry=frame.iloc[entry_i]; open_price=float(entry.get("open") or 0); volume=float(entry.get("volume") or 0)
        result.update({"entry_date":str(pd.Timestamp(dates[entry_i]).date()),"entry_open_raw":open_price})
        if open_price<=0 or volume<=0:
            result["execution_status"]="suspended_or_zero_volume"
        elif float(entry.get("high") or 0)==float(entry.get("low") or -1) and entry_i>0 and float(entry.get("close") or 0)>float(frame.iloc[entry_i-1].get("close") or 0):
            result["execution_status"]="one_word_limit_up_unbuyable"
        else:
            result["execution_status"]="tradable"
        for h in (5,10,20):
            end=entry_i+h-1
            if end>=len(frame) or result["execution_status"] != "tradable": continue
            closes=frame.iloc[entry_i:end+1]["close"].astype(float)
            result[f"return_{h}d_pct"]=round((float(closes.iloc[-1])/open_price-1)*100,4)
            result[f"max_drawdown_{h}d_pct"]=round((float(closes.min())/open_price-1)*100,4)
        result["future_window_complete_20d"] = result["return_20d_pct"] is not None
        row["outcome"]=result;output.append({**row,**result})
    return output
