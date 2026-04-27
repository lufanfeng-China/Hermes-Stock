#!/usr/bin/env python3
"""Serve a minimal local dashboard for one stock's daily trend and volume windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.index import concept_search_response, stock_profile_response, stock_search_response


TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
DEFAULT_SYMBOL = "601600"
DEFAULT_HISTORY_LIMIT = 120
WEB_ROOT = PROJECT_ROOT / "web"


def infer_market(symbol: str) -> tuple[str, int]:
    if symbol.startswith(("60", "68", "90")):
        return "sh", 1
    if symbol.startswith(("00", "30", "20")):
        return "sz", 0
    raise ValueError(f"unsupported symbol prefix for {symbol}")


def load_stock_history(symbol: str, history_limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, object]:
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
suffix = int(sys.argv[3])
tdxdir = sys.argv[4]
history_limit = int(sys.argv[5])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)
minute = reader.minute(symbol=symbol, suffix=suffix)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")
if minute is None or minute.empty:
    raise RuntimeError("minute data not found")

minute = minute.copy()
minute["trading_day"] = minute.index.strftime("%Y-%m-%d")
window_specs = {
    "open_15m_volume": ("09:31:00", "09:45:00"),
    "window_1430_1445_volume": ("14:30:00", "14:45:00"),
}
by_day = {}
for trading_day, day_frame in minute.groupby("trading_day", sort=True):
    metrics = {}
    timestamps = day_frame.index.strftime("%H:%M:%S")
    for indicator_name, (start_ts, end_ts) in window_specs.items():
        selected = day_frame.loc[(timestamps >= start_ts) & (timestamps <= end_ts)]
        metrics[indicator_name] = {
            "volume": int(selected["volume"].fillna(0).sum()),
            "bar_count": int(selected.shape[0]),
        }
    by_day[trading_day] = metrics

rows = []
for index, row in daily.sort_index().iterrows():
    trading_day = index.strftime("%Y-%m-%d")
    metrics = by_day.get(trading_day)
    if not metrics:
        continue
    rows.append(
        {
            "trading_day": trading_day,
            "close": round(float(row["close"]), 4),
            "open_15m_volume": metrics["open_15m_volume"]["volume"],
            "open_15m_bar_count": metrics["open_15m_volume"]["bar_count"],
            "window_1430_1445_volume": metrics["window_1430_1445_volume"]["volume"],
            "window_1430_1445_bar_count": metrics["window_1430_1445_volume"]["bar_count"],
        }
    )

if not rows:
    raise RuntimeError("no overlapping daily/minute history found")

rows = rows[-history_limit:]
latest = rows[-1]
payload = {
    "ok": True,
    "symbol": symbol,
    "market": market,
    "history_limit": history_limit,
    "latest_trading_day": latest["trading_day"],
    "latest_metrics": {
        "open_15m_volume": latest["open_15m_volume"],
        "open_15m_bar_count": latest["open_15m_bar_count"],
        "window_1430_1445_volume": latest["window_1430_1445_volume"],
        "window_1430_1445_bar_count": latest["window_1430_1445_bar_count"],
        "close": latest["close"],
    },
    "history": rows,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [
            TONGDAXIN_PYTHON,
            "-c",
            script,
            symbol,
            market,
            str(suffix),
            TONGDAXIN_DIR,
            str(history_limit),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "unknown subprocess error").strip()
        raise RuntimeError(stderr)
    return json.loads(result.stdout)


class StockDashboardHandler(BaseHTTPRequestHandler):
    server_version = "StockDashboard/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/stock-window-volume":
            self.handle_api(parsed.query)
            return
        if parsed.path == "/api/search/stocks":
            self.handle_stock_search(parsed.query)
            return
        if parsed.path == "/api/search/concepts":
            self.handle_concept_search(parsed.query)
            return
        if parsed.path == "/api/stock-profile":
            self.handle_stock_profile(parsed.query)
            return
        if parsed.path == "/":
            self.serve_static("index.html")
            return
        if parsed.path.startswith("/"):
            self.serve_static(parsed.path.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_static(self, relative_path: str) -> None:
        target = (WEB_ROOT / relative_path).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            payload = load_stock_history(symbol)
            self.respond_json(HTTPStatus.OK, payload)
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_symbol",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": {
                        "code": "data_unavailable",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )

    def handle_stock_search(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["20"])[0], default=20, maximum=50)
        try:
            self.respond_json(HTTPStatus.OK, stock_search_response(search_query, limit=limit))
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_concept_search(self, query: str) -> None:
        params = parse_qs(query)
        search_query = params.get("q", [""])[0].strip()
        limit = self.parse_limit(params.get("limit", ["20"])[0], default=20, maximum=50)
        try:
            self.respond_json(HTTPStatus.OK, concept_search_response(search_query, limit=limit))
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    def handle_stock_profile(self, query: str) -> None:
        params = parse_qs(query)
        symbol = params.get("symbol", [DEFAULT_SYMBOL])[0].strip() or DEFAULT_SYMBOL
        try:
            self.respond_json(HTTPStatus.OK, stock_profile_response(symbol))
        except ValueError as exc:
            self.respond_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": {
                        "code": "stock_not_found",
                        "message": str(exc),
                        "symbol": symbol,
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - exercised by manual integration
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "search_unavailable", "message": str(exc)}},
            )

    @staticmethod
    def parse_limit(raw_value: str, *, default: int, maximum: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return default
        return max(1, min(maximum, value))

    def respond_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Default: 8765")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not WEB_ROOT.is_dir():
        raise SystemExit(f"web root not found: {WEB_ROOT}")
    server = ThreadingHTTPServer((args.host, args.port), StockDashboardHandler)
    print(f"Serving stock dashboard on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
