"""Watchlist column and chart contracts exercised in Node without a browser server."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'web/watchlist.html').read_text()
JS = (ROOT / 'web/watchlist.js').read_text()


def render_row(stock):
    script = re.sub(r"^import .*?;\s*", "", JS, count=1, flags=re.MULTILINE)
    script = re.sub(r"loadWatchlist\(\);\s*$", "", script)
    script = script.split('// ── Audited evidence dialogs')[0]
    harness = f"""
const vm=require('vm'), assert=require('assert');
const stock={json.dumps(stock, ensure_ascii=False)};
const tbody={{innerHTML:''}};
const document={{querySelector:s=>s==='#watchlist-table tbody'?tbody:null,
  querySelectorAll:()=>[],getElementById:()=>null}};
const context={{stock,document,console,window:{{}},KlineChart:class{{}},fetch:()=>Promise.reject(Error('unexpected fetch'))}};
vm.createContext(context);vm.runInContext({json.dumps(script)},context);
vm.runInContext('renderTable([stock])',context);console.log(tbody.innerHTML);
"""
    proc = subprocess.run(['node', '-e', harness], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode:
        raise AssertionError(proc.stderr)
    return proc.stdout


class WatchlistColumnsTest(unittest.TestCase):
    def test_columns_and_valid_evidence(self):
        headers = re.findall(r'<th[^>]*>(.*?)</th>', HTML)
        self.assertEqual(headers, ['', '股票', '现价', '10MA距离', '30斜率', '当前收益', '最大收益', '最大损失', '加入日期', '行业', 'PE分位', '换手分位', '相对大盘强弱', '波峰波谷结构', '操作'])
        row = render_row(dict(market='sh', symbol='600000', stock_name='<测试>', pe_percentile_5y=26.5,
            pe_percentile_5y_status='ok', pe_percentile_5y_price_date='2026-11-13',
            turnover_percentile_1y=53.2, turnover_percentile_1y_status='ok',
            turnover_percentile_1y_as_of='2026-11-13', turnover_percentile_1y_sample_count=150,
            mrs_score=88.3, mrs_label='强势', relative_strength_as_of='2026-11-13',
            swing_structure_as_of='2026-11-12', swing_structure=dict(status='ok',state='上升',tendency='bull',stars=3,
                as_of='2026-11-12',last_bar_date='2026-11-12',source_sha256='abc')))
        self.assertEqual(len(re.findall(r'<td\b', row)), len(headers))
        self.assertIn('&lt;测试&gt;', row)
        self.assertIn('26.5%', row)
        self.assertIn('53.2%', row)
        self.assertIn('88.3', row)
        self.assertIn('2026-11-13', row)
        self.assertIn('2026-11-12', row)
        self.assertIn('data-turnover-trend=', row)
        self.assertIn('data-swing-chart=', row)
        self.assertNotIn('<td>持有</td>', row)

    def test_swing_snapshot_day_is_authoritative_when_observation_omits_as_of(self):
        row = render_row(dict(market='sh', symbol='603586', swing_structure_as_of='2026-11-12',
            swing_structure=dict(status='ok',state='上涨突破',tendency='bull',stars=3,
                last_bar_date='2026-11-12',source_sha256='digest')))
        self.assertIn('data-swing-chart=', row)
        self.assertIn('2026-11-12', row)

    def test_invalid_evidence_is_unknown_and_not_clickable(self):
        row = render_row(dict(market='sz',symbol='000001', pe_percentile_5y=-10, pe_percentile_5y_status='invalid',
            turnover_percentile_1y=89, turnover_percentile_1y_status='insufficient_history',
            turnover_percentile_1y_sample_count=25, turnover_percentile_1y_as_of='2026-11-13',
            mrs_score=float('nan'), mrs_label='强势', relative_strength_as_of='2026-11-13',
            swing_structure_as_of='2026-11-12', swing_structure=dict(status='missing_qfq',state='上升',tendency='bull',stars=5)))
        self.assertNotIn('data-turnover-trend=', row)
        self.assertNotIn('data-swing-chart=', row)
        self.assertNotIn('89.0%', row)
        self.assertNotIn('强势', row)
        self.assertIn('未知', row)
        self.assertNotIn('截至 未知', row)

    def test_dialogs_and_live_qfq_contract(self):
        for marker in ['turnover-trend-dialog','turnover-trend-svg','turnover-trend-tooltip','swing-chart-dialog','swing-chart-svg','swing-chart-macd']:
            self.assertIn(f'id="{marker}"', HTML)
        for lib in ['swing-chart.js','price-trend-chart.js']:
            self.assertIn(lib, HTML)
        self.assertIn('/api/stock-filter-turnover-trend?', JS)
        self.assertIn('/api/swing-structure?', JS)
        self.assertIn('SwingChart.chartEvidence', JS)
        self.assertIn('SwingChart.renderOverlay', JS)
        self.assertIn('PriceTrendChart.renderMacd', JS)
        self.assertIn("data.source_type !== 'live_qfq'", JS)
        self.assertIn('表格结构截至', JS)
        self.assertIn('当前前复权截至', JS)
        self.assertNotIn("query.set('as_of_date'", JS)


if __name__ == '__main__':
    unittest.main()
