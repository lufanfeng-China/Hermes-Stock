"""Snapshot rebuilds must not copy every security index for each lookup."""
import pandas as pd
from app.undervaluation.own_valuation_history import _row_for


def test_row_lookup_reuses_existing_string_index(monkeypatch):
    frame=pd.DataFrame({'基本每股收益':[0.5,1.0]},index=['000001','600000'])
    def forbid_copy(*args,**kwargs):
        raise AssertionError('per-security lookup must not cast/copy the whole universe index')
    monkeypatch.setattr(pd.Index,'astype',forbid_copy)
    assert _row_for({'2026Q3':frame},'2026Q3','000001')['基本每股收益']==0.5
    assert _row_for({'2026Q3':frame},'2026Q3','600000')['基本每股收益']==1.0
    assert _row_for({'2026Q3':frame},'2026Q3','999999') is None
