from pathlib import Path
from scripts import build_industry_relative_valuation_snapshot as cli
from app.search import index


def test_offline_industry_publication_never_requests_live_quotes(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('daily snapshot must not request a live quote')
    monkeypatch.setattr(index,'_load_realtime_quote_snapshot',forbidden)
    calls=[]
    def build(**kwargs):
        calls.append(index._load_realtime_quote_snapshot('sh','600000'))
        return Path('unused-test-output.json')
    monkeypatch.setattr(cli,'write_current_industry_snapshots',build)
    cli.main([])
    assert calls==[None]
    assert index._load_realtime_quote_snapshot is forbidden
