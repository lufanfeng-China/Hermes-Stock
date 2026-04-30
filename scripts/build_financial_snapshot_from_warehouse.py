#!/usr/bin/env python3
"""
build_financial_snapshot_from_warehouse.py
==========================================
从 Parquet 时间序列仓库重建全市场财务评分快照。

核心逻辑（路径A — 全市场统一百分位）：
  1. 每只股票取仓库中最新已发布报告（2026Q1 / 2025A / 2025Q3）
  2. 全市场 5510 只混在一起算百分位排名（不分行业，不同比同期）
  3. 按申万二级行业分组内百分位展示，但参评范围是全市场

输出：
    data/derived/datasets/final/financial_snapshot_{period}.json

用法：
    python scripts/build_financial_snapshot_from_warehouse.py latest
    python scripts/build_financial_snapshot_from_warehouse.py --help
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TS_DIR = PROJECT_ROOT / "data/derived/financial_ts/by_quarter"
SNAPSHOT_DIR = PROJECT_ROOT / "data/derived/datasets/final"
INDUSTRY_FILE = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_industry_current.json"


# ── Sub-indicator definitions ─────────────────────────────────────────────────
_SUB_DEFS = [
    # profitability
    ("roe_ex",           "profitability", None,                                           True,  True),
    ("net_margin",       "profitability", "净利润率(非金融类指标)",                         True,  True),
    ("roe_pct",          "profitability", "净资产收益率",                                  True,  True),
    # growth (YoY)
    ("revenue_growth",   "growth",        "营业收入增长率(%)",                              True,  False),
    ("profit_growth",    "growth",        "净利润增长率(%)",                               True,  False),
    ("ex_profit_growth", "growth",        "扣非净利润同比(%)",                             True,  False),
    # operating
    ("ar_days",          "operating",     "应收帐款周转天数(非金融类指标)",                 False, True),
    ("inv_days",         "operating",     "存货周转天数(非金融类指标)",                     False, True),
    ("asset_turn",       "operating",     "总资产周转率(非金融类指标)",                    True,  True),
    # cashflow
    ("ocf_to_profit",    "cashflow",      None,                                            True,  True),
    ("ocf_to_rev",       "cashflow",      "经营活动产生的现金流量净额/营业收入",            True,  True),
    ("free_cf",          "cashflow",      None,                                            True,  True),
    # solvency
    ("debt_ratio",       "solvency",      "资产负债率(%)",                                 False, True),
    ("current_ratio",    "solvency",      "流动比率(非金融类指标)",                        True,  True),
    ("quick_ratio",      "solvency",      "速动比率(非金融类指标)",                        True,  True),
    # asset quality
    ("ar_to_asset",      "asset_quality", "应收账款",                                       False, False),
    ("inv_to_asset",     "asset_quality", "存货",                                          False, False),
    ("goodwill_ratio",   "asset_quality", "商誉",                                          False, False),
    ("impair_to_rev",    "asset_quality", "资产减值损失",                                  False, False),
]
_SUB_KEYS = [d[0] for d in _SUB_DEFS]

_DIM_WEIGHTS = {
    "profitability": 0.25,
    "growth":        0.20,
    "operating":    0.15,
    "cashflow":     0.20,
    "solvency":     0.10,
    "asset_quality": 0.10,
}


# ── Period helpers ─────────────────────────────────────────────────────────────
def period_order(s: str) -> tuple:
    """'2023A' → (2023,5), '2023Q1' → (2023,1)"""
    year = int(s[:4])
    if "A" in s:
        q = 5
    else:
        q = int(s[-1])
    return (year, q)


# ── Derive sub-fields from raw financial row ──────────────────────────────────
def derive_sub_fields(frow) -> dict:
    def vv(col):
        try:
            v = frow.get(col)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    net_profit    = vv("归属于母公司所有者的净利润")
    ex_net_prof   = vv("扣除非经常性损益后的净利润")
    revenue       = vv("营业收入")
    op_cf         = vv("经营活动产生的现金流量净额")
    total_assets  = vv("资产总计")
    equity        = vv("归属于母公司股东权益(资产负债表)")
    ar            = vv("应收账款")
    inv           = vv("存货")
    goodwill      = vv("商誉")
    impair_loss   = vv("资产减值损失")
    capex         = vv("购建固定资产、无形资产和其他长期资产支付的现金")
    op_cost       = vv("营业成本")
    op_profit_v   = vv("营业利润")

    if op_cost is None and revenue is not None and op_profit_v is not None:
        op_cost = revenue - op_profit_v

    out = {}

    # profitability
    if equity and ex_net_prof is not None and equity != 0:
        out["roe_ex"] = ex_net_prof / equity * 100.0
    else:
        out["roe_ex"] = None
    out["net_margin"]   = vv("净利润率(非金融类指标)")
    out["roe_pct"] = vv("净资产收益率")

    # growth
    out["revenue_growth"]   = vv("营业收入增长率(%)")
    out["profit_growth"]    = vv("净利润增长率(%)")
    out["ex_profit_growth"] = vv("扣非净利润同比(%)")

    # operating
    out["ar_days"]    = vv("应收帐款周转天数(非金融类指标)")
    out["inv_days"]   = vv("存货周转天数(非金融类指标)")
    out["asset_turn"] = vv("总资产周转率(非金融类指标)")

    # cashflow
    if op_cf is not None and net_profit and net_profit != 0:
        out["ocf_to_profit"] = op_cf / net_profit
    else:
        out["ocf_to_profit"] = None
    out["ocf_to_rev"] = vv("经营活动产生的现金流量净额/营业收入")
    if op_cf is not None and capex is not None:
        out["free_cf"] = op_cf - capex
    else:
        out["free_cf"] = None

    # solvency
    out["debt_ratio"]    = vv("资产负债率(%)")
    out["current_ratio"] = vv("流动比率(非金融类指标)")
    out["quick_ratio"]   = vv("速动比率(非金融类指标)")

    # asset quality
    if ar and total_assets and total_assets != 0:
        out["ar_to_asset"] = ar / total_assets * 100.0
    else:
        out["ar_to_asset"] = None
    if inv and total_assets and total_assets != 0:
        out["inv_to_asset"] = inv / total_assets * 100.0
    else:
        out["inv_to_asset"] = None
    if goodwill and total_assets and total_assets != 0:
        out["goodwill_ratio"] = goodwill / total_assets * 100.0
    else:
        out["goodwill_ratio"] = None
    if impair_loss and revenue and revenue != 0:
        out["impair_to_rev"] = impair_loss / revenue * 100.0
    else:
        out["impair_to_rev"] = None

    return out


# ── Percentile: 全市场混排 ───────────────────────────────────────────────────
def _percentile_market(raw_values: dict, higher_better: bool, zero_penalty: bool) -> dict:
    """
    全市场统一百分位。
    - raw_values: {key -> value}
    - 返回: {key -> percentile_score (0-100)}
    """
    valid = {k: v for k, v in raw_values.items()
             if v is not None and v == v}
    if not valid:
        return {k: 50.0 for k in raw_values}  # 无有效数据时给中间档分

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

    for k in raw_values:
        if k not in result:
            result[k] = 50.0  # 无数据时给中间档分
    return result


# ── Percentile: 行业内分组 ───────────────────────────────────────────────────
def _percentile_industry(industry_groups: dict, raw_by_indicator: dict) -> dict:
    """
    行业内百分位排名。

    industry_groups: {ind2 -> [key, ...]}
    raw_by_indicator: {sub_key -> {key -> raw_value}}

    Returns: {key -> {sub_key -> pct}}
    """
    result = {}
    for ind2, keys in industry_groups.items():
        if ind2 == "__no_industry__":
            # 无行业股票：跳过行业排名
            for key in keys:
                result[key] = {}
            continue

        for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
            group_raw = {k: raw_by_indicator[sub_key].get(k) for k in keys}
            pct_map = _percentile_market(group_raw, higher_better, zero_penalty)
            for key in keys:
                result.setdefault(key, {})[sub_key] = pct_map.get(key, 0.0)

    return result


# ── Industry map ─────────────────────────────────────────────────────────────
def load_industry_map() -> dict:
    if not INDUSTRY_FILE.exists():
        print(f"WARNING: industry file not found: {INDUSTRY_FILE}")
        return {}
    with open(INDUSTRY_FILE, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for r in data:
        key = (r.get("market", ""), r.get("symbol", ""))
        out[key] = (r.get("industry_level_2_name", "") or "",
                    r.get("industry_level_1_name", "") or "")
    return out


# ── Load latest data for all stocks from Parquet warehouse ───────────────────
def load_all_latest() -> tuple[dict, dict, dict, dict]:
    """
    Returns:
      stock_raw:   {key -> {sub_key -> raw_value}}
      stock_meta:  {key -> {ind2, ind1, latest_period, report_date}}
      latest_periods_dist: Counter of latest periods
    """
    period_files = sorted(
        [f for f in TS_DIR.glob("*.parquet") if f.stem != "latest"],
        key=lambda f: period_order(f.stem),
    )

    code_latest = {}  # code -> (period_str, df_row)

    for fp in reversed(period_files):  # reversed: newest first, skip older
        df = pd.read_parquet(fp)
        period = fp.stem
        order = period_order(period)
        for code, row in df.iterrows():
            code = str(code)
            if code not in code_latest:
                code_latest[code] = (period, order, row)

    # Build market:symbol key for each code
    code_to_key = {}
    for code in code_latest:
        s = code
        if s.startswith("6") or s.startswith("5"):
            market = "sh"
        elif s.startswith("92"):
            market = "bj"
        else:
            market = "sz"
        code_to_key[code] = (market, s)

    # Industry map
    ind_map = load_industry_map()

    stock_raw = {}
    stock_meta = {}
    # Pre-load all periods into memory for YoY lookups
    period_to_df = {}
    for fp in period_files:
        period_to_df[fp.stem] = pd.read_parquet(fp)

    # Determine previous period for each code
    code_prev_raw = {}  # key -> {sub_key -> prev_raw_value}
    all_periods_sorted = sorted(period_files, key=lambda f: period_order(f.stem))
    period_index = {p.stem: i for i, p in enumerate(all_periods_sorted)}

    for code, (period, order, row) in code_latest.items():
        key = code_to_key.get(code, ("sz", code))
        fields = derive_sub_fields(row)
        stock_raw[key] = fields

        # Find previous period's data for YoY
        pi = period_index.get(period)
        prev_fields = {}
        if pi is not None and pi > 0:
            prev_period = all_periods_sorted[pi - 1].stem
            prev_df = period_to_df.get(prev_period)
            if prev_df is not None and code in prev_df.index:
                prev_row = prev_df.loc[code]
                prev_fields = derive_sub_fields(prev_row)
        code_prev_raw[key] = prev_fields

        ind2, ind1 = ind_map.get(key, ("", ""))
        # 银行及非银金融类股票的若干指标无意义，置为None不参与百分位计算
        if ind1 in ("银行", "非银金融"):
            for k in ("current_ratio", "quick_ratio"):
                fields[k] = None
        if ind1 in ("银行", "非银金融"):
            for k in ("ar_days", "inv_days", "ar_to_asset", "inv_to_asset", "asset_turn"):
                fields[k] = None
        announce_ts = row.get("announce_date")
        announce_val = int(announce_ts) if (announce_ts and not pd.isna(announce_ts)) else 0
        stock_meta[key] = {
            "ind2": ind2,
            "ind1": ind1,
            "latest_period": period,
            "report_date": int(row.get("report_date", 0)) if not pd.isna(row.get("report_date")) else 0,
            "announce_date": announce_val,
        }

    from collections import Counter
    latest_dist = Counter(v[0] for v in code_latest.values())

    return stock_raw, stock_meta, latest_dist, code_prev_raw


# ── Available periods ─────────────────────────────────────────────────────────
def available_periods() -> list[str]:
    if not TS_DIR.exists():
        return []
    return sorted(
        [p.stem for p in TS_DIR.glob("*.parquet") if p.stem != "latest"],
        key=period_order,
        reverse=True,
    )


def best_period_for(period_arg: str) -> str:
    all_periods = available_periods()
    if not all_periods:
        raise SystemExit("No quarterly Parquet files found")
    if period_arg == "latest" or period_arg is None:
        return all_periods[0]
    if period_arg in all_periods:
        return period_arg
    matches = [p for p in all_periods if p.startswith(period_arg)]
    if matches:
        return matches[0]
    raise SystemExit(f"Period '{period_arg}' not found. Available: {all_periods[:5]}")


# ── Build snapshot ─────────────────────────────────────────────────────────────
def build_snapshot(period: str = None, output_path: Path = None):
    t0 = time.time()

    print("=== 加载 Parquet 仓库最新财报数据（全市场混排）===")
    stock_raw, stock_meta, latest_dist, code_prev_raw = load_all_latest()
    print(f"总股票数: {len(stock_raw)}")
    print("最新报告期分布:")
    for p, cnt in sorted(latest_dist.items(), key=lambda x: period_order(x[0]), reverse=True):
        print(f"  {p}: {cnt} 只")

    # Group by industry (for display context only — percentiles are market-wide)
    industry_groups = {}
    no_industry = []
    for key in stock_raw:
        ind2 = stock_meta[key]["ind2"]
        if ind2:
            industry_groups.setdefault(ind2, []).append(key)
        else:
            industry_groups.setdefault("__no_industry__", []).append(key)

    print(f"\n行业分组: {len(industry_groups)} 个")

    # ── 全市场统一百分位 ───────────────────────────────────────────────────
    # Build per-indicator raw dict across ALL stocks
    raw_by_indicator = {k: {} for k in _SUB_KEYS}
    for key, fields in stock_raw.items():
        for sub_key in _SUB_KEYS:
            raw_by_indicator[sub_key][key] = fields.get(sub_key)

    # Compute market-wide percentiles for each sub-indicator
    sub_pct_market = {}  # key -> {sub_key -> pct}
    for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
        pct_map = _percentile_market(
            raw_by_indicator[sub_key], higher_better, zero_penalty
        )
        for key in stock_raw:
            sub_pct_market.setdefault(key, {})[sub_key] = pct_map.get(key, 0.0)

    # ── 行业分组百分位 ────────────────────────────────────────────────────
    sub_pct_industry = _percentile_industry(industry_groups, raw_by_indicator)

    # ── 维度加权（两份） ──────────────────────────────────────────────────
    def _compute_dims(sub_pct):
        out = {}
        for key, sub_scores in sub_pct.items():
            dim_scores = {}
            for sub_key, dim, *_rest in _SUB_DEFS:
                dim_scores.setdefault(dim, []).append(sub_scores.get(sub_key, 0.0))
            weighted = {}
            for dim, vals in dim_scores.items():
                avg = sum(vals) / len(vals) if vals else 0.0
                weighted[dim] = round(avg * _DIM_WEIGHTS.get(dim, 0.0), 2)
            total = round(sum(weighted.values()), 2)
            out[key] = (weighted, total)
        return out

    market_dims = _compute_dims(sub_pct_market)
    industry_dims = _compute_dims(sub_pct_industry)

    final_scores = {}
    for key in stock_raw:
        meta = stock_meta.get(key, {})
        m_weighted, m_total = market_dims.get(key, ({}, 0.0))
        i_weighted, i_total = industry_dims.get(key, ({}, 0.0))
        # 原始（未百分位换算）指标值
        raw_fields = stock_raw.get(key, {})
        # 上一期同指标原始值（用于计算同比）
        prev_fields = code_prev_raw.get(key, {})
        # 同行代码（market:symbol）→ announce_date
        key_str = f"{key[0]}:{key[1]}"
        announce_val = meta.get("announce_date", 0)
        announce_str = str(announce_val) if announce_val else ""
        final_scores[key] = {
            "industry_sw_level_2": meta.get("ind2", ""),
            "industry_sw_level_1": meta.get("ind1", ""),
            "latest_period": meta.get("latest_period", ""),
            "report_date": str(meta.get("report_date", "")),
            "announce_date": announce_str,
            # 全市场排名
            "sub_indicators": sub_pct_market.get(key, {}),
            "dim_scores": m_weighted,
            "total_score": m_total,
            # 行业排名
            "ind_sub_indicators": sub_pct_industry.get(key, {}),
            "ind_dim_scores": i_weighted,
            "ind_total_score": i_total,
            # 原始指标值（供前端展示）
            "raw_sub_indicators": {k: v for k, v in raw_fields.items() if v is not None},
            # 上一期原始指标值（供同比计算）
            "prev_raw_sub_indicators": {k: v for k, v in prev_fields.items() if v is not None},
        }

    # ── 保存 ────────────────────────────────────────────────────────────────
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        output_path = SNAPSHOT_DIR / f"financial_snapshot_{period or 'full'}.json"

    snapshot = {
        "report_date": period or "full",
        "stock_count": len(final_scores),
        "industry_count": len(industry_groups),
        "scores": {f"{m}:{s}": v for (m, s), v in final_scores.items()},
    }

    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    elapsed = time.time() - t0
    print(f"\n快照已保存 → {output_path}")
    print(f"  股票: {len(final_scores)}, 行业: {len(industry_groups)}")
    print(f"  耗时: {elapsed:.1f}s")
    return output_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "period",
        nargs="?",
        default="latest",
        help="快照标识，如 latest, 2025A (default: latest)，实际不影响计算（全市场混排）",
    )
    ap.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="输出文件路径 (default: final/financial_snapshot_{period}.json)",
    )
    args = ap.parse_args()

    period = best_period_for(args.period)
    print(f"快照标识: {period} （全市场统一百分位，不分区次）")
    build_snapshot(period, args.output)
