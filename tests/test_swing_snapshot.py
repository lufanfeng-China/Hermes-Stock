"""Swing snapshot isolation, date/prefix, immutability and missing-source controls."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import swing_snapshot


def _bars(day='2026-10-30'):
    days=pd.date_range('2026-10-26',day,freq='B')
    return pd.DataFrame({'open':[10.]*len(days),'high':[11.]*len(days),
                         'low':[9.]*len(days),'close':[10.]*len(days),
                         'volume':[100.]*len(days)},index=days)


def test_build_sample_prefix_isolation_stale_and_immutable(tmp_path: Path):
    export=tmp_path/'export'; export.mkdir()
    (export/'SH#600000.txt').write_text('real source one')
    (export/'SH#600001.txt').write_text('real source two')
    output=tmp_path/'output'
    source=tmp_path/'sync.json';source.write_text('{}')
    with patch.object(swing_snapshot,'_source_day',return_value='2026-10-30'), \
         patch.object(swing_snapshot,'discover_universe',return_value=[('sh','600000','A'),('sh','600001','B')]), \
         patch.object(swing_snapshot,'load_tdx_qfq_daily',side_effect=lambda code, export_dir: _bars('2026-10-29' if code=='600001' else '2026-10-30')), \
         patch('app.swing_structure.classify',return_value={'state':'上涨突破','reason':'confirmed','bars':5}):
        payload=swing_snapshot.build_snapshot(export,output,sync_manifest=source,limit=2)
        assert payload['coverage']['symbols_total']==2
        assert payload['coverage']['states_current']==1
        assert payload['stocks']['sh:600001']['state'] is None
        assert payload['stocks']['sh:600001']['status']=='stale_qfq'
        assert payload['stocks']['sh:600000']['last_bar_date']=='2026-10-30'
        published=json.loads((output/'swing_structure_v8/2026-10-30.json').read_text())
        assert published==payload
        assert swing_snapshot.build_snapshot(export,output,sync_manifest=source,limit=2)==payload
        with pytest.raises(ValueError,match='roll'):
            swing_snapshot.build_snapshot(export,output,trading_day='2026-10-29',sync_manifest=source,limit=2)
        with pytest.raises(ValueError,match='stale'):
            swing_snapshot.build_snapshot(export,output,trading_day='2026-10-31',sync_manifest=source,limit=2)
    assert not (output/'.swing_structure.building').exists()


def test_sample_refuses_production_output(tmp_path: Path):
    with patch.object(swing_snapshot,'_source_day',return_value='2026-10-30'):
        with pytest.raises(ValueError,match='isolated'):
            swing_snapshot.build_snapshot(tmp_path,swing_snapshot.DEFAULT_OUTPUT_DIR,limit=1)
