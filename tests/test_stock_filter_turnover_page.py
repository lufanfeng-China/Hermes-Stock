"""Stock-filter turnover percentile UI contract (no backend fixtures required)."""
import json
import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web/stock-filter.html"
JS = ROOT / "web/stock-filter.js"


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.options = {}
        self.select = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs
        if tag == "select":
            self.select = attrs.get("name") or attrs.get("id")
        if tag == "option" and self.select:
            self.options[attrs.get("value")] = attrs

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None


class StockFilterTurnoverPageTest(unittest.TestCase):
    def test_percentile_range_and_sort_are_real_form_controls(self):
        html = HTML.read_text(encoding="utf-8")
        controls = Controls()
        controls.feed(html)
        for suffix in ("min", "max"):
            name = f"turnover_percentile_1y_{suffix}"
            self.assertEqual(controls.fields[name]["type"], "number")
            self.assertEqual(controls.fields[name]["min"], "0")
            self.assertEqual(controls.fields[name]["max"], "100")
        self.assertIn("一年换手率分位（7日截尾均值，%）", html)
        self.assertIn("turnover_percentile_1y", controls.options)
        self.assertIn('<option value="turnover_percentile_1y">7日截尾均值换手分位（降序）</option>', html)
        self.assertIn('name="sort" form="filter-form"', html)
        self.assertIn("query.set('page', String(page))", JS.read_text(encoding="utf-8"))
        self.assertIn("query.set(field.name, field.value)", JS.read_text(encoding="utf-8"))

    def test_table_has_matching_turnover_cell_and_empty_state_colspans(self):
        html = HTML.read_text(encoding="utf-8")
        js = JS.read_text(encoding="utf-8")
        header_match = re.search(r'<table class="filter-table"><thead><tr>(.*?)</tr>', html)
        self.assertIsNotNone(header_match)
        assert header_match is not None
        header = header_match.group(1)
        self.assertIn(">换手分位</th>", header)
        self.assertNotIn("一年换手率分位", header)
        self.assertIn("turnoverCell(row, data.data_as_of)", js)
        self.assertEqual(header.count("<th"), 11)
        rows = js[js.index('function renderRows('):js.index('function renderIndustryDistribution(')]
        self.assertEqual(len(re.findall(r'<td[^>]*>', rows[rows.index("return '<tr>'"):])) , 11)
        self.assertNotIn('colspan="13"', js)
        self.assertEqual(js.count('colspan="11"'), 4)
        self.assertIn("历史", html)
        self.assertIn("换手率", html)

    def test_cell_shows_real_evidence_and_unknown_without_fabricated_zero(self):
        source = JS.read_text(encoding="utf-8")
        start = source.index("  function turnoverCell(row, day) {")
        end = source.index("\n  function ", start + 3)
        esc = "function esc(value) { return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\"/g,'&quot;'); }"
        fixed = "function fixed(value, digits) { return Number(value).toFixed(digits); }"
        script = esc + fixed + source[start:end] + "\nconsole.log(JSON.stringify([turnoverCell({market:'sh',symbol:'600000',stock_name:'浦发银行',turnover_percentile_1y: 0, turnover_percentile_1y_current_turnover: 2.13, turnover_percentile_1y_sample_count: 201, turnover_percentile_1y_as_of: '2026-11-13', turnover_percentile_1y_window_start: '2025-11-13', turnover_percentile_1y_current_shares_source: 'report_proxy', turnover_percentile_1y_report_period: '2026Q3', turnover_percentile_1y_report_announce: '2026-10-30', turnover_percentile_1y_report_fallback_count: 4}, '2026-11-13'), turnoverCell({turnover_percentile_1y: null, turnover_percentile_1y_status: 'insufficient_history'}, '2026-11-13'), turnoverCell({}, '2026-11-13'), turnoverCell({turnover_percentile_1y: 42, turnover_percentile_1y_status: '<bad>'}, '2026-11-13'), turnoverCell({market:'sh',symbol:'600000',turnover_percentile_1y: 19, turnover_percentile_1y_sample_count: 119}, '2026-11-13')]));"
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        valid, unknown, absent, escaped, short = json.loads(proc.stdout)
        for token in ("<button", "data-turnover-trend", 'data-market="sh"', 'data-symbol="600000"', 'data-date="2026-11-13"', "0.0%", "2.13%", "201", "2026-11-13", "2025-11-13", "财报代理", "2026Q3", "2026-10-30", "4", "7日截尾均值"):
            self.assertIn(token, valid)
        self.assertNotIn('<button', unknown + absent + escaped + short)
        self.assertIn('120', short)
        self.assertIn("样本不足", unknown)
        self.assertIn("有效7日截尾均值样本不足120日", unknown)
        self.assertNotIn("0.0%", unknown + absent)
        self.assertIn("—", absent)
        self.assertNotIn("<bad>", escaped)

    def test_trend_dialog_markup_and_cache_busted_script(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn('id="turnover-trend-dialog"', html)
        self.assertIn('aria-labelledby="turnover-trend-title"', html)
        self.assertIn('id="turnover-trend-status" role="status"', html)
        self.assertIn('id="turnover-trend-svg"', html)
        self.assertIn('id="turnover-trend-tooltip"', html)
        self.assertRegex(html, r'/stock-filter\.js\?v=[^"\s]+')

    def test_chart_uses_historical_percentiles_not_raw_turnover_and_breaks_missing_points(self):
        source = JS.read_text(encoding="utf-8")
        start = source.index('  function turnoverTrendChart(')
        end = source.index('\n  function ', start + 3)
        script = source[start:end] + "\nconsole.log(JSON.stringify(turnoverTrendChart([{date:'2025-11-14',percentile:10,trimmed_average_pct:1,sample_count:130},{date:'2026-03-01',percentile:null,trimmed_average_pct:null,sample_count:0},{date:'2026-11-13',percentile:90,trimmed_average_pct:3,sample_count:190},{date:'2026-11-14',percentile:40,sample_count:190}], '2026-11-13')));"
        chart = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout)
        self.assertIn('2025-11-13', chart)
        self.assertIn('2026-11-13', chart)
        self.assertNotIn('2026-11-14', chart)
        self.assertEqual(chart.count('<path '), 0)  # isolated points cannot be connected through a null
        self.assertEqual(chart.count('data-turnover-point'), 2)
        self.assertIn('0%', chart)
        self.assertIn('100%', chart)

    def test_chart_connects_only_adjacent_valid_percentiles_and_rejects_short_history(self):
        source = JS.read_text(encoding='utf-8')
        start = source.index('  function turnoverTrendChart(')
        end = source.index('\n  function ', start + 3)
        script = source[start:end] + "\nconsole.log(JSON.stringify(turnoverTrendChart([{date:'2025-11-12',percentile:99,sample_count:200},{date:'2025-11-13',percentile:12,sample_count:120},{date:'2026-01-01',percentile:20,sample_count:130},{date:'2026-02-01',percentile:25,sample_count:119},{date:'2026-04-01',percentile:30,sample_count:130},{date:'2026-05-01',percentile:40,sample_count:140},{date:'2026-06-01',percentile:null,sample_count:150}], '2026-11-13')));"
        chart = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(chart.count('<path '), 2)
        self.assertEqual(chart.count('data-turnover-point'), 4)
        self.assertNotIn('2025-11-12', chart)
        self.assertNotIn('99.0%', chart)
        self.assertNotIn('25.0%', chart)

    def test_trend_endpoint_and_dialog_lifecycle_are_wired(self):
        source = JS.read_text(encoding="utf-8")
        for token in ('/api/stock-filter-turnover-trend?', 'as_of_date: trigger.dataset.date',
                      'response.ok', 'payload.ok', 'payload.as_of_date',
                      "results.addEventListener('click'", "[data-turnover-trend]",
                      'turnoverTrendController.abort()', 'turnoverTrendTrigger.focus()',
                      'turnoverTrendDialog.showModal()', 'turnoverTrendDialog.close()'):
            self.assertIn(token, source)

    def test_turnover_range_and_sort_reach_api_query_with_historical_date(self):
        controls = Controls()
        controls.feed(HTML.read_text(encoding="utf-8"))
        fields = [
            {"name": name, "value": value, "type": controls.fields[name]["type"]}
            for name, value in (("turnover_percentile_1y_min", "12.5"),
                                ("turnover_percentile_1y_max", "80"),
                                ("as_of_date", "2026-11-13"))
        ]
        source = JS.read_text(encoding="utf-8")
        method = source[source.index("  function requestParams(page) {"):source.index("\n  function relativeStrengthCell", source.index("  function requestParams(page) {"))]
        script = ("var form = {elements: " + json.dumps(fields) + "}; "
                  "form.elements.swing_entry_only = {checked: false}; "
                  "var sort = {selectedOptions: [{dataset: {order: 'desc'}}]}; "
                  "var multi = {}; " + method +
                  "\nconsole.log(requestParams(2).toString());")
        query = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        for part in ("turnover_percentile_1y_min=12.5", "turnover_percentile_1y_max=80",
                     "as_of_date=2026-11-13", "order=desc", "page=2"):
            self.assertIn(part, query)


if __name__ == "__main__":
    unittest.main()
