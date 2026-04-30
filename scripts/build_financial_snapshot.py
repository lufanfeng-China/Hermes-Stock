#!/usr/bin/env python3
"""
Build a full-market financial snapshot for a given report date.
Loads all stocks from the latest gpcw*.dat file, computes sub-indicator
raw values, then for each indicator computes industry-relative percentile
scores (申万二级行业), dimension scores, and total score.

Output: data/derived/datasets/final/financial_snapshot_{date}.json
"""
import json, sys, time
from pathlib import Path
from functools import lru_cache

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.search.index import (
    _FR, _TDX_DIR, _Path,
    _all_financial_files, _load_file,
    _derive_sub_fields, _industry_percentile,
    _SUB_DEFS, _SUB_KEYS,
    _load_industry_map,
)


# ── percentile computation (duplicated from index.py to keep snapshot logic self-contained) ──


def _percentile(raw_values, higher_better, zero_penalty):
    valid = {k: v for k, v in raw_values.items() if v is not None and v == v}
    if not valid:
        return {k: 0.0 for k in raw_values}
    if zero_penalty:
        if higher_better:
            penalized = {k: None if v <= 0 else v for k, v in valid.items()}
        else:
            penalized = valid
        valid = {k: v for k, v in penalized.items() if v is not None}
        if not valid:
            return {k: 0.0 for k in raw_values}
    ascending = not higher_better
    sorted_keys = sorted(valid, key=lambda k: float(valid[k]), reverse=(not ascending))
    universe_size = len(sorted_keys)
    result = {}
    for rank_idx, k in enumerate(sorted_keys):
        pct = ((universe_size - rank_idx) / universe_size) * 100.0
        result[k] = round(pct, 4)
    return result


def _score_industry_group(raw_by_indicator, stocks_with_keys):
    scores = {}
    for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
        pct_map = _percentile(raw_by_indicator[sub_key], higher_better, zero_penalty)
        for key in stocks_with_keys:
            scores.setdefault(key, {})[sub_key] = pct_map.get(key, 0.0)
    return scores


DIM_WEIGHTS = {
    "profitability": 0.25,
    "growth": 0.20,
    "operating": 0.15,
    "cashflow": 0.20,
    "solvency": 0.10,
    "asset_quality": 0.10,
}


def build_snapshot(date_str=None, output_dir=None):
    # Find latest valid file
    all_files = _all_financial_files()
    if not all_files:
        print("No financial .dat files found")
        return None

    # Load the file — skip empty ones
    fp = None
    for ds, fpath in all_files:
        result = _load_file(fpath)
        if result is not None:
            date_str = ds
            fp = fpath
            _, df = result
            print(f"Loaded {len(df)} stocks from {date_str}")
            break
    if fp is None:
        print("No valid financial .dat files found")
        return None

    # Build index: code → (market, symbol)
    # A-share classification: 6xxxxx=sh, 00xxxx/30xxxx=sz, 92xxxx=bj
    market_symbol_by_code = {}
    for idx in df.index:
        s = str(idx)
        if s.startswith("6"):
            market_symbol_by_code[s] = ("sh", s)
        elif s.startswith("92"):
            market_symbol_by_code[s] = ("bj", s)
        else:
            market_symbol_by_code[s] = ("sz", s)

    # Load industry map
    ind_map = _load_industry_map()

    # Derive sub fields for every stock
    stock_raw = {}  # key: (market, symbol) → {sub_key: raw_value}
    stock_meta = {}  # key → {industry, report_date}
    no_industry = []

    for idx in df.index:
        s = str(idx)
        if s in market_symbol_by_code:
            market, symbol = market_symbol_by_code[s]
        else:
            market = "sz" if not s.startswith("6") else "sh"
            symbol = s
        key = (market, symbol)
        frow = df.loc[s]
        fields = _derive_sub_fields(frow, None)
        stock_raw[key] = fields
        ind2, ind1 = ind_map.get(key, ("", ""))
        stock_meta[key] = {"ind2": ind2, "ind1": ind1}
        if not ind2:
            no_industry.append(key)

    print(f"Derived fields for {len(stock_raw)} stocks, {len(no_industry)} without industry")

    # Group by 申万二级 industry
    industry_groups = {}
    for key in stock_raw:
        ind2 = stock_meta[key]["ind2"]
        if ind2:
            industry_groups.setdefault(ind2, []).append(key)
        else:
            industry_groups.setdefault("__no_industry__", []).append(key)

    # Compute percentiles per industry group
    stock_scores = {}
    for ind2, keys in industry_groups.items():
        raw_by_indicator = {k: {} for k in _SUB_KEYS}
        for key in keys:
            fields = stock_raw[key]
            for sub_key in _SUB_KEYS:
                raw_by_indicator[sub_key][key] = fields.get(sub_key)
        grp_scores = _score_industry_group(raw_by_indicator, keys)
        stock_scores.update(grp_scores)

    # Compute weighted dimension scores and total score
    final_scores = {}
    for key, sub_scores in stock_scores.items():
        dim_scores = {}
        for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
            dim_scores.setdefault(dim, []).append(sub_scores.get(sub_key, 0.0))
        weighted = {}
        for dim, vals in dim_scores.items():
            avg = sum(vals) / len(vals) if vals else 0.0
            weighted[dim] = avg * DIM_WEIGHTS.get(dim, 0.0)
        total = round(sum(weighted.values()), 2)
        final_scores[key] = {
            "stock_name": stock_meta[key].get("name", ""),
            "industry_sw_level_2": stock_meta[key]["ind2"],
            "industry_sw_level_1": stock_meta[key]["ind1"],
            "report_date": date_str,
            "sub_indicators": sub_scores,
            "dim_scores": {k: round(v, 2) for k, v in weighted.items()},
            "total_score": total,
        }

    # Save snapshot
    if output_dir is None:
        output_dir = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"financial_snapshot_{date_str}.json"
    snapshot = {
        "report_date": date_str,
        "stock_count": len(final_scores),
        "industry_count": len(industry_groups),
        "scores": {f"{m}:{s}": v for (m, s), v in final_scores.items()},
    }
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Snapshot saved to {out_path}")
    print(f"  stocks: {len(final_scores)}, industries: {len(industry_groups)}")
    return out_path


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    t0 = time.time()
    p = build_snapshot(date_str)
    print(f"Done in {time.time()-t0:.1f}s")
