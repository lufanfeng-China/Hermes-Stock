from app.stock_filter import _universe


def test_universe_projects_financial_health_recovery_basis_contract():
    _universe.cache_clear()
    rows, _ = _universe()
    assert rows
    required = {
        "annual_score_version",
        "annual_score_basis_track",
        "annual_score_comparable",
        "annual_growth_quality_basis",
        "annual_cash_quality_basis",
    }
    assert required <= set(rows[0])
