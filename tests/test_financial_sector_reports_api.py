from app.financial.reports import _sector_health_api


def test_sector_quarterly_breakdown_uses_readable_regulatory_metric_titles():
    record = {
        "sector_model": "bank",
        "annual_score": {"score": 93, "coverage_weight": 100, "status": "ready", "dimensions": {}, "red_flags": []},
        "quarterly_score": {
            "score": 88,
            "report_period": "2026Q3",
            "coverage_weight": 90,
            "status": "stable",
            "parts": {
                "npl_ratio": {"score": 15, "weight": 15},
                "cet1_ratio": {"score": 15, "weight": 15},
                "liquidity_coverage_ratio": {"score": 10, "weight": 10},
                "margin_financing_risk": {"score": None, "weight": 10},
                "net_capital_to_net_assets_pct": {"score": 11, "weight": 15},
            },
        },
    }

    _, monitor, _ = _sector_health_api(record)

    titles = {row["code"]: row["title"] for row in monitor["realtime_score"]["breakdown"]}
    assert titles == {
        "npl_ratio": "不良贷款率",
        "cet1_ratio": "核心一级资本充足率",
        "liquidity_coverage_ratio": "流动性覆盖率",
        "margin_financing_risk": "融资融券与信用减值风险",
        "net_capital_to_net_assets_pct": "净资本／净资产",
    }
