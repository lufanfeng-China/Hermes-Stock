#!/usr/bin/env python3
"""Background script: search competitive edge info for a stock and cache it.
Called by app/competitive_edge.py as a subprocess.
"""
import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "derived" / "cache" / "competitive_edge"


def search_and_cache(market: str, symbol: str, stock_name: str) -> None:
    text = _search_all(stock_name)
    data = {
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "text": text if text else "暂无相关信息",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_DIR / f"{market}_{symbol}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _search_all(stock_name: str) -> str:
    if not stock_name:
        return ""
    queries = [
        f"{stock_name} 国内第一 市占率 行业龙头 领先",
        f"{stock_name} 卡脖子 核心技术 国产替代 打破垄断",
        f"{stock_name} 竞争力 优势 排名",
    ]
    all_lines = []
    for q in queries:
        lines = _bing_search(q)
        all_lines.extend(lines)
        if len(all_lines) >= 8:
            break
    return "\n\n".join(all_lines) if all_lines else ""


def _bing_search(query: str, max_results: int = 4) -> list[str]:
    encoded = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={encoded}&setlang=zh-cn&cc=cn"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    lines = []
    blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)
    for block in blocks[:max_results]:
        title_m = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_m = re.search(r'<(?:p|div) class="b_lineclamp[^"]*"[^>]*>(.*?)</(?:p|div)>', block, re.DOTALL)
        if not snippet_m:
            snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
        snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
        if title:
            lines.append(f"· {title}：{snippet}" if snippet else f"· {title}")
    return lines


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        search_and_cache(sys.argv[1], sys.argv[2], sys.argv[3])
