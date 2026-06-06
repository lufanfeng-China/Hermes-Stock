"""Technical evaluation data loading."""
import json
from pathlib import Path

DERIVED_FINAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final"

def _load_tech_eval() -> dict:
    """Load technical evaluation data, keyed by 6-digit symbol."""
    path = DERIVED_FINAL_DIR / "dataset_technical_eval.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("stocks", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}

def _load_industry_temp() -> dict:
    """Load industry temperature, keyed by industry_level_2_name -> {label, percentile}."""
    path = DERIVED_FINAL_DIR / "dataset_industry_valuation_current.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            rows = json.load(f)
        result = {}
        for row in rows:
            name = (row.get("industry_level_2_name") or "").strip()
            if name:
                result[name] = {
                    "label": row.get("temperature_label", ""),
                    "percentile": row.get("temperature_percentile_since_2022"),
                }
        return result
    except Exception:
        return {}

def _load_prev_tech_evals(max_days: int = 20) -> list[dict]:
    """Load previous tech eval files (newest first), return [{symbol: {trend, trend_label}}, ...]."""
    import glob
    pattern = str(DERIVED_FINAL_DIR / "dataset_technical_eval_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    results = []
    for fp in files[:max_days]:
        try:
            with open(fp) as f:
                data = json.load(f)
            stocks = data.get("stocks", {}) if isinstance(data, dict) else {}
            results.append({s: {"trend": v.get("trend"), "trend_label": v.get("trend_label"),
                                  "short_trend": v.get("short_trend"), "short_trend_label": v.get("short_trend_label")}
                           for s, v in stocks.items()})
        except Exception:
            results.append({})
    return results

