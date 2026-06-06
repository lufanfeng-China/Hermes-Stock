"""Industry template tags and valuation percentile."""
import json
import importlib

from app.relative_valuation.service import build_relative_valuation_result

def _industry_template_tags(ind1: str, ind2: str) -> set[str]:
    text = f"{ind1 or ''}/{ind2 or ''}"
    tags: set[str] = set()

    if any(token in text for token in ("保险", "非银金融", "证券", "多元金融")):
        tags.add("nonbank_finance")
    if any(token in text for token in ("银行", "全国性银行", "地方性银行")):
        tags.add("bank")
    if any(token in text for token in ("工业金属", "有色", "钢铁", "建材", "化工", "石油", "煤炭")):
        tags.add("materials_resources")
    if any(token in text for token in ("工业金属", "有色")):
        tags.add("industrial_metal")
    if any(token in text for token in ("食品饮料", "酿酒", "商贸", "轻工制造", "家电", "纺织服饰", "社会服务", "消费")):
        tags.add("consumer")
    if any(token in text for token in ("医药医疗", "医药生物", "化学制药", "中药", "生物制品", "医疗服务", "医疗器械")):
        tags.add("pharma")
    if any(token in text for token in ("电子", "半导体", "计算机", "通信", "传媒")):
        tags.add("tech_media")
    if any(token in text for token in ("半导体", "消费电子")):
        tags.add("semiconductor")
    if any(token in text for token in ("机械设备", "工程机械", "通用设备", "专用设备", "电力设备", "汽车", "国防军工", "建筑", "交通运输")):
        tags.add("cyclical_manufacturing")
    if any(token in text for token in ("公用事业", "环保")):
        tags.add("utilities_env")
    if any(token in text for token in ("农林牧渔", "养殖业", "种植业")):
        tags.add("agriculture")
    if any(token in text for token in ("房地产", "房地产开发", "房产服务")):
        tags.add("real_estate")
    if any(token in text for token in ("综合", "综合类")):
        tags.add("composite")
    return tags


def _build_industry_valuation_percentile_payload(market: str, symbol: str) -> dict[str, object]:
    from app.search.index import _load_financial_snapshot, _stock_name_lookup
    from app.relative_valuation import data_loader as valuation_data_loader
    from app.relative_valuation.labels import classify_percentile_band
    from app.relative_valuation.percentiles import compute_empirical_percentile

    snap = _load_financial_snapshot()
    score_entry = snap.get("scores", {}).get(f"{market}:{symbol}") if snap else {}
    industry_level_2_name = str(score_entry.get("industry_sw_level_2") or "")
    industry_level_1_name = str(score_entry.get("industry_sw_level_1") or "")
    if not industry_level_2_name:
        return {"ok": False, "error": "industry_not_found"}

    stock_name = _stock_name_lookup().get((market, symbol), symbol)
    industry_snapshot = valuation_data_loader.load_industry_valuation_snapshot(industry_level_2_name) or {}
    sample_status = str(industry_snapshot.get("sample_status") or "insufficient")
    members = industry_snapshot.get("member_valuation_rows") or []
    if not members:
        live_members = []
        for member in valuation_data_loader._industry_members(industry_level_2_name):
            row_market = str(member.get("market") or "").strip().lower()
            row_symbol = str(member.get("symbol") or "").strip()
            if not row_market or not row_symbol:
                continue
            stock_inputs = valuation_data_loader.load_stock_relative_valuation_inputs(row_market, row_symbol)
            if not stock_inputs:
                continue
            live_members.append({
                "market": row_market,
                "symbol": row_symbol,
                "stock_name": stock_inputs.get("stock_name") or member.get("stock_name") or row_symbol,
                "current_price": stock_inputs.get("current_price"),
                "total_market_cap": stock_inputs.get("total_market_cap"),
                "free_float_market_cap": stock_inputs.get("free_float_market_cap"),
                "pe_ttm": stock_inputs.get("pe_ttm"),
                "ps_ttm": stock_inputs.get("ps_ttm"),
            })
        members = live_members
    current_stock_member = next(
        (m for m in members if isinstance(m, dict) and m.get("market", "").strip().lower() == market and m.get("symbol", "").strip() == symbol),
        None,
    )

    def positive_float(raw_value):
        value = valuation_data_loader._to_float(raw_value)
        if value is None or value <= 0:
            return None
        return value

    pe_ttm = positive_float(current_stock_member.get("pe_ttm")) if current_stock_member else None
    ps_ttm = positive_float(current_stock_member.get("ps_ttm")) if current_stock_member else None

    relative_payload = build_relative_valuation_result(market, symbol)
    if relative_payload.get("ok"):
        stock_name = str(relative_payload.get("stock_name") or stock_name)
        classification = str(relative_payload.get("classification") or "A_NORMAL_EARNING")
        sub_classification = relative_payload.get("sub_classification")
        primary_metric = str(
            relative_payload.get("primary_percentile_metric")
            or relative_payload.get("primary_metric")
            or "pe_ttm"
        )
        if primary_metric not in {"pe_ttm", "ps_ttm"}:
            primary_metric = "pe_ttm"
        primary_value = valuation_data_loader._to_float(relative_payload.get("primary_percentile_value"))
        if primary_value is not None and primary_value <= 0:
            primary_value = None
        primary_percentile = valuation_data_loader._to_float(relative_payload.get("primary_percentile"))
        valuation_band_label = relative_payload.get("valuation_band_label")
    else:
        classification = "A_NORMAL_EARNING" if pe_ttm is not None else "B_THIN_PROFIT_DISTORTED"
        sub_classification = None
        primary_metric = "pe_ttm" if pe_ttm is not None else "ps_ttm"
        primary_value = pe_ttm if primary_metric == "pe_ttm" else ps_ttm
        primary_percentile = None
        valuation_band_label = None

    if sample_status == "ok" and primary_value is not None:
        sample = valuation_data_loader.load_industry_percentile_sample(
            industry_level_2_name,
            primary_metric,
            classification,
            str(sub_classification) if sub_classification else None,
        ) or []
    else:
        sample = []
    if primary_percentile is None and primary_value is not None and sample:
        primary_percentile = compute_empirical_percentile(primary_value, sample)
    if valuation_band_label is None:
        valuation_band_label = classify_percentile_band(primary_percentile) if primary_percentile is not None else None

    member_rows: list[dict[str, object]] = []
    for vr in members:
        if not isinstance(vr, dict):
            continue
        row_market = str(vr.get("market") or "").strip().lower()
        row_symbol = str(vr.get("symbol") or "").strip()
        if not row_market or not row_symbol:
            continue
        row_pe_ttm = positive_float(vr.get("pe_ttm"))
        row_ps_ttm = positive_float(vr.get("ps_ttm"))
        row_value = row_pe_ttm if primary_metric == "pe_ttm" else row_ps_ttm
        row_percentile = compute_empirical_percentile(row_value, sample) if row_value is not None and sample else None
        row_band = classify_percentile_band(row_percentile) if row_percentile is not None else "估值不可比"
        member_rows.append({
            "stock_name": vr.get("stock_name") or vr.get("symbol") or row_symbol,
            "market": row_market,
            "symbol": row_symbol,
            "current_price": valuation_data_loader._to_float(vr.get("current_price")),
            "ps_ttm": row_ps_ttm,
            "pe_ttm": row_pe_ttm,
            "valuation_metric": primary_metric,
            "valuation_percentile": row_percentile,
            "_percentile_rank": row_percentile,
            "valuation_band": row_band,
            "_band_label": row_band,
            "is_current_stock": row_market == market and row_symbol == symbol,
        })

    member_rows.sort(key=lambda r: (r["valuation_percentile"] is None, r["valuation_percentile"] or 0))
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "industry_level_2_name": industry_level_2_name,
        "industry_level_1_name": industry_level_1_name,
        "classification": classification,
        "sample_status": sample_status,
        "primary_metric": primary_metric,
        "primary_percentile_metric": primary_metric,
        "primary_percentile_value": primary_value,
        "primary_percentile": primary_percentile,
        "valuation_band_label": valuation_band_label,
        "rows": member_rows,
    }


