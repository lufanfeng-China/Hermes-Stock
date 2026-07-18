"""Competitive edge analysis via DeepSeek API + local context."""
import json, os, yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "derived" / "cache" / "competitive_edge"
_STALE_DAYS = 180
_CACHE: dict[str, dict] = {}


def get_stock_competitive_edge(market: str, symbol: str, stock_name: str = "", auto_search: bool = False) -> dict:
    cached = _load_cache(market, symbol)
    now = datetime.now(timezone.utc)
    is_stale = False
    if cached:
        try:
            refreshed = datetime.fromisoformat(cached.get("refreshed_at", ""))
            is_stale = (now - refreshed) >= timedelta(days=_STALE_DAYS)
        except (ValueError, TypeError):
            is_stale = True
    if not cached or (auto_search and is_stale):
        if stock_name:
            text = _generate_via_api(market, symbol, stock_name)
            if text:
                return save_competitive_edge(market, symbol, text, stock_name)
    if not cached:
        return {"market": market, "symbol": symbol, "stock_name": stock_name, "text": "", "refreshed_at": "", "stale": False}
    return {**cached, "stale": is_stale}


def save_competitive_edge(market: str, symbol: str, text: str, stock_name: str = "") -> dict:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"market": market, "symbol": symbol, "stock_name": stock_name,
            "text": text, "refreshed_at": datetime.now(timezone.utc).isoformat()}
    key = f"{market}:{symbol}"
    _CACHE[key] = data
    with open(_CACHE_DIR / f"{market}_{symbol}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _get_deepseek_client():
    """Lazy-init OpenAI client pointed at DeepSeek."""
    cfg_path = Path(os.path.expanduser("~/.hermes/config.yaml"))
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    api_key = model_cfg.get("api_key", "")
    base_url = model_cfg.get("base_url", "https://api.deepseek.com/v1")
    model = model_cfg.get("default", "deepseek-v4-pro")

    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url), model


def _generate_via_api(market: str, symbol: str, stock_name: str) -> str:
    try:
        client, model = _get_deepseek_client()
        context = _build_context(market, symbol, stock_name)
        prompt = (
            f"你是一名A股投资分析师。请基于数据和你的知识，分析{stock_name}（{market}:{symbol}）的竞争优势（护城河），"
            f"输出一个约150-250字中文自然段落。\n\n{context}\n\n"
            f"覆盖品牌/技术/规模/成本/网络效应/特许经营等维度，说明行业定位（龙头/跟随者/利基），"
            f"判断护城河可持续性。数据不足可用行业常识但标注[推测]。"
            f"\n\n最后单独一行输出标签，格式如下（严格按此格式，不加其他文字）："
            f"\n[标签: 细分龙头, 领域: XXX] 或 [标签: 非龙头]"
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1200,
            timeout=60,
        )
        text = resp.choices[0].message.content
        return text.strip() if text else ""
    except Exception:
        return ""


def _build_context(market: str, symbol: str, stock_name: str) -> str:
    parts = [f"股票: {stock_name} ({market}:{symbol})"]
    try:
        import importlib
        si = importlib.import_module("app.search.index")
        rows = si.load_security_rows()
        for r in rows:
            if r.get("market") == market and r.get("symbol") == symbol:
                l2 = str(r.get("industry_level_2_name", "")).strip()
                l1 = str(r.get("industry_level_1_name", "")).strip()
                if l2:
                    parts.append(f"行业: {l1}/{l2}" if l1 else f"行业: {l2}")
                mcap = r.get("total_market_cap")
                if mcap:
                    try:
                        parts.append(f"总市值: {int(float(mcap)/1e8)}亿")
                    except (TypeError, ValueError):
                        pass
                break
    except Exception:
        pass
    try:
        import importlib
        si = importlib.import_module("app.search.index")
        snapshot = si._load_financial_snapshot()
        if snapshot and isinstance(snapshot, dict):
            scores = snapshot.get("scores", {})
            key = f"{market}:{symbol}"
            row = scores.get(key, {}) if isinstance(scores, dict) else {}
            if row and isinstance(row, dict):
                score_parts = []
                for f, label in [("composite_score", "综合"), ("absolute_score", "绝对"), ("trend_score", "趋势")]:
                    v = row.get(f)
                    if v is not None:
                        score_parts.append(f"{label}={float(v):.1f}")
                if score_parts:
                    parts.append("评分: " + ", ".join(score_parts))
    except Exception:
        pass
    return "\n".join(parts)


def _load_cache(market: str, symbol: str) -> dict | None:
    key = f"{market}:{symbol}"
    if key in _CACHE:
        return _CACHE[key]
    path = _CACHE_DIR / f"{market}_{symbol}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _CACHE[key] = data
        return data
    except Exception:
        return None
