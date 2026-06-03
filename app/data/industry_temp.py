"""Industry temperature loading."""
import json
from pathlib import Path

DERIVED_FINAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final"

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

