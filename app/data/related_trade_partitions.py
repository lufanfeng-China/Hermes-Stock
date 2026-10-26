"""Bounded monthly snapshots for a changing 2026 announcement source."""
import calendar
from datetime import date
from pathlib import Path
from app.data.external_risk_updates import PublicAPIClient, API, _dump, _require, _read_pages, _now
import urllib.parse


def download_related_monthly(run, fetcher, progress):
    fetcher = fetcher or PublicAPIClient()
    base = dict(reportName='RPT_RELATED_TRADE', columns='ALL',pageSize='500',pageNumber='1',source='WEB',client='WEB',sortColumns='NOTICE_DATE,SECURITY_CODE,EID,RELATED_PARTY,TRADE_WAY,END_DATE,TRADE_AMT',sortTypes='-1,1,-1,1,1,-1,-1')
    def ask(query, path):
        payload=fetcher(dict(query));_require(payload.get('success') is True and isinstance(payload.get('result'),dict),'API failure')
        path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(fetcher,PublicAPIClient):path.write_bytes(fetcher.last_body)
        else:_dump(path,payload)
        _dump(path.with_name(path.stem+'_request.json'),dict(params=query,url=API+'?'+urllib.parse.urlencode(query),fetched_at=_now()))
        return payload['result']
    def filtered(lo,hi):return dict(base,filter=f"(NOTICE_DATE>='{lo}')(NOTICE_DATE<='{hi}')")
    probe=ask(dict(filtered('2026-01-01','2026-12-31'),pageSize='1'),run/'raw/initial_latest_probe.json')
    _require(probe.get('data') and probe['count']>0,'empty announcement data')
    end=probe['data'][0]['NOTICE_DATE'][:10];_require('2026-01-01'<=end<='2026-12-31','outside announcement scope')
    ranges={f'2026-{m:02d}':(f'2026-{m:02d}-01',min(f'2026-{m:02d}-{calendar.monthrange(2026,m)[1]}',end)) for m in range(1,date.fromisoformat(end).month+1)}
    rows_by_month={};parts={};attempts={k:0 for k in ranges}
    def collect(month):
        lo,hi=ranges[month];query=filtered(lo,hi)
        for retry in range(3):
            attempts[month]+=1;directory=run/'partitions'/month/f'attempt_{attempts[month]}'
            first=ask(query,directory/'raw/page_0001.json');count=int(first['count']);pages=int(first['pages'])
            _require(count>=0 and (count>0 or not first.get('data')),'invalid empty month')
            try:
                if count:
                    import math
                    _require(pages==math.ceil(count/500),'invalid month pages')
                    for n in range(2,pages+1):
                        progress(f'[1/3] {month} 下载分页 {n}/{pages}；按月完整校验')
                        r=ask(dict(query,pageNumber=str(n)),directory/f'raw/page_{n:04d}.json')
                        _require((r['count'],r['pages'])==(count,pages),'source count/pages changed')
                    rows=_read_pages(directory)
                else:rows=[]
                final=ask(query,directory/'raw/final_first_page_recheck.json')
                _require(final['count']==count and final.get('data')==first.get('data'),'month changed during download')
                _require(all(lo<=r['NOTICE_DATE'][:10]<=hi for r in rows),'outside month scope')
                rows_by_month[month]=rows
                parts[month]=dict(path=str(directory.relative_to(run)),row_count=count,pages=pages,announcement_start=lo,announcement_end=hi)
                progress(f'[1/3] {month} 完成 {count}条；保留重复及空月份')
                return
            except ValueError as exc:
                if 'changed' not in str(exc):raise
                progress(f'[1/3] {month} 来源变化，重试该月 {retry+1}/3')
        raise ValueError('month did not stabilize: '+month)
    for month in ranges:collect(month)
    for sweep in range(3):
        for month,(lo,hi) in ranges.items():
            check=ask(dict(filtered(lo,hi),pageSize='1'),run/f'raw/reconcile_{sweep}_{month}.json')
            if check['count']!=parts[month]['row_count']:collect(month)
        annual=ask(dict(filtered('2026-01-01',end),pageSize='1'),run/f'raw/annual_recheck_{sweep}.json')
        total=sum(p['row_count'] for p in parts.values())
        if annual['count']==total:
            rows=[r for month in ranges for r in rows_by_month[month]]
            # The annual leading row must also be present in the current last month.
            _require(annual.get('data') and annual['data'][0] in rows_by_month[max(ranges)],'annual leading row changed')
            _dump(run/'raw/final_annual_recheck.json',dict(success=True,result=annual))
            extra=dict(partitioned=True,partitions=parts,announcement_start='2026-01-01',announcement_end=end,source_downloaded_at=_now(),annual_count=total)
            _dump(run/'config.json',dict(**extra,query=filtered('2026-01-01',end)))
            return rows,extra
    raise ValueError('annual/month counts did not stabilize')
