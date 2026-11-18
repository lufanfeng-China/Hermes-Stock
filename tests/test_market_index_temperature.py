"""Four local TDX market-index MA temperature cards on the stock-filter page."""
import struct
from datetime import date, timedelta
from pathlib import Path

from app.market_index_temperature import index_temperature_response

PERIODS = [240, 120, 60, 30, 20, 10, 5]
INDICES = [('sh', '000001'), ('sz', '399001'), ('sz', '399006'), ('sh', '000680')]


def _write_day(root: Path, market: str, symbol: str, closes: list[float]) -> None:
    path = root / 'vipdoc' / market / 'lday' / f'{market}{symbol}.day'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as out:
        for i, close in enumerate(closes):
            day = int((date(2025, 1, 1) + timedelta(days=i)).strftime('%Y%m%d'))
            raw = int(close * 100)
            out.write(struct.pack('<IIIIIfII', day, raw, raw, raw, raw, 0., 1, 0))


def test_four_indices_strictly_split_above_and_not_above_on_last_close(tmp_path):
    for market, symbol in INDICES:
        _write_day(tmp_path, market, symbol, [100.] * 239 + [101.])
    result = index_temperature_response(tmp_path)
    assert result['ok'] and [(x['market'], x['symbol']) for x in result['indices']] == INDICES
    assert result['indices'][-1]['name'] == '科创综指'
    for row in result['indices']:
        assert row['above'] == PERIODS and row['below'] == [] and row['unavailable'] == []
        assert row['close'] == 101. and row['as_of_date'] == '2025-08-28'
        assert row['moving_averages']['240'] < row['close']
    _write_day(tmp_path, 'sh', '000001', [100.] * 240)
    equal = index_temperature_response(tmp_path)['indices'][0]
    assert equal['above'] == [] and equal['below'] == PERIODS


def test_short_history_and_invalid_halt_not_guessed(tmp_path):
    _write_day(tmp_path, 'sh', '000001', [100.] * 120 + [0.])
    result = index_temperature_response(tmp_path)
    short = result['indices'][0]
    assert short['as_of_date'] == '2025-04-30'
    assert short['unavailable'] == [240]
    assert short['below'] == [120, 60, 30, 20, 10, 5]
    assert result['indices'][1]['status'] == 'missing'
    assert result['indices'][1]['above'] == [] and result['indices'][1]['below'] == []
    assert result['indices'][1]['unavailable'] == PERIODS


def test_page_has_four_cards_location_and_date_aware_api_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (root / 'web/stock-filter-market-temperature.js').read_text(encoding='utf-8')
    handler = (root / 'app/handler.py').read_text(encoding='utf-8')
    assert html.index('id="market-index-temperature"') < html.index('class="stock-filter-workbench"')
    assert 'stock-filter-market-temperature.js?' in html
    assert '/api/market-index-temperature' in handler and '/api/market-index-temperature' in js
    for marker in ('market-index-above', 'market-index-below', 'market-index-divider', 'as_of_date', 'unavailable'):
        assert marker in js
