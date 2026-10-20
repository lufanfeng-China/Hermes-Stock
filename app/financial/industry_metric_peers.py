"""Fast read-only secondary-industry peer metrics from published snapshots."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.financial.industry_metric_snapshot import DERIVED_CHANGE_METRICS, POINT_IN_TIME_METRICS, SUPPORTED_METRICS

ROOT = Path(__file__).resolve().parents[2]
CURRENT_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "dataset_industry_metric_peers_current.json"
# Temporary compatibility source while the independent peer snapshot publication is
# rolled out.  It is read-only and never causes reports to be materialized at request time.
SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "strict_financial_health_snapshot_2025A__2026Q2.json"

METRIC_METADATA = {
    "revenue": ("营业收入", "元", "营业收入", "%"),
    "net_profit": ("归母净利润", "元", "归母净利润", "%"),
    "ex_net_profit": ("扣非归母净利润", "元", "扣非归母净利润", "%"),
    "gross_margin": ("毛利率", "%", "毛利 ÷ 营业收入", "百分点"),
    "net_margin": ("净利率", "%", "归母净利润 ÷ 营业收入", "百分点"),
    "roe_ex": ("扣非 ROE", "%", "扣非归母净利润 ÷ 平均净资产", "百分点"),
    "debt_ratio": ("资产负债率", "%", "总负债 ÷ 总资产", "百分点"),
    "ocf": ("经营现金流", "元", "经营活动产生的现金流量净额", "%"),
    "free_cf": ("自由现金流", "元", "经营现金流 − 资本开支", "%"),
    "capex": ("资本开支", "元", "购建固定资产、无形资产和其他长期资产支付的现金", "%"),
    "goodwill": ("商誉", "元", "商誉期末余额", "%"),
    "accounts_receivable": ("应收账款", "元", "应收账款期末余额", "%"),
    "inventory": ("存货", "元", "存货期末余额", "%"),
    "cash_profit_ratio": ("现金利润比", "倍", "经营现金流 ÷ 扣非归母净利润", "%"),
    "revenue_growth": ("营收增长率", "%", "营业收入与上年同口径同比", "百分点"),
    "fcf_margin": ("FCF Margin", "%", "自由现金流 ÷ 营业收入", "百分点"),
    "capex_intensity": ("CapEx 强度", "%", "资本开支 ÷ 营业收入", "百分点"),
    "accounts_receivable_growth_gap": ("应收增速差", "百分点", "应收账款同比 − 营业收入同比", "百分点"),
    "inventory_growth_gap": ("存货增速差", "百分点", "存货同比 − 营业收入同比", "百分点"),
}


class IndustryMetricPeersError(ValueError):
    """A client-visible peer API validation error with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=4)
def _load_snapshot(path_text: str, mtime_ns: int) -> dict[str, Any]:
    with Path(path_text).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("industry metric snapshot must be a JSON object")
    return payload


def _published_snapshot_path() -> Path:
    if CURRENT_SNAPSHOT.is_file():
        return CURRENT_SNAPSHOT
    if SNAPSHOT.is_file():
        return SNAPSHOT
    raise FileNotFoundError(
        "industry metric snapshot is not published "
        f"(expected {CURRENT_SNAPSHOT.name}; compatibility fallback {SNAPSHOT.name} is also absent)"
    )


def _snapshot() -> tuple[dict[str, Any], Path]:
    path = _published_snapshot_path()
    return _load_snapshot(str(path), path.stat().st_mtime_ns), path


def _partition_path(manifest_path: Path, reference: object) -> Path:
    """Resolve a manifest-owned relative partition without escaping its directory."""
    relative = Path(str(reference or ""))
    candidate = (manifest_path.parent / relative).resolve()
    if relative.is_absolute() or manifest_path.parent.resolve() not in candidate.parents:
        raise ValueError("industry metric partition path is outside snapshot directory")
    return candidate


def _partition(snapshot: dict[str, Any], manifest_path: Path, industry_level_2: str) -> dict[str, Any] | None:
    references = snapshot.get("partitions")
    if not isinstance(references, dict):
        return None
    reference = references.get(industry_level_2)
    if not reference:
        return None
    path = _partition_path(manifest_path, reference)
    return _load_snapshot(str(path), path.stat().st_mtime_ns)


def _metric_metadata(metric: str) -> dict[str, Any]:
    label, unit, formula, growth_unit = METRIC_METADATA[metric]
    return {
        "code": metric,
        "label": label,
        "unit": unit,
        "formula": formula,
        "growth_unit": growth_unit,
        "ttm_supported": metric not in POINT_IN_TIME_METRICS | DERIVED_CHANGE_METRICS,
    }


def _snapshot_as_of(snapshot: dict[str, Any], path: Path) -> str:
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    for key in ("snapshot_as_of", "built_at", "updated_at", "as_of"):
        value = snapshot.get(key) or metadata.get(key)
        if value:
            return str(value)
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _empty_metrics() -> dict[str, None]:
    return {"annual": None, "quarter": None, "ttm": None}


def _coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"members": len(rows), "annual": 0, "quarter": 0, "ttm": 0}
    for row in rows:
        metrics = row["metrics"]
        for period in ("annual", "quarter", "ttm"):
            cell = metrics.get(period)
            if isinstance(cell, dict) and cell.get("value") is not None:
                counts[period] += 1
    return counts


def build_industry_metric_peers(market: str, symbol: str, metric: str) -> dict[str, Any]:
    """Return all secondary-industry members using only the published snapshot.

    This hot path intentionally does not import or invoke financial report loaders;
    absent cells remain explicit unavailable rows rather than triggering fallback work.
    """
    market, symbol, metric = str(market).lower().strip(), str(symbol).strip(), str(metric).strip()
    if market not in {"sh", "sz", "bj"} or not symbol.isdigit() or len(symbol) != 6:
        raise IndustryMetricPeersError("invalid_params", "market/symbol 参数不合法")
    if metric not in SUPPORTED_METRICS:
        raise IndustryMetricPeersError("unknown_metric", f"unknown industry peer metric: {metric}")

    # Fail before resolving the industry so a missing publication can never silently
    # devolve into a runtime/raw-report fallback.
    snapshot, snapshot_path = _snapshot()
    stock_to_industry = snapshot.get("stock_to_industry")
    partitioned = isinstance(stock_to_industry, dict) and isinstance(snapshot.get("partitions"), dict)
    industry_level_1 = None
    if partitioned:
        industry_level_2 = stock_to_industry.get(f"{market}:{symbol}")
    else:
        # Legacy in-memory fixtures and pre-v2 payloads retain their historic
        # compatibility behavior. Published v2 manifests never reach this
        # branch, so the hot path opens only a manifest and one partition.
        from app.search import index as search_index
        industry_map = search_index._load_industry_map()
        industry_level_2, industry_level_1 = industry_map.get((market, symbol), (None, None))
    if not industry_level_2:
        return {
            "ok": False,
            "error": {"code": "industry_classification_unavailable", "message": "未找到股票的二级行业分类"},
            "market": market,
            "symbol": symbol,
            "metric": _metric_metadata(metric),
            "rows": [],
        }

    names: dict[tuple[str, str], str] = {}
    partition = _partition(snapshot, snapshot_path, str(industry_level_2)) if partitioned else (snapshot.get("industries") or {}).get(str(industry_level_2))
    if not partitioned:
        names = search_index._stock_name_lookup()
    rows: list[dict[str, Any]] = []
    if isinstance(partition, dict):
        # The independent publication is already partitioned by secondary
        # industry.  Reading just this partition preserves its explicit
        # unavailable members and avoids remapping raw financial records.
        for member in partition.get("rows") or []:
            if not isinstance(member, dict):
                continue
            peer_market = str(member.get("market") or "").lower()
            peer_symbol = str(member.get("symbol") or "").zfill(6)
            cells = (member.get("peer_metrics") or {}).get(metric)
            rows.append({
                "market": peer_market,
                "symbol": peer_symbol,
                "stock_name": str(member.get("stock_name") or names.get((peer_market, peer_symbol), peer_symbol)),
                "is_current_stock": peer_market == market and peer_symbol == symbol,
                "metrics": cells or _empty_metrics(),
                "available": cells is not None,
                "unavailable_reason": member.get("unavailable_reason") if cells is None else None,
            })
    elif not partitioned:
        # Compatibility only for the pre-partition strict snapshot.  It remains
        # snapshot-only and is never a raw-report/realtime fallback.
        stocks = snapshot.get("stocks") or {}
        members = sorted(
            (("bj" if raw_market == "2" else raw_market), peer_symbol, raw_market)
            for (raw_market, peer_symbol), (ind2, _ind1) in industry_map.items()
            if ind2 == industry_level_2
        )
        for peer_market, peer_symbol, raw_market in members:
            record = stocks.get(f"{peer_market}:{peer_symbol}") or {}
            cells = (record.get("peer_metrics") or {}).get(metric)
            rows.append({
                "market": peer_market,
                "symbol": peer_symbol,
                "stock_name": names.get((raw_market, peer_symbol), names.get((peer_market, peer_symbol), peer_symbol)),
                "is_current_stock": peer_market == market and peer_symbol == symbol,
                "metrics": cells or _empty_metrics(),
                "available": cells is not None,
            })
    if isinstance(partition, dict):
        industry_level_1 = partition.get("industry_level_1") or industry_level_1
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "metric": _metric_metadata(metric),
        "industry_level_1": industry_level_1,
        "industry_level_2": industry_level_2,
        "snapshot_as_of": _snapshot_as_of(snapshot, snapshot_path),
        "coverage": _coverage(rows),
        "rows": rows,
    }
