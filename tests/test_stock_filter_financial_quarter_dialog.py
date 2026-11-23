from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'web' / 'stock-filter.html'
JS = ROOT / 'web' / 'stock-filter.js'


def test_five_year_health_opens_all_metric_quarterly_history_dialog():
    html = HTML.read_text(encoding='utf-8')
    js = JS.read_text(encoding='utf-8')

    assert 'quarterly-financial-chart.js' in html
    assert 'id="financial-quarter-history-dialog"' in html
    assert 'id="financial-quarter-history-charts"' in html
    assert 'class="financial-history-trigger"' in js
    assert 'function annualHealthCell(row, historical)' in js
    assert '/api/stock-score-report-history?' in js
    assert "years: '30'" in js
    assert 'QuarterlyFinancialChart.METRICS' in js
    assert 'QuarterlyFinancialChart.renderQuarterMetric' in js
    assert 'financial-quarter-chart-card' in js


def test_result_rows_keep_quarter_health_static_and_annual_health_clickable():
    js = JS.read_text(encoding='utf-8')
    render_rows = js[js.index('function renderRows('):js.index('function temperatureCurrentCell(')]
    assert "annualHealthCell(row, data.is_historical)" in render_rows
    assert "if (historical) return healthCell(row.annual_total, row.annual_period);" in js
    assert "!asOfDate.value" in js
    assert "button.disabled = historical" in js
    assert "quarterlyHealthCell(row)" in render_rows
    assert "return healthCell(row.quarterly_total, row.quarterly_period);" in js
    assert 'data-market="' in render_rows and 'data-symbol="' in render_rows
    assert "annualScoreBasisLabel(row.annual_score_basis_track)" in js
    assert "恢复型" in js and "恶化型" in js


def test_report_history_allows_full_warehouse_window_but_rejects_larger_requests():
    from app.financial.reports import load_recent_three_year_financial_reports

    with pytest.raises(ValueError, match='market must be'):
        load_recent_three_year_financial_reports('', '000001', years=30)
    with pytest.raises(ValueError, match='years must be between 1 and 30'):
        load_recent_three_year_financial_reports('sz', '000001', years=31)
