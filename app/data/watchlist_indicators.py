"""Published, dated stock-filter indicators for compact watchlist rows.

Each field retains its own source date. A malformed/stale publication is unknown,
never replaced by a live raw-price or a different snapshot's value.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from collections.abc import Iterable
from pathlib import Path

from app.config import DERIVED_FINAL_DIR
from app.swing_presentation import presentation
from app.swing_snapshot import RULE_VERSION as SWING_RULE

FINAL = Path(DERIVED_FINAL_DIR)


@lru_cache(maxsize=4)
def _decode_snapshot(path: Path, inode: int, mtime_ns: int, size: int) -> dict:
    # Cache only a published file identity. Atomic replacement changes its stamp;
    # source payloads are treated as immutable during a request.
    return json.loads(path.read_text(encoding='utf-8'))


def _published(name: str, schema: str, *, qfq: bool = False, swing: bool = False) -> dict:
    try:
        path = FINAL / name
        stat = path.stat()
        payload = _decode_snapshot(path, stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return {}
    if (not isinstance(payload, dict) or payload.get('schema_version') != schema
            or not isinstance(payload.get('as_of_date'), str)
            or not isinstance(payload.get('stocks'), dict)
            or (qfq and payload.get('price_basis') != 'tdx_export_qfq')
            or (swing and (payload.get('rule_version') != SWING_RULE
                           or payload.get('completeness') != 'complete'))):
        return {}
    return payload


def _percent(value) -> bool:
    try:
        return value is not None and 0 <= float(value) <= 100 and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def load_watchlist_indicators(entries: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """Join only published snapshots by market:symbol, preserving per-source dates."""
    pe = _published('stock_filter_pe_percentile_current.json', 'stock-filter-pe-percentile-v1')
    turnover = _published('stock_filter_turnover_percentile_current.json', 'stock-filter-turnover-percentile-v2')
    relative = _published('market_relative_strength_current.json', 'market-relative-strength-v1', qfq=True)
    swing = _published('swing_structure_v8_current.json', 'swing-structure-v8', qfq=True, swing=True)
    out: dict[tuple[str, str], dict] = {}
    for entry in entries:
        market, symbol = str(entry.get('market') or '').lower(), str(entry.get('symbol') or '').zfill(6)
        key = f'{market}:{symbol}'
        row: dict = {}
        p = (pe.get('stocks') or {}).get(key) or {}
        pe_ok = (p.get('pe_percentile_5y_status') == 'ok'
                 and p.get('pe_percentile_5y_price_date') == pe.get('as_of_date')
                 and _percent(p.get('pe_percentile_5y')))
        row.update(pe_percentile_5y=p.get('pe_percentile_5y') if pe_ok else None,
                   pe_percentile_5y_status='ok' if pe_ok else 'stale_snapshot',
                   pe_percentile_5y_price_date=pe.get('as_of_date') if pe_ok else None,
                   pe_percentile_5y_sample_count=p.get('pe_percentile_5y_sample_count') if pe_ok else None)
        t = (turnover.get('stocks') or {}).get(key) or {}
        sample_count = t.get('turnover_percentile_1y_sample_count')
        turnover_ok = (t.get('turnover_percentile_1y_status') == 'ok'
                       and t.get('turnover_percentile_1y_as_of') == turnover.get('as_of_date')
                       and isinstance(sample_count, (int, float)) and sample_count >= 120
                       and _percent(t.get('turnover_percentile_1y')))
        row.update(turnover_percentile_1y=t.get('turnover_percentile_1y') if turnover_ok else None,
                   turnover_percentile_1y_status='ok' if turnover_ok else 'stale_snapshot',
                   turnover_percentile_1y_as_of=turnover.get('as_of_date') if turnover_ok else None,
                   turnover_percentile_1y_sample_count=t.get('turnover_percentile_1y_sample_count') if turnover_ok else None)
        r = (relative.get('stocks') or {}).get(key) or {}
        relative_ok = (r.get('as_of_date') == relative.get('as_of_date')
                       and _percent(r.get('mrs_score')))
        row.update(mrs_score=r.get('mrs_score') if relative_ok else None,
                   mrs_label=r.get('mrs_label') if relative_ok else None,
                   relative_strength_state_label=r.get('relative_strength_state_label') if relative_ok else None,
                   relative_strength_as_of=relative.get('as_of_date') if relative_ok else None)
        s = (swing.get('stocks') or {}).get(key) or {}
        swing_ok = (s.get('status') == 'ok' and s.get('last_bar_date') == swing.get('as_of_date')
                    and bool(s.get('source_sha256')))
        observation = ({**s, **presentation(s)} if swing_ok else
                       {**presentation({}), 'status': 'stale_qfq' if s else 'missing_qfq',
                        'state': None, 'last_bar_date': s.get('last_bar_date')})
        row.update(swing_structure=observation,
                   swing_structure_as_of=swing.get('as_of_date') if swing_ok else None)
        out[(market, symbol)] = row
    return out
