"""Independent, auditable manual snapshots. No scheduler or strategy integration."""
import csv
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

DATASETS = ('company_pledge', 'related_transactions')
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'data' / 'external_risk'
API = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
SCOPES = {
    'company_pledge': '公司整体未解押统计；非大股东个人持股质押率；数量万股、市值万元、比例百分点；逐行数据日期，缺记录/NULL不等于0',
    'related_transactions': '仅2026年公告明细，非交易发生年；TRADE_AMT万原币乘10000，营收/净利润元不放大；混合类型不得求和除营收；EID非唯一；缺记录不等于0',
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_float=Decimal)


def _dump(path, obj):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, default=str, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _digest(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_external_risk_status(root=None):
    """Only two tiny pointer/last-attempt files per dataset, never scan rows."""
    root = Path(root) if root is not None else DEFAULT_ROOT
    result = {}
    for dataset in DATASETS:
        entry = dict(updated_at=None, data_date=None, row_count=0, company_count=0,
                     latest_date_rows=0, older_date_rows=0, snapshot_path=None,
                     error=None, warning=None, source_scope=SCOPES[dataset], available=False)
        try:
            entry.update(_json(root / dataset / 'current.json'))
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            entry['error'] = str(exc)
        try:
            attempt = _json(root / dataset / 'last_attempt.json')
            if attempt.get('error'):
                entry['error'] = attempt['error']
        except (OSError, ValueError):
            pass
        result[dataset] = entry
    return result


def _pages(directory):
    return sorted((directory / 'raw').glob('page_*.json'),
                  key=lambda p: int(re.search(r'page_(\d+)', p.name).group(1)))


def _read_pages(directory):
    files = [p for p in _pages(directory) if re.fullmatch(r'page_\d+\.json', p.name)]
    _require(bool(files), 'missing raw pages')
    rows = []
    count = pages = None
    for n, path in enumerate(files, 1):
        _require(int(re.search(r'page_(\d+)', path.name).group(1)) == n, 'page sequence gap')
        payload = _json(path)
        _require(payload.get('success') is True and isinstance(payload.get('result'), dict), 'API failure')
        r = payload['result']
        if count is None:
            count, pages = int(r['count']), int(r['pages'])
            _require(count > 0 and pages == math.ceil(count / 500), 'empty data or invalid pages')
        _require((r['count'], r['pages']) == (count, pages), 'source count/pages changed')
        _require(n <= pages and len(r['data']) == min(500, count - (n - 1) * 500), 'invalid tail/page length')
        rows.extend(r['data'])
    _require(len(files) == pages and len(rows) == count, 'incomplete pagination')
    return rows


def _csv_value(value):
    return '' if value is None else str(value)


PLEDGE_CSV = dict(SECURITY_CODE='股票代码', SECURITY_NAME_ABBR='股票名称', SECUCODE='市场代码', TRADE_DATE='数据日期', PLEDGE_RATIO='质押比例(%)', REPURCHASE_BALANCE='质押总股数(万股)', PLEDGE_DEAL_NUM='质押笔数', REPURCHASE_UNLIMITED_BALANCE='无限售质押股数(万股)', REPURCHASE_LIMITED_BALANCE='限售质押股数(万股)', PLEDGE_MARKET_CAP='质押市值(万元)', INDUSTRY='所属行业', Y1_CLOSE_ADJCHRATE='近一年涨跌幅(%)')
RELATED_CSV = dict(SECURITY_CODE='股票代码', SECURITY_NAME_ABBR='股票名称', SECUCODE='市场代码', NOTICE_DATE='公告日期', END_DATE='来源截止日期_END_DATE', RELATED_PARTY='关联方', RELATED_RELATION='关联关系', IS_CONTROL='是否控制_来源原值', TRADE_WAY='交易方式', TRADE_PROFILE='交易内容', TRADE_AMT='交易金额原值_万原币', CURRENCY='币种代码', CURRENCY_NAME='币种名称', PAY_WAY='支付方式', PRICE_BASIS='定价依据', OPERATE_INCOME='参考营业收入_元_期间待核', NETPROFIT='参考净利润_元_期间待核', DATE_TYPE_CODE='来源财报期间代码_未解码', TRADE_START_DATE='来源交易开始日期', EID='来源事件ID_非唯一行键')


def _check_source_csv_fields(records, rows, mapping):
    if not records:
        raise ValueError('empty CSV fields')
    selected = [(key, label) for key, label in mapping.items() if label in records[0]]
    expected = Counter(tuple(_csv_value(r.get(key)) for key, _ in selected) for r in rows)
    actual = Counter(tuple(r[label] for _, label in selected) for r in records)
    _require(actual == expected, 'CSV fields/raw multiplicity mismatch')


def _import_archive(source, run, dataset):
    source = Path(source).resolve()
    manifest = _json(source / 'sha256_manifest.json')
    _require(isinstance(manifest, dict) and bool(manifest), 'missing hash manifest')
    for name, expected in manifest.items():
        _require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'unsafe hash path')
        path = (source / name).resolve()
        _require(path.is_relative_to(source) and path.is_file(), 'unsafe/missing hash path')
        _require(_hash(path) == expected, 'hash mismatch: ' + name)
    rawfiles = [p for p in _pages(source) if re.fullmatch(r'page_\d+\.json', p.name)]
    required = ['verification.json'] + [str(p.relative_to(source)) for p in rawfiles]
    primary = 'company_pledge_latest.json' if dataset == 'company_pledge' else 'related_transactions_2026.jsonl.gz'
    required.append(primary)
    if (source / 'config.json').exists():
        required.append('config.json')
    for name in required:
        _require(name in manifest, 'unhashed required artifact: ' + name)
    verification = _json(source / 'verification.json')
    _require(verification.get('passed') is True, 'source verification not passed')
    rows = _read_pages(source)
    _require(len(rows) == verification['downloaded_rows'], 'verification row count mismatch')
    raw_counter = Counter(map(_digest, rows))
    if dataset == 'company_pledge':
        primary_rows = _json(source / primary)['data']
    else:
        with gzip.open(source / primary, 'rt', encoding='utf-8') as f:
            primary_rows = [json.loads(line, parse_float=Decimal) for line in f]
    _require(Counter(map(_digest, primary_rows)) == raw_counter, 'primary/raw duplicate multiplicity mismatch')
    # Existing Chinese CSVs are independently checked, including repeated row counts.
    for csvpath in source.glob('*.csv'):
        if dataset == 'related_transactions' and '明细' in csvpath.name:
            with csvpath.open(encoding='utf-8-sig', newline='') as f:
                records = list(csv.DictReader(f))
            _check_source_csv_fields(records, rows, RELATED_CSV)
            _require(csvpath.name in manifest, 'unhashed CSV artifact')
            _require(Counter(r['整行内容SHA256'] for r in records) == raw_counter, 'CSV/raw multiplicity mismatch')
            for r in records:
                a, b = r['交易金额原值_万原币'], r['交易金额换算值_元原币']
                _require((not a and not b) or (bool(a) and bool(b) and Decimal(b) == Decimal(a) * 10000), 'CSV unit conversion mismatch')
        elif dataset == 'company_pledge' and csvpath.name == '公司整体质押_最新.csv':
            with csvpath.open(encoding='utf-8-sig', newline='') as f:
                records = list(csv.DictReader(f))
            _check_source_csv_fields(records, rows, PLEDGE_CSV)
            _require(csvpath.name in manifest, 'unhashed CSV artifact')
    # Copy evidence/data only; never import or execute source scripts.
    for name in manifest:
        path = source / name
        if path.suffix.lower() in ('.json', '.gz', '.csv'):
            target = run / 'import_evidence' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    shutil.copyfile(source / 'sha256_manifest.json', run / 'import_evidence/sha256_manifest.json')
    for path in rawfiles:
        shutil.copyfile(path, run / 'raw' / path.name)
    config = _json(source / 'config.json') if (source / 'config.json').exists() else {}
    if dataset == 'related_transactions' and (source / 'config.json').exists():
        cutoff = config.get('announcement_end')
        _require(isinstance(cutoff, str) and bool(re.fullmatch(r'2026-\d{2}-\d{2}', cutoff)), 'invalid announcement cutoff')
        date.fromisoformat(str(cutoff))
    return rows, dict(imported_from=str(source), source_downloaded_at=verification.get('downloaded_at') or config.get('started_at'), announcement_end=config.get('announcement_end'))


def _export(run, dataset, rows, extra, progress):
    date_field = 'TRADE_DATE' if dataset == 'company_pledge' else 'NOTICE_DATE'
    dates = Counter()
    codes = Counter()
    raw_counts = Counter(map(_digest, rows))
    for row in rows:
        code = row.get('SECURITY_CODE', '')
        _require(isinstance(code, str) and len(code) == 6 and code.isdigit(), 'invalid security code')
        day = str(row.get(date_field, ''))[:10]
        date.fromisoformat(day)
        if dataset == 'related_transactions':
            _require('2026-01-01' <= day <= '2026-12-31' and day <= (extra.get('announcement_end') or '2026-12-31'), 'outside announcement scope')
        dates[day] += 1
        codes[code] += 1
    if dataset == 'company_pledge':
        _require(len(codes) == len(rows), 'duplicate company pledge rows')
    fields = sorted({key for row in rows for key in row})
    if dataset == 'related_transactions':
        fields += ['_AMOUNT_UNITS']
    fields += ['_ROW_HASH']
    progress('[2/3] 开始构建导出与逐行读回校验（保留重复与NULL）')
    partitions = {}
    try:
        with (run / 'data.csv').open('w', encoding='utf-8-sig', newline='') as cf, gzip.open(run / 'data.jsonl.gz', 'wt', encoding='utf-8') as jf:
            writer = csv.DictWriter(cf, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                exported = dict(row)
                if dataset == 'related_transactions':
                    value = row.get('TRADE_AMT')
                    exported['_AMOUNT_UNITS'] = None if value is None else format(Decimal(str(value)) * 10000, 'f')
                exported['_ROW_HASH'] = _digest(row)
                writer.writerow(exported)
                text = json.dumps(exported, ensure_ascii=False, default=str) + '\n'
                jf.write(text)
                if dataset == 'company_pledge':
                    day = row[date_field][:10]
                    if day not in partitions:
                        (run / 'by_date').mkdir(exist_ok=True)
                        partitions[day] = (run / 'by_date' / (day + '.jsonl')).open('w', encoding='utf-8')
                    partitions[day].write(text)
    finally:
        for f in partitions.values():
            f.close()
    with (run / 'data.csv').open(encoding='utf-8-sig', newline='') as f:
        read_csv = list(csv.DictReader(f))
    _require(Counter(r['_ROW_HASH'] for r in read_csv) == raw_counts, 'CSV readback mismatch')
    _check_source_csv_fields(read_csv, rows, {key: key for key in fields if not key.startswith('_')})
    with gzip.open(run / 'data.jsonl.gz', 'rt', encoding='utf-8') as f:
        read_json = [json.loads(line, parse_float=Decimal) for line in f]
    restored = []
    for row in read_json:
        row.pop('_ROW_HASH')
        row.pop('_AMOUNT_UNITS', None)
        restored.append(_digest(row))
    _require(Counter(restored) == raw_counts, 'JSONL readback mismatch')
    for row in read_csv:
        if dataset == 'related_transactions':
            a, b = row.get('TRADE_AMT'), row['_AMOUNT_UNITS']
            _require((not a and not b) or (bool(a) and bool(b) and Decimal(b) == Decimal(a) * 10000), 'amount conversion mismatch')
    latest = max(dates)
    coverage = dict(company_records=dict(codes), date_distribution=dict(sorted(dates.items())),
                    currencies=dict(Counter(str(r.get('CURRENCY')) for r in rows)),
                    trade_ways=dict(Counter(str(r.get('TRADE_WAY')) for r in rows)))
    _dump(run / 'coverage.json', coverage)
    return dict(data_date=latest, row_count=len(rows), company_count=len(codes),
                latest_date_rows=dates[latest], older_date_rows=len(rows)-dates[latest],
                date_distribution=dict(sorted(dates.items())),
                exact_duplicate_rows_preserved=len(rows)-len(raw_counts))


class PublicAPIClient:
    """Public GET only; starts >=2s apart including retries, 3 attempts, 40s timeout."""
    def __init__(self):
        self.last_start = None
        self.last_body = None

    def __call__(self, params):
        url = API + '?' + urllib.parse.urlencode(params)
        for attempt in range(3):
            if self.last_start is not None:
                wait = 2 - (time.monotonic() - self.last_start)
                if wait > 0:
                    time.sleep(wait)
            self.last_start = time.monotonic()
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'})
                with urllib.request.urlopen(request, timeout=40) as response:
                    _require(response.status == 200, 'HTTP status not 200')
                    body = response.read()
                payload = json.loads(body, parse_float=Decimal)
                _require(payload.get('success') is True and isinstance(payload.get('result'), dict), 'API failure: ' + str(payload.get('message')))
                self.last_body = body
                return payload
            except (OSError, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))


def _download(run, dataset, fetcher, progress):
    fetcher = fetcher or PublicAPIClient()
    related = dataset == 'related_transactions'
    params = dict(reportName='RPT_RELATED_TRADE' if related else 'RPT_CSDC_LIST_NEWEST',
                  columns='ALL', pageSize='500', pageNumber='1', source='WEB', client='WEB',
                  sortColumns='NOTICE_DATE,SECURITY_CODE,EID,RELATED_PARTY,TRADE_WAY,END_DATE,TRADE_AMT' if related else 'SECURITY_CODE,SECUCODE',
                  sortTypes='-1,1,-1,1,1,-1,-1' if related else '1,1')
    extra = dict(source_downloaded_at=_now())
    def request(query, filename):
        payload = fetcher(dict(query))
        _require(payload.get('success') is True and isinstance(payload.get('result'), dict), 'API failure')
        path = run / 'raw' / filename
        if isinstance(fetcher, PublicAPIClient) and fetcher.last_body is not None:
            path.write_bytes(fetcher.last_body)
        else:
            _dump(path, payload)
        _dump(path.with_name(path.stem + '_request.json'), dict(params=query, url=API + '?' + urllib.parse.urlencode(query), fetched_at=_now()))
        return payload['result']
    if related:
        params['filter'] = "(NOTICE_DATE>='2026-01-01')(NOTICE_DATE<='2026-12-31')"
        probe = request(dict(params, pageSize='1'), 'initial_latest_probe.json')
        _require(bool(probe.get('data')), 'empty announcement data')
        latest = str(probe['data'][0]['NOTICE_DATE'])[:10]
        _require('2026-01-01' <= latest <= '2026-12-31', 'outside announcement scope')
        params['filter'] = "(NOTICE_DATE>='2026-01-01')(NOTICE_DATE<='" + latest + "')"
        extra['announcement_start'] = '2026-01-01'
        extra['announcement_end'] = latest
    first = request(params, 'page_0001.json')
    count, pages = int(first['count']), int(first['pages'])
    _require(count > 0 and pages == math.ceil(count / 500), 'empty data or invalid pages')
    _require(len(first['data']) == min(500, count), 'invalid tail/page length')
    for n in range(2, pages + 1):
        progress('[1/3] 下载分页 %d/%d，已冻结全快照口径' % (n, pages))
        r = request(dict(params, pageNumber=str(n)), 'page_%04d.json' % n)
        _require((r['count'], r['pages']) == (count, pages), 'source count/pages changed')
        _require(len(r['data']) == min(500, count-(n-1)*500), 'invalid tail/page length')
    rows = _read_pages(run)
    progress('[1/3] 完成分页，开始首屏与总数复核')
    final = request(params, 'final_first_page_recheck.json')
    _require((final['count'], final['pages']) == (count, pages), 'source count/pages changed at final recheck')
    _require(final['data'] == first['data'], 'first page changed during download')
    _dump(run / 'config.json', dict(params=params, count=count, pages=pages, **extra))
    return rows, extra


def update_external_risk(dataset, root=None, import_from=None, *, fetcher=None, progress=print, download_strategy="full"):
    """Publish a validated full snapshot; raises on failure, preserving prior current.

    fetcher(params)->API dict is injectable for offline tests only. Production uses
    the rate-limited public HTTP client. root is the external_risk directory itself.
    """
    _require(dataset in DATASETS, 'unknown dataset')
    root = Path(root).resolve() if root is not None else DEFAULT_ROOT
    base = root / dataset
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('dataset update already running: ' + dataset) from exc
        run = base / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid4().hex[:10])
        (run / 'raw').mkdir(parents=True)
        started = _now()
        _dump(base / 'last_attempt.json', dict(started_at=started, snapshot_path=str(run), error=None, complete=False))
        try:
            progress('[1/3] 开始构建' + dataset + ('：导入既有归档（不是网络新拉取）' if import_from else '：联网全快照'))
            if import_from:
                rows, extra = _import_archive(import_from, run, dataset)
            elif dataset == 'related_transactions' and download_strategy == 'monthly':
                from app.data.related_trade_partitions import download_related_monthly
                rows, extra = download_related_monthly(run, fetcher, progress)
            else:
                rows, extra = _download(run, dataset, fetcher, progress)
            stats = _export(run, dataset, rows, extra, progress)
            metadata = dict(stats, **extra, dataset=dataset, updated_at=_now(), started_at=started,
                            acquisition_mode='import' if import_from else 'network_full_snapshot',
                            snapshot_path=str(run), source_scope=SCOPES[dataset],
                            warning='逐行日期不同，较早值不代表当前；缺记录不等于0' if dataset == 'company_pledge' else '公告年非发生年；混合交易不计算收入占比；不按EID去重',
                            error=None, available=True, complete=True)
            _dump(run / 'metadata.json', metadata)
            manifest = {str(p.relative_to(run)): _hash(p) for p in run.rglob('*') if p.is_file()}
            _dump(run / 'sha256_manifest.json', manifest)
            _require(all(_hash(run / n) == h for n, h in manifest.items()), 'output hash readback mismatch')
            _dump(base / 'last_attempt.json', metadata)
            # Atomic current replacement is the publication commit point.
            _dump(base / 'current.json', metadata)
        except Exception as exc:
            failure = dict(started_at=started, updated_at=_now(), snapshot_path=str(run), error=str(exc), complete=False)
            _dump(run / 'metadata.json', failure)
            _dump(base / 'last_attempt.json', failure)
            progress('[3/3] 失败：' + str(exc))
            raise
        # Post-commit output cannot invalidate immutable metadata or its manifest.
        try:
            progress('[3/3] 完成：校验通过并原子发布 ' + str(run))
        except Exception:
            pass
        return metadata
