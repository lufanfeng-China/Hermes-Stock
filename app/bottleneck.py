"""
瓶颈股发现模块 — Serenity 紫苏叶理论
==================================

提供 7 步研究流程的 API：
  step1 - 选择超级趋势
  step2 - 拆解产业链
  step3 - 识别瓶颈层
  step4 - 映射 A 股标的
  step5 - 系统数据验证（财务评分+技术面+RPS）
  step6 - Serenity 交叉验证（反方论证）
  step7 - 输出最终报告

支持：
  - 逐步执行模式（每步独立 API）
  - 一键全自动模式
  - 报告保存 / 查看历史 / 重新运行
"""

import json
import os
import time
import threading
import traceback
import urllib.parse
from datetime import datetime

# ── 数据路径 ──────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SUPPLY_CHAINS_PATH = os.path.join(DATA_DIR, "supply_chains.json")
REPORTS_DIR = os.path.join(DATA_DIR, "bottleneck_reports")

# ── 后台 AI 拆解任务状态 ──────────────────────────────────

_ai_jobs: dict[str, dict] = {}  # session_id -> {status, result, error}
_ai_jobs_lock = threading.Lock()


def _run_ai_decompose_bg(session_id: str, description: str) -> None:
    """后台线程：调用 hermes 拆解产业链。"""
    try:
        result = _ai_decompose_chain(description)
        with _ai_jobs_lock:
            _ai_jobs[session_id] = {"status": "done", "result": result}
    except Exception as e:
        with _ai_jobs_lock:
            _ai_jobs[session_id] = {"status": "error", "error": str(e)}


def _load_supply_chains():
    """加载预置产业链数据"""
    with open(SUPPLY_CHAINS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _list_all_stocks_in_layer(layer, max_display=15):
    """
    如果候选数 ≤ max_display，返回全部；
    超过则返回总数 + 部分预览。
    """
    candidates = layer.get("a_share_candidates", [])
    if len(candidates) <= max_display:
        return {
            "show_all": True,
            "total": len(candidates),
            "stocks": candidates,
        }
    else:
        return {
            "show_all": False,
            "total": len(candidates),
            "preview": candidates[:10],
            "remaining": len(candidates) - 10,
        }


# ── 步骤 1: 选择趋势 ─────────────────────────────────────

def step1_select_trend(trend_id=None):
    """
    返回可选趋势列表或指定趋势的详情。
    trend_id=None → 列出所有趋势
    trend_id=指定 → 返回趋势详情 + 产业链预览
    """
    data = _load_supply_chains()
    trends = data.get("trends", {})

    if trend_id is None:
        # 列出所有趋势
        trend_list = []
        for tid, t in trends.items():
            trend_list.append({
                "id": tid,
                "name": t["name"],
                "description": t["description"],
                "anchor": t.get("anchor", ""),
                "layer_count": len(t.get("layers", [])),
            })
        return {"ok": True, "type": "list", "trends": trend_list}

    # 返回指定趋势详情
    trend = trends.get(trend_id)
    if not trend:
        return {"ok": False, "error": f"未知趋势: {trend_id}", "available": list(trends.keys())}

    return {
        "ok": True,
        "type": "detail",
        "trend": {
            "id": trend_id,
            "name": trend["name"],
            "description": trend["description"],
            "anchor": trend.get("anchor", ""),
            "layer_count": len(trend.get("layers", [])),
        },
    }


# ── 步骤 2: 拆解产业链 ─────────────────────────────────────

def _ai_decompose_chain(custom_description: str) -> dict:
    """
    使用 AI 实时拆解自定义趋势的产业链。
    """
    import subprocess

    prompt = f"""分析「{custom_description}」的产业链，用中文逐层拆解 5-7 层。

每层格式：层级名称 | 作用 | 全球主要玩家（公司名） | 国内主要玩家（公司名或A股代码） | 供应商数量

最后标注哪些层供应商 ≤2家（瓶颈层）。只输出层级列表。"""

    cmd = [
        "hermes", "chat", "-Q", "--ignore-rules", "--source", "tool",
        "-q", prompt,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "hermes command failed")
    raw = result.stdout.strip()
    if not raw or len(raw) <= 20:
        raise RuntimeError("hermes returned empty or too-short response")
    return _parse_text_to_chain(raw, custom_description)


def _search_web(query: str) -> list[dict]:
    """用 DuckDuckGo 搜索产业链相关文章。"""
    import urllib.request
    import urllib.parse
    import re

    search_q = f"{query} 产业链 供应商 上市公司"
    encoded = urllib.parse.quote(search_q)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    # 提取搜索结果：标题 + 链接
    results = []
    for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
        href = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        # 解码 DuckDuckGo 重定向 URL
        if "uddg=" in href:
            decoded = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
            results.append({"title": title, "url": decoded})
        if len(results) >= 8:
            break
    return results


def _fetch_top_articles(results: list[dict], max_articles: int = 2) -> list[str]:
    """抓取搜索排名前几篇文章的正文。"""
    import urllib.request
    import re

    texts = []
    for r in results[:max_articles]:
        try:
            req = urllib.request.Request(
                r["url"],
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # 简单提取文本
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 200:
                texts.append(f"[来源：{r['title']}]\n{text[:3000]}")
        except Exception:
            continue

    return texts


def _parse_text_to_chain(text: str, trend_name: str) -> dict:
    """将 AI 文本输出解析为产业链 JSON。"""
    lines = [l.strip() for l in text.split("\n") if l.strip() and ("|" in l or "：" in l or ":" in l or "层" in l)]
    layers = []
    for i, line in enumerate(lines[:8]):
        # 尝试用 | 分割
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            parts = [p.strip() for p in line.replace("：", "|").replace(":", "|").split("|")]
        name = parts[0] if len(parts) > 0 else f"第{i}层"
        role = parts[1] if len(parts) > 1 else ""
        global_p = [p.strip() for p in parts[2].split("、")] if len(parts) > 2 and parts[2] else []
        domestic_p = [p.strip() for p in parts[3].split("、")] if len(parts) > 3 and parts[3] else []

        # 检测瓶颈关键词
        bottleneck_keywords = ["供应商", "≤2", "两家", "一家", "垄断", "寡头", "唯一", "瓶颈", "卡脖子"]
        is_bn = any(kw in line.lower() for kw in bottleneck_keywords)
        sc = len(global_p) if global_p else (2 if is_bn else 5)

        layers.append({
            "level": i, "name": name, "role": role,
            "description": f"{name}——{role}" if role else name,
            "global_players": global_p[:5],
            "domestic_players": domestic_p[:5],
            "supplier_count": sc,
            "is_bottleneck": is_bn or sc <= 2,
            "bottleneck_level": "🔴 核心瓶颈" if sc <= 1 else ("🟡 次要瓶颈" if sc <= 2 else ""),
            "bottleneck_score": 5 if sc <= 1 else (4 if sc <= 2 else (3 if sc <= 3 else 0)),
            "bottleneck_reason": f"全球仅{sc}家供应商" if sc <= 2 else "",
            "skip_reason": "" if sc <= 2 else f"供应商≥3家，竞争充分",
            "a_share_candidates": [],
        })

    if not layers:
        return _rule_based_decompose(trend_name)

    return {
        "trend_name": trend_name,
        "anchor": f"{trend_name}——AI自动拆解",
        "layers": layers,
    }


def _rule_based_decompose(description: str) -> dict:
    """规则引擎兜底：根据关键词匹配产业链模板。"""
    desc_lower = description.lower()
    layers = []

    # 终端需求层
    layers.append({"level": 0, "name": "终端需求", "role": "应用场景",
        "description": description, "global_players": ["多玩家"], "domestic_players": ["多玩家"],
        "supplier_count": 10, "is_bottleneck": False,
        "bottleneck_reason": "", "skip_reason": "应用层竞争充分，不构成瓶颈",
        "a_share_candidates": []})

    # 根据关键词添加中间层
    if any(kw in desc_lower for kw in ["算力", "ai", "计算", "芯片", "gpu"]):
        layers.append({"level": 1, "name": "AI芯片/算力硬件", "role": "核心计算单元",
            "description": "提供算力的GPU/NPU等芯片", "global_players": ["NVIDIA", "AMD", "Intel"],
            "domestic_players": ["华为昇腾", "寒武纪", "海光信息"],
            "supplier_count": 3, "is_bottleneck": False,
            "bottleneck_reason": "", "skip_reason": "供应商>2家",
            "a_share_candidates": ["688256", "688041"]})

    if any(kw in desc_lower for kw in ["太空", "卫星", "轨道", "空间", "航天"]):
        layers.append({"level": 2, "name": "卫星/航天平台", "role": "轨道部署载体",
            "description": "搭载AI计算节点的卫星或空间站平台",
            "global_players": ["SpaceX", "OneWeb", "Amazon Kuiper"],
            "domestic_players": ["中国卫星", "中国卫通", "银河航天"],
            "supplier_count": 3, "is_bottleneck": False,
            "bottleneck_reason": "", "skip_reason": "供应商>2家",
            "a_share_candidates": ["600118", "601698"]})

    if any(kw in desc_lower for kw in ["太空", "卫星", "轨道", "航天", "发射", "火箭"]):
        layers.append({"level": 3, "name": "发射服务/运载火箭", "role": "将载荷送入轨道",
            "description": "提供卫星发射和轨道部署服务",
            "global_players": ["SpaceX", "ULA", "Arianespace"],
            "domestic_players": ["航天科技(长征)", "蓝箭航天", "星河动力"],
            "supplier_count": 3, "is_bottleneck": False,
            "bottleneck_reason": "", "skip_reason": "供应商>2家",
            "a_share_candidates": ["600879", "603698"]})

    if any(kw in desc_lower for kw in ["算力", "ai", "计算", "芯片", "散热", "电源", "太阳能"]):
        layers.append({"level": 4, "name": "太空级电源/散热系统", "role": "极端环境供能与热管理",
            "description": "太空环境下的太阳能供电与真空散热",
            "global_players": ["Northrop Grumman", "Airbus Defence"],
            "domestic_players": ["中国空间技术研究院", "中航光电"],
            "supplier_count": 2, "is_bottleneck": True,
            "bottleneck_level": "🟡 次要瓶颈",
            "bottleneck_score": 4, "bottleneck_reason": "太空级电源和散热方案供应商极少",
            "a_share_candidates": ["002179", "600118"]})

    if any(kw in desc_lower for kw in ["卫星", "太空", "通信", "激光", "链路"]):
        layers.append({"level": 5, "name": "星间激光通信", "role": "卫星间高速数据传输",
            "description": "构建卫星间光通信网络实现低延迟数据传输",
            "global_players": ["TESAT Spacecom", "Mynaric"],
            "domestic_players": ["中国空间技术研究院", "航天电子"],
            "supplier_count": 2, "is_bottleneck": True,
            "bottleneck_level": "🔴 核心瓶颈",
            "bottleneck_score": 5, "bottleneck_reason": "星间激光通信终端全球仅2家成熟供应商",
            "a_share_candidates": ["600879"]})

    # 辐射加固芯片
    if any(kw in desc_lower for kw in ["太空", "卫星", "辐射", "抗辐射", "加固"]):
        layers.append({"level": 6, "name": "抗辐射加固芯片", "role": "太空环境下的可靠性保障",
            "description": "太空辐射环境要求芯片具备抗辐射能力，普通芯片无法使用",
            "global_players": ["BAE Systems", "Honeywell"],
            "domestic_players": ["航天科技772所", "中国电科"],
            "supplier_count": 2, "is_bottleneck": True,
            "bottleneck_level": "🔴 核心瓶颈",
            "bottleneck_score": 5, "bottleneck_reason": "抗辐射芯片全球仅2家成熟供应商，技术壁垒极高",
            "a_share_candidates": ["600879", "600118"]})

    if not layers or len(layers) < 3:
        layers.append({"level": len(layers), "name": "关键材料/零部件", "role": "上游核心材料",
            "description": "产业链上游的关键材料或零部件环节",
            "global_players": ["供应商A", "供应商B"],
            "domestic_players": ["国内供应商"],
            "supplier_count": 2, "is_bottleneck": True,
            "bottleneck_level": "🟡 次要瓶颈",
            "bottleneck_score": 4, "bottleneck_reason": "建议进一步细化趋势描述以获得更准确分析",
            "a_share_candidates": []})

    return {
        "trend_name": description,
        "anchor": f"{description}——基于规则引擎的产业链拆解",
        "layers": layers,
    }


def step2_decompose_chain(trend_id, custom_description=""):
    """
    对指定趋势返回完整产业链拆解。
    如果是预置趋势 → 从 JSON 加载
    如果是自定义 → 调用 AI 实时拆解
    """
    data = _load_supply_chains()
    trend = data.get("trends", {}).get(trend_id)

    if trend:
        # 预置趋势
        layers_output = []
        for layer in trend["layers"]:
            layers_output.append({
                "level": layer["level"],
                "name": layer["name"],
                "role": layer.get("role", ""),
                "description": layer.get("description", ""),
                "global_players": layer.get("global_players", []),
                "domestic_players": layer.get("domestic_players", []),
                "supplier_count": layer.get("supplier_count", 0),
                "is_bottleneck": layer.get("is_bottleneck", False),
                "bottleneck_level": layer.get("bottleneck_level", ""),
                "bottleneck_score": layer.get("bottleneck_score", 0),
                "bottleneck_reason": layer.get("bottleneck_reason", ""),
                "skip_reason": layer.get("skip_reason", ""),
                "a_share_candidates": layer.get("a_share_candidates", []),
            })
        return {
            "ok": True,
            "type": "preset",
            "trend_name": trend["name"],
            "trend_id": trend_id,
            "description": trend.get("description", ""),
            "anchor": trend.get("anchor", ""),
            "total_layers": len(layers_output),
            "layers": layers_output,
        }

    # 自定义趋势 → 后台 AI 拆解
    if trend_id == "__custom__" and custom_description:
        import uuid
        session_id = uuid.uuid4().hex[:12]
        with _ai_jobs_lock:
            _ai_jobs[session_id] = {"status": "processing"}
        t = threading.Thread(target=_run_ai_decompose_bg, args=(session_id, custom_description), daemon=True)
        t.start()
        return {
            "ok": True,
            "type": "custom_processing",
            "trend_id": trend_id,
            "session_id": session_id,
            "custom_description": custom_description,
            "message": "AI 正在拆解产业链，预计需要 10-30 秒...",
            "layers": [],
        }

    # 兜底：无数据
    return {
        "ok": True,
        "type": "custom",
        "trend_id": trend_id,
        "custom_description": custom_description,
        "message": "自定义趋势需要 AI 实时拆解产业链。",
        "layers": [],
    }


def check_custom_status(session_id: str) -> dict:
    """查询自定义趋势 AI 拆解的状态。"""
    with _ai_jobs_lock:
        job = _ai_jobs.get(session_id)
    if not job:
        return {"ok": False, "error": "未知的 session_id"}

    if job["status"] == "processing":
        return {"ok": True, "status": "processing"}

    if job["status"] == "error":
        return {"ok": True, "status": "error", "error": job.get("error", "")}

    # done — 标准化 layers
    ai_result = job.get("result", {})
    if "error" in ai_result:
        return {"ok": True, "status": "error", "error": ai_result["error"]}

    layers = ai_result.get("layers", [])
    norm_layers = []
    for i, l in enumerate(layers):
        sc = l.get("supplier_count", len(l.get("global_players", [])))
        is_b = l.get("is_bottleneck", sc <= 2)
        score = 5 if sc <= 1 else (4 if sc == 2 else (3 if sc == 3 else 0))
        level_tag = "🔴 核心瓶颈" if sc <= 1 else ("🟡 次要瓶颈" if sc == 2 else "")
        norm_layers.append({
            "level": l.get("level", i),
            "name": l.get("name", f"第{i}层"),
            "role": l.get("role", ""),
            "description": l.get("description", ""),
            "global_players": l.get("global_players", []),
            "domestic_players": l.get("domestic_players", []),
            "supplier_count": sc,
            "is_bottleneck": is_b,
            "bottleneck_level": l.get("bottleneck_level", level_tag),
            "bottleneck_score": l.get("bottleneck_score", score),
            "bottleneck_reason": l.get("bottleneck_reason", ""),
            "skip_reason": l.get("skip_reason", ""),
            "a_share_candidates": l.get("a_share_candidates", []),
        })

    return {
        "ok": True,
        "status": "done",
        "type": "custom_ai",
        "trend_name": ai_result.get("trend_name", ""),
        "anchor": ai_result.get("anchor", ""),
        "total_layers": len(norm_layers),
        "layers": norm_layers,
        "bottleneck_count": sum(1 for l in norm_layers if l.get("is_bottleneck")),
    }

def step3_identify_bottlenecks(trend_id):
    """
    遍历产业链，标注所有 bottleneck=true 的层。
    返回带颜色标注的产业链 + 瓶颈层高亮。
    """
    data = _load_supply_chains()
    trend = data.get("trends", {}).get(trend_id)

    if not trend:
        return {"ok": False, "error": f"未知趋势: {trend_id}"}

    bottlenecks = []
    all_layers = []

    for layer in trend["layers"]:
        info = {
            "level": layer["level"],
            "name": layer["name"],
            "supplier_count": layer.get("supplier_count", 0),
            "is_bottleneck": layer.get("is_bottleneck", False),
        }
        if layer.get("is_bottleneck"):
            info["bottleneck_level"] = layer.get("bottleneck_level", "")
            info["bottleneck_score"] = layer.get("bottleneck_score", 0)
            info["bottleneck_reason"] = layer.get("bottleneck_reason", "")
            info["skip_reason"] = layer.get("skip_reason", "")
            bottlenecks.append(info)
        else:
            info["skip_reason"] = layer.get("skip_reason", "")
        all_layers.append(info)

    # 按 bottleneck_score 排序瓶颈层
    bottlenecks.sort(key=lambda x: x.get("bottleneck_score", 0), reverse=True)

    return {
        "ok": True,
        "trend_name": trend["name"],
        "total_layers": len(all_layers),
        "bottleneck_count": len(bottlenecks),
        "all_layers": all_layers,
        "bottlenecks": bottlenecks,
        "summary": (
            f"在 {len(all_layers)} 层产业链中，识别出 {len(bottlenecks)} 个瓶颈层。"
            f"按卡脖子程度排序，前三个最关键的瓶颈是："
            + "、".join([b["name"] for b in bottlenecks[:3]])
            + "。"
        ),
    }


def _fetch_price_info(market, symbol):
    """Fetch current close + 5/20/60 day % changes from kline API."""
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:8765/api/stock-kline?market={market}&symbol={symbol}&limit=65"
    try:
        req = urllib.request.Request(url, headers={"Origin": "http://127.0.0.1:8765"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    bars = data.get("bars", [])
    if not bars or len(bars) < 5:
        return None

    last = bars[-1]
    close = last.get("close")

    def _pct(days):
        if len(bars) > days:
            prev = bars[-(days + 1)]["close"]
            if prev and prev > 0:
                return round((close / prev - 1) * 100, 1)
        return None

    return {
        "close": close,
        "change_5d": _pct(5),
        "change_20d": _pct(20),
        "change_60d": _pct(60),
    }


def _lookup_stock_name(market, symbol):
    """Lightweight stock name lookup using compute_stock_score."""
    try:
        from app.search.index import compute_stock_score
        score_data = compute_stock_score(market, symbol)
        if score_data:
            return score_data.get("stock_name", "")
    except Exception:
        pass
    return ""


# ── 步骤 4: 映射 A 股标的 ───────────────────────────────────

def step4_map_stocks(trend_id):
    """
    对每个瓶颈层，列出对应的 A 股标的。
    ≤15 家 → 全部列出（含股票名称）
    >15 家 → 列出总数 + 前 10 家
    """
    data = _load_supply_chains()
    trend = data.get("trends", {}).get(trend_id)

    if not trend:
        return {"ok": False, "error": f"未知趋势: {trend_id}"}

    mapped_layers = []
    for layer in trend["layers"]:
        if not layer.get("is_bottleneck"):
            continue
        candidates = layer.get("a_share_candidates", [])
        stock_list = _list_all_stocks_in_layer(layer)

        # 添加股票名称
        stocks_with_names = []
        for code in stock_list.get("stocks") or stock_list.get("preview", []):
            market = "sh" if code.startswith("6") else "sz"
            name = _lookup_stock_name(market, code)
            stocks_with_names.append({"code": code, "name": name})

        mapped_layers.append({
            "level": layer["level"],
            "name": layer["name"],
            "bottleneck_level": layer.get("bottleneck_level", ""),
            "bottleneck_score": layer.get("bottleneck_score", 0),
            "bottleneck_reason": layer.get("bottleneck_reason", ""),
            "show_all": stock_list["show_all"],
            "total_stocks": stock_list["total"],
            "stocks": stocks_with_names,
            "remaining": stock_list.get("remaining", 0),
        })

    return {
        "ok": True,
        "trend_name": trend["name"],
        "mapped_layers": mapped_layers,
    }


# ── 步骤 5: 系统数据验证 ───────────────────────────────────

def step5_verify_stocks(trend_id):
    """
    对候选股票调用系统 API（stock-score + technical-eval）
    返回每只股票的六维评分、RPS、趋势、估值等。
    """
    from app.search.index import compute_stock_score
    import sys
    import os

    data = _load_supply_chains()
    trend = data.get("trends", {}).get(trend_id)

    if not trend:
        return {"ok": False, "error": f"未知趋势: {trend_id}"}

    # 收集所有候选股票
    all_candidates = {}
    for layer in trend["layers"]:
        if not layer.get("is_bottleneck"):
            continue
        for code in layer.get("a_share_candidates", []):
            if code not in all_candidates:
                all_candidates[code] = {
                    "code": code,
                    "layers": [],
                }
            all_candidates[code]["layers"].append(layer["name"])

    # 对每只股票跑评分 + 价格
    verified = []
    for code, info in all_candidates.items():
        market = "sh" if code.startswith("6") else "sz"
        try:
            score_data = compute_stock_score(market, code)
            if not score_data:
                verified.append({
                    "code": code, "market": market, "name": "",
                    "layers": info["layers"],
                    "error": "未找到评分数据",
                })
                continue
        except Exception:
            verified.append({
                "code": code, "market": market, "name": "",
                "layers": info["layers"],
                "error": "评分计算异常",
            })
            continue

        # 获取价格和涨跌幅
        price_info = _fetch_price_info(market, code) or {}

        dim = score_data.get("dim_scores", {})

        # ── 概念股风险评估 ──
        raw = score_data.get("raw_sub_indicators", {})
        ind1 = score_data.get("ind1", "")
        ind2 = score_data.get("ind2", "")
        total = score_data.get("total_score", 0)
        net_margin = raw.get("net_margin", 0) or 0
        revenue_growth = raw.get("revenue_growth", 0) or 0

        risk_flags = []
        # 检查行业匹配（针对半导体/电子/光学等硬科技趋势）
        tech_keywords = ["电子", "半导体", "光学", "化工", "材料", "设备", "制造", "医药", "航天", "军工", "新能源"]
        industry_ok = any(kw in f"{ind1}{ind2}" for kw in tech_keywords)
        if not industry_ok:
            risk_flags.append(f"行业({ind1}/{ind2})与技术趋势不直接匹配")
        if net_margin < 1 and total < 55:
            risk_flags.append(f"利润率极低({net_margin:.1f}%)且评分不高")
        if revenue_growth < -10:
            risk_flags.append(f"营收严重下滑({revenue_growth:.1f}%)")
        if total < 30:
            risk_flags.append(f"总分过低({int(total)})")

        concept_risk = "none"
        if len(risk_flags) >= 2:
            concept_risk = "high"
        elif len(risk_flags) == 1:
            concept_risk = "medium"

        verified.append({
            "code": code,
            "market": market,
            "name": score_data.get("stock_name", ""),
            "layers": info["layers"],
            "total_score": score_data.get("total_score"),
            "market_rank": score_data.get("market_total_rank"),
            "market_total": score_data.get("market_total_universe_size"),
            "industry_rank": score_data.get("industry_total_rank"),
            "industry_total": score_data.get("industry_total_universe_size"),
            "ind1": score_data.get("ind1", ""),
            "ind2": score_data.get("ind2", ""),
            "close": price_info.get("close"),
            "change_5d": price_info.get("change_5d"),
            "change_20d": price_info.get("change_20d"),
            "change_60d": price_info.get("change_60d"),
            "concept_risk": concept_risk,
            "risk_flags": risk_flags,
            "dim_scores": {
                "profitability": round(dim.get("profitability", 0), 1),
                "growth": round(dim.get("growth", 0), 1),
                "operating": round(dim.get("operating", 0), 1),
                "cashflow": round(dim.get("cashflow", 0), 1),
                "solvency": round(dim.get("solvency", 0), 1),
                "asset_quality": round(dim.get("asset_quality", 0), 1),
            },
        })

    # 按总分排序
    verified.sort(key=lambda x: x.get("total_score", 0) or 0, reverse=True)

    return {
        "ok": True,
        "trend_name": trend["name"],
        "total_verified": len(verified),
        "stocks": verified,
    }


# ── 步骤 6: Serenity 交叉验证 ──────────────────────────────

def step6_cross_verify(trend_id):
    """
    对每只瓶颈股做反方论证：
    - 逻辑可能在哪些环节被推翻？
    - 需要持续跟踪的关键信号？
    - 逻辑推翻条件？
    """
    data = _load_supply_chains()
    trend = data.get("trends", {}).get(trend_id)

    if not trend:
        return {"ok": False, "error": f"未知趋势: {trend_id}"}

    cross_checks = []
    for layer in trend["layers"]:
        if not layer.get("is_bottleneck"):
            continue

        candidates = layer.get("a_share_candidates", [])
        layer_check = {
            "level": layer["level"],
            "layer_name": layer["name"],
            "bottleneck_score": layer.get("bottleneck_score", 0),
            "global_monopoly": layer.get("global_players", [])[0] if layer.get("global_players") else "",
            "domestic_leader": candidates[0] if candidates else "",
            "all_candidates": candidates,
            "key_risks": _generate_risk_checklist(layer, trend),
        }
        cross_checks.append(layer_check)

    return {
        "ok": True,
        "trend_name": trend["name"],
        "cross_checks": cross_checks,
    }


def _generate_risk_checklist(layer, trend):
    """根据瓶颈层特征生成风险检查清单"""
    risks = []

    # 通用风险
    risks.append({
        "type": "tech_substitution",
        "question": "如果出现颠覆性技术路线替代这个环节，逻辑是否还成立？",
        "trigger": "出现新的封装方案/材料替代，不再需要此环节的产品",
    })
    risks.append({
        "type": "global_competition",
        "question": f"如果全球垄断企业（{layer.get('global_players', ['未知'])[0]}）大幅扩产并降价打压，国产替代空间会缩小多少？",
        "trigger": "海外垄断企业宣布大规模扩产或主动降价",
    })

    # 根据供应商数量生成
    if layer.get("supplier_count", 0) <= 1:
        risks.append({
            "type": "domestic_newcomer",
            "question": "如果有新的国产厂商突破技术进入供应，现有国产龙头的唯一性优势是否会被削弱？",
            "trigger": "新国产厂商宣布技术突破或通过客户验证",
        })

    # 根据 bottleneck_score 生成
    if layer.get("bottleneck_score", 0) >= 5:
        risks.append({
            "type": "valuation_risk",
            "question": "当前股价是否已经充分反映了「唯一国产替代者」的溢价？安全边际有多少？",
            "trigger": "股价短期内大幅上涨，5年分位进入极高区间",
        })
        risks.append({
            "type": "capacity_bottleneck",
            "question": "国产龙头的产能是否足够承接爆发的需求？产能爬坡周期是多久？",
            "trigger": "公司季报显示产能利用率接近上限但新产能尚未投产",
        })

    # 财务风险
    risks.append({
        "type": "financial_risk",
        "question": "公司的负债率、ROE、现金流能否支撑大规模扩产？如果需求爆发但公司财务跟不上怎么办？",
        "trigger": "负债率持续上升、ROE不升反降、自由现金流恶化",
    })

    return risks


# ── 步骤 7: 一键全自动 ────────────────────────────────────

def step7_full_auto(trend_id):
    """一键执行全部 6 步 + 生成最终报告"""
    results = {
        "trend_id": trend_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "iso_timestamp": datetime.now().isoformat(),
    }

    # Step 1
    s1 = step1_select_trend(trend_id)
    if not s1["ok"]:
        return {"ok": False, "error": s1["error"]}
    results["step1"] = s1

    # Step 2
    s2 = step2_decompose_chain(trend_id)
    if not s2["ok"]:
        return {"ok": False, "error": s2.get("error", "step2 failed")}
    results["step2"] = s2

    # Step 3
    s3 = step3_identify_bottlenecks(trend_id)
    results["step3"] = s3

    # Step 4
    s4 = step4_map_stocks(trend_id)
    results["step4"] = s4

    # Step 5
    s5 = step5_verify_stocks(trend_id)
    results["step5"] = s5

    # Step 6
    s6 = step6_cross_verify(trend_id)
    results["step6"] = s6

    # 生成总结
    bottlenecks = s3.get("bottlenecks", [])
    stocks = s5.get("stocks", [])

    summary_parts = [
        f"趋势：{s2.get('trend_name', trend_id)}",
        f"产业链共 {s2.get('total_layers', 0)} 层，识别 {len(bottlenecks)} 个瓶颈层",
    ]

    if bottlenecks:
        top = bottlenecks[:3]
        summary_parts.append(
            "核心瓶颈：" + " → ".join(
                [f"{b['name']}(卡脖子度:{b['bottleneck_score']}/5)" for b in top]
            )
        )

    if stocks:
        top_stocks = stocks[:5]
        summary_parts.append(
            "关键标的：" + "、".join(
                [f"{s['code']} {s.get('name', '')}(总分{s.get('total_score', 'N/A')})" for s in top_stocks]
            )
        )

    results["summary"] = "。".join(summary_parts) + "。"

    return {
        "ok": True,
        "results": results,
    }


# ── 报告管理 ──────────────────────────────────────────────

def save_report(trend_id, step_results):
    """保存报告到 JSON 文件"""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    filename = f"{trend_id}_{ts}.json"
    filepath = os.path.join(REPORTS_DIR, filename)

    report = {
        "trend_id": trend_id,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "iso_timestamp": now.isoformat(),
        "timestamp_short": ts,
        "filename": filename,
        "steps": step_results,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {"ok": True, "filename": filename, "created_at": report["created_at"]}


def list_reports():
    """列出所有已保存的报告"""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    reports = []
    for fname in sorted(os.listdir(REPORTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(REPORTS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 加载趋势名称
            chains = _load_supply_chains()
            trend_name = chains.get("trends", {}).get(data.get("trend_id", ""), {}).get("name", data.get("trend_id", ""))
            reports.append({
                "filename": fname,
                "trend_id": data.get("trend_id", ""),
                "trend_name": trend_name,
                "created_at": data.get("created_at", ""),
                "timestamp_short": data.get("timestamp_short", ""),
            })
        except Exception:
            reports.append({
                "filename": fname,
                "error": "无法解析",
            })

    return {"ok": True, "reports": reports}


def load_report(filename):
    """加载指定报告"""
    fpath = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(fpath):
        return {"ok": False, "error": f"报告不存在: {filename}"}

    with open(fpath, "r", encoding="utf-8") as f:
        return {"ok": True, "report": json.load(f)}


def rerun_report(filename):
    """重新运行已保存的报告，更新时间戳"""
    fpath = os.path.join(REPORTS_DIR, filename)
    if not os.path.exists(fpath):
        return {"ok": False, "error": f"报告不存在: {filename}"}

    with open(fpath, "r", encoding="utf-8") as f:
        old_report = json.load(f)

    trend_id = old_report.get("trend_id", "")
    if not trend_id:
        return {"ok": False, "error": "报告中没有 trend_id"}

    # 重新跑全流程
    results = step7_full_auto(trend_id)
    if not results["ok"]:
        return results

    # 保存新报告
    save_result = save_report(trend_id, results.get("results", {}))
    return {
        "ok": True,
        "message": f"已重新分析并保存。旧报告: {filename}, 新报告: {save_result['filename']}",
        "old_filename": filename,
        "new_filename": save_result["filename"],
        "created_at": save_result["created_at"],
        "results": results.get("results", {}),
    }
