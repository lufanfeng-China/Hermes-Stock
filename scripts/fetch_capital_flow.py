#!/usr/bin/env python3
"""Fetch and cache full-market capital flow data from Eastmoney."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = PROJECT_ROOT / "data/derived/cache/capital_flow/capital_flow_full.json"

FIELDS = "f12,f14,f2,f3,f62,f66,f69,f72,f75,f78,f184"
PAGE_SIZE = 500
# All A-share stocks (SH main + STAR + SZ main + ChiNext)
MARKET_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def fetch_page(page: int) -> dict | None:
    url = (
        f"{BASE_URL}?cb=&fid=f62&po=1&pz={PAGE_SIZE}&pn={page}"
        f"&np=1&fltt=2&invt=2&fs={MARKET_FILTER}&fields={FIELDS}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://data.eastmoney.com/",
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt < 2:
                time.sleep(2)
                continue
            print(f"  page {page} failed: {exc}", flush=True)
            return None


def main() -> None:
    # Fetch first page to get total count
    print("Fetching page 1...", flush=True)
    p1 = fetch_page(1)
    if not p1 or not p1.get("data"):
        print("ERROR: failed to fetch first page", flush=True)
        sys.exit(1)

    total = p1["data"]["total"]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"Total stocks: {total}, pages: {total_pages}", flush=True)

    all_rows = []
    for page in range(1, total_pages + 1):
        if page == 1:
            data = p1
        else:
            time.sleep(0.8)  # rate limit
            data = fetch_page(page)

        if data and data.get("data"):
            diff = data["data"].get("diff")
            if diff and isinstance(diff, list):
                for row in diff:
                    symbol = str(row.get("f12", ""))
                    name = str(row.get("f14", ""))
                    price = row.get("f2")       # 最新价
                    pct_chg = row.get("f3")     # 涨跌幅 %
                    main_inflow = row.get("f62")  # 主力净流入 (yuan)
                    main_pct = row.get("f184")     # 主力净流入占比 %
                    super_large = row.get("f66")   # 超大单净流入
                    large = row.get("f72")         # 大单净流入
                    mid = row.get("f78")           # 中单净流入
                    small = row.get("f84")         # 小单净流入
                    market = "sh" if symbol.startswith(("6", "68")) else "sz"
                    all_rows.append({
                        "symbol": symbol,
                        "name": name,
                        "market": market,
                        "price": price,
                        "pct_chg": pct_chg,
                        "main_inflow": main_inflow,
                        "main_inflow_pct": main_pct,
                        "super_large_inflow": super_large,
                        "large_inflow": large,
                        "mid_inflow": mid,
                        "small_inflow": small,
                    })
            print(f"  page {page}/{total_pages}: {len(all_rows)} rows so far", flush=True)

    # Sort by main_inflow descending
    all_rows.sort(key=lambda r: float(r["main_inflow"] or 0), reverse=True)

    payload = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_rows),
        "top_inflow": all_rows[:20],
        "top_outflow": sorted(all_rows, key=lambda r: float(r["main_inflow"] or 0))[:20],
        "all": all_rows,
    }

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done: {len(all_rows)} stocks, cache: {CACHE_PATH}", flush=True)
    print(json.dumps({"ok": True, "rows": len(all_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
