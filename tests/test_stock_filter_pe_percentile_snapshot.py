"""Contract tests for the raw-price daily PE percentile snapshot."""
from datetime import date, timedelta
import json
import struct

import pytest

from app.relative_valuation.pe_percentile_snapshot import compute_for_stock, load_disclosures_bulk


def test_compute_for_stock_uses_disclosed_raw_daily_pe_and_five_year_window():
    end = date(2026, 11, 5)
    bars = [(end - timedelta(days=i), 10.0 + i / 100) for i in range(90, -1, -1)]
    reports = [{"period": "2026Q2", "announce_date": "2026-07-01", "ttm_profit_yi": 1.0, "total_shares": 100_000_000}]
    result = compute_for_stock(bars, reports, end.isoformat())
    assert result == {
        "pe_percentile_5y": 1.1, "pe_percentile_5y_basis": "since_listing",
        "pe_percentile_5y_sample_count": 91,
        "pe_percentile_5y_window_start": bars[0][0].isoformat(),
        "pe_percentile_5y_price_date": end.isoformat(),
        "pe_percentile_5y_latest_report_period": "2026Q2",
        "pe_percentile_5y_latest_announce_date": "2026-07-01",
        "pe_percentile_5y_current_pe": 10.0,
        "pe_percentile_5y_status": "ok",
    }


def test_bulk_loader_reads_five_year_relevant_quarters_and_normalizes_yymmdd(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    def quarter(period, rows):
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / f"{period}.parquet")

    row = {"code": "000001", "announce_date": 260401,
           "近一年归母净利润（万元）": 10000.0, "总股本": 100_000_000.0}
    quarter("2019A", [row])
    quarter("2021Q1", [{**row, "announce_date": 210401}, {**row, "code": "600001", "announce_date": 20261106}])
    quarter("2026Q1", [{**row, "announce_date": 20260401}])
    quarter("2026Q2", [{**row, "announce_date": 20261106}])
    result = load_disclosures_bulk(tmp_path, "2026-11-05")
    assert result == {"000001": [{"period": "2021Q1", "announce_date": "20210401",
                                  "ttm_profit_yi": 1.0, "total_shares": 100_000_000.0},
                                 {"period": "2026Q1", "announce_date": "20260401",
                                  "ttm_profit_yi": 1.0, "total_shares": 100_000_000.0}]}




def test_raw_tail_keeps_pre_cutoff_bar_to_identify_five_year_basis(tmp_path):
    from mootdx.reader import Reader
    from scripts.build_stock_filter_pe_percentile_snapshot import read_raw_bars
    end = date(2026, 11, 5)
    raw = tmp_path / "vipdoc/sz/lday/sz000001.day"
    raw.parent.mkdir(parents=True)
    days = [date(2021, 11, 4), date(2021, 11, 5), end]
    raw.write_bytes(b"".join(struct.pack("<IIIIIfII", int(day.strftime("%Y%m%d")),
                                           0, 0, 0, 1000, 0., 0, 0) for day in days))
    reader = Reader.factory(market="std", tdxdir=str(tmp_path))
    bars = read_raw_bars(reader, "sz", "000001", end.isoformat())
    assert bars == [(day, 10.0) for day in days]
    reports = [{"period": "2021Q3", "announce_date": "20211001", "ttm_profit_yi": 1,
                "total_shares": 100_000_000}]
    assert compute_for_stock(bars, reports, end.isoformat())["pe_percentile_5y_basis"] == "five_years"


def test_compute_rejects_stale_bars_and_short_or_nonpositive_history():
    end = date(2026, 11, 5)
    reports = [{"period": "2025A", "announce_date": "20260401", "ttm_profit_yi": 1,
                "total_shares": 100_000_000}]
    bars = [(end - timedelta(days=i), 10.0) for i in range(58, -1, -1)]
    short = compute_for_stock(bars, reports, end.isoformat())
    assert short["pe_percentile_5y_status"] == "insufficient_history"
    assert short["pe_percentile_5y"] is None
    assert short["pe_percentile_5y_sample_count"] == 59
    stale = compute_for_stock(bars[:-1], reports, end.isoformat())
    assert stale["pe_percentile_5y_status"] == "stale_raw_price"
    assert stale["pe_percentile_5y"] is None
    loss = compute_for_stock(bars, [{**reports[0], "ttm_profit_yi": -1}], end.isoformat())
    assert loss["pe_percentile_5y_status"] == "nonpositive_ttm_profit"
    assert loss["pe_percentile_5y"] is None


def test_builder_rejects_materially_incomplete_raw_market_coverage(tmp_path):
    from scripts.build_stock_filter_pe_percentile_snapshot import build_snapshot
    day = "2026-11-05"
    metrics = tmp_path / "market.json"
    metrics.write_text(json.dumps({"metrics": {"sz:000001": {"qfq_as_of": day},
                                                "sz:000002": {"qfq_as_of": day}}}))
    raw = tmp_path / "tdx/vipdoc/sz/lday/sz000001.day"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(struct.pack("<IIIIIfII", 20261105, 0, 0, 0, 1000, 0., 0, 0))
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    with pytest.raises(ValueError, match="raw.*coverage"):
        build_snapshot(day, output=tmp_path / "current.json", metrics_path=metrics,
                       warehouse_dir=warehouse, tdx_dir=tmp_path / "tdx")
    assert not (tmp_path / "current.json").exists()


def test_builder_publishes_full_universe_and_rejects_stale_qfq_without_overwriting(tmp_path):
    from scripts.build_stock_filter_pe_percentile_snapshot import build_snapshot
    day = "2026-11-05"
    metrics = tmp_path / "market.json"
    output = tmp_path / "current.json"
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    tdx = tmp_path / "tdx"
    raw = tdx / "vipdoc" / "sz" / "lday" / "sz000001.day"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"".join(struct.pack("<IIIIIfII", int((date(2026, 11, 5) - timedelta(days=i)).strftime("%Y%m%d")), 0, 0, 0, 1000, 0., 0, 0)
                             for i in range(90, -1, -1)))
    metrics.write_text(json.dumps({"metrics": {"sz:000001": {"qfq_as_of": day},
                                                "bj:920001": {"qfq_as_of": "2026-10-19"}}}))
    payload = build_snapshot(day, output=output, metrics_path=metrics,
                             warehouse_dir=warehouse, tdx_dir=tdx)
    assert payload["schema_version"] == "stock-filter-pe-percentile-v1"
    assert payload["as_of_date"] == day
    assert set(payload["stocks"]) == {"sz:000001", "bj:920001"}
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["raw_price_coverage"] == 1
    assert json.loads(output.read_text()) == payload
    original = output.read_bytes()
    metrics.write_text(json.dumps({"metrics": {"sz:000001": {"qfq_as_of": "2026-11-04"}}}))
    with pytest.raises(ValueError, match="QFQ"):
        build_snapshot(day, output=output, metrics_path=metrics,
                       warehouse_dir=warehouse, tdx_dir=tdx)
    assert output.read_bytes() == original
    metrics.write_text(json.dumps({"metrics": {"sz:000001": {"qfq_as_of": "2026-11-04"}}}))
    with pytest.raises(ValueError, match="raw"):
        build_snapshot("2026-11-04", output=output, metrics_path=metrics,
                       warehouse_dir=warehouse, tdx_dir=tdx)
    assert output.read_bytes() == original


def test_builder_uses_filter_universe_even_if_market_metrics_omits_a_stock(tmp_path):
    from scripts.build_stock_filter_pe_percentile_snapshot import build_snapshot
    day = '2026-11-05'
    metrics = tmp_path / 'metrics.json'
    metrics.write_text(json.dumps({'metrics': {'sz:000001': {'qfq_as_of': day}}}))
    for symbol in ('000001', '000002'):
        raw = tmp_path / 'tdx/vipdoc/sz/lday' / f'sz{symbol}.day'
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(struct.pack('<IIIIIfII', 20261105, 0, 0, 0, 1000, 0., 0, 0))
    warehouse = tmp_path / 'warehouse'
    warehouse.mkdir()
    payload = build_snapshot(day, metrics_path=metrics, warehouse_dir=warehouse,
                             tdx_dir=tmp_path / 'tdx', output=tmp_path / 'result.json',
                             universe_keys=['sz:000001', 'sz:000002'])
    assert set(payload['stocks']) == {'sz:000001', 'sz:000002'}
