"""Causal duration of a published swing main-state label."""
from __future__ import annotations

import pandas as pd

from app.swing_structure import classify
from app.wyckoff_events import clean_wyckoff_bars


def state_run(bars: pd.DataFrame, state: str) -> dict | None:
    """Replay only known prefixes; never backdate a confirmed pivot to its occurrence."""
    valid = clean_wyckoff_bars(bars)
    if valid.empty or classify(valid)['state'] != state:
        return None
    first = 0
    previous_state = None
    for size in range(len(valid) - 1, 0, -1):
        before = classify(valid.iloc[:size])['state']
        if before != state:
            first, previous_state = size, before
            break
    day = lambda i: str(valid.index[i].date())
    return {'state': state, 'start_date': day(first), 'through_date': day(-1),
            'trading_days': len(valid) - first, 'start_confirmed': previous_state is not None,
            'previous_state': previous_state,
            'previous_date': day(first - 1) if first else None}
