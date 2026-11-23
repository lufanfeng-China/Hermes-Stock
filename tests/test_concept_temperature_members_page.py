from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")


def test_member_table_exposes_requested_market_and_health_columns():
    header = HTML.split('<tbody id="members">', 1)[0].rsplit('<thead><tr>', 1)[1]
    expected = [
        '代码', '名称', 'X日涨幅', '最新股价', '1年涨幅', '3年涨幅', '5年涨幅',
        '5/20日量比', 'MRS', '换手分位', 'PE-TTM', '五年健康', '当季健康',
    ]
    positions = [header.index(label) for label in expected]
    assert positions == sorted(positions)
    assert '最新前复权收盘' not in header


def test_member_renderer_discloses_all_history_fallback_and_new_fields():
    for field in (
        'return_1y_pct', 'return_3y_pct', 'return_5y_pct',
        'return_1y_basis', 'return_3y_basis', 'return_5y_basis',
        'mrs_score', 'turnover_percentile_1y', 'pe_ttm',
        'annual_total', 'annual_period', 'annual_score_basis_track',
        'annual_growth_quality_basis', 'annual_cash_quality_basis',
        'quarterly_total', 'quarterly_period',
    ):
        assert f'row.{field}' in JS
    assert '全部历史' in JS
    assert '恢复型' in JS
    assert '恶化型' in JS
    assert 'scoreCell(row.annual_total, row.annual_period, row.annual_score_basis_track, row.annual_growth_quality_basis, row.annual_cash_quality_basis)' in JS
    assert 'colspan="13"' in JS
    assert 'colspan="5"' not in JS
