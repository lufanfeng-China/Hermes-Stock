"""Project-wide constants and paths."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Paths
TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
WEB_ROOT = PROJECT_ROOT / "web"
DERIVED_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
WATCHLIST_PATH = PROJECT_ROOT / "data" / "derived" / "watchlist.json"
STOCK_SCREENER_STRATEGY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_screener_strategies_current.json"
STOCK_RPS_CURRENT_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_current.json"
CAPITAL_FLOW_CACHE = PROJECT_ROOT / "data" / "derived" / "cache" / "capital_flow" / "capital_flow_full.json"

# Defaults
DEFAULT_SYMBOL = "601600"
DEFAULT_HISTORY_LIMIT = 120
DEFAULT_HERMES_MODEL = os.environ.get("HERMES_MODEL", "").strip()
DATA_UPDATE_OUTPUT_TAIL_LINES = 8
