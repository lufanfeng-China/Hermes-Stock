"""The watchlist list endpoint must not re-run stock detail analysis per row."""
from http import HTTPStatus

from app import handler


def test_watchlist_uses_batch_snapshot_instead_of_detail_analysis(monkeypatch):
    entries = [
        {"market": "sh", "symbol": "603895", "added_at": "2026-11-13T12:00:00", "add_price": None},
        {"market": "sz", "symbol": "002309", "added_at": "2026-11-12T12:00:00", "add_price": None},
    ]
    monkeypatch.setattr(handler, "_load_watchlist", lambda: {"stocks": entries})
    monkeypatch.setattr(handler, "_load_tech_eval", lambda: {
        "603895": {"trend_label": "空头", "short_trend": "bearish"},
    })
    monkeypatch.setattr(handler, "_load_prev_tech_evals", lambda **kwargs: [])
    monkeypatch.setattr(handler, "_load_industry_temp", lambda: {})

    def forbid_detail(*args, **kwargs):
        raise AssertionError("watchlist list must not compute stock detail")

    monkeypatch.setattr(handler, "compute_stock_score", forbid_detail)
    monkeypatch.setattr(handler, "stock_profile_response", forbid_detail)

    from mootdx.reader import Reader
    class NoDailyReader:
        def daily(self, **kwargs):
            return None
    monkeypatch.setattr(Reader, "factory", lambda **kwargs: NoDailyReader())

    class Reply:
        def respond_json(self, status, payload):
            self.status, self.payload = status, payload

    reply = Reply()
    handler.StockDashboardHandler.handle_watchlist_get(reply)
    assert reply.status == HTTPStatus.OK
    rows = reply.payload["stocks"]
    assert [r["symbol"] for r in rows] == ["603895", "002309"]
    assert rows[0]["stock_name"] == "天永智能"
    assert rows[0]["industry_level_2"] == "专用设备"
    assert rows[0]["tech_trend_label"] == "空头"
    assert rows[0]["market_total_score"] is not None
    assert all("_error" not in row for row in rows)


def test_watchlist_merges_published_indicator_rows_without_detail_calls(monkeypatch):
    entries = [{"market": "sh", "symbol": "603895", "added_at": "2026-11-13", "add_price": None}]
    monkeypatch.setattr(handler, "_load_watchlist", lambda: {"stocks": entries})
    monkeypatch.setattr(handler, "_load_tech_eval", lambda: {})
    monkeypatch.setattr(handler, "_load_prev_tech_evals", lambda **kwargs: [])
    monkeypatch.setattr(handler, "_load_industry_temp", lambda: {})
    monkeypatch.setattr(handler, "load_watchlist_indicators", lambda items: {
        ("sh", "603895"): {"pe_percentile_5y": 51.1, "relative_strength_as_of": "2026-11-12"}})
    from mootdx.reader import Reader
    class NoDailyReader:
        def daily(self, **kwargs):
            return None
    monkeypatch.setattr(Reader, "factory", lambda **kwargs: NoDailyReader())
    class Reply:
        def respond_json(self, status, payload):
            self.status, self.payload = status, payload
    reply = Reply()
    handler.StockDashboardHandler.handle_watchlist_get(reply)
    assert reply.payload['stocks'][0]['pe_percentile_5y'] == 51.1
    assert reply.payload['stocks'][0]['relative_strength_as_of'] == '2026-11-12'
