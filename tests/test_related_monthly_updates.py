import math,re,tempfile,unittest
from pathlib import Path
from app.data.external_risk_updates import update_external_risk

class MonthlyRelatedTests(unittest.TestCase):
 def feed(self, change=False, always=False):
  calls=[]; bumps=[0]
  base=[{'SECURITY_CODE':'000001','NOTICE_DATE':'2026-01-03','TRADE_AMT':'0.57'}, {'SECURITY_CODE':'000002','NOTICE_DATE':'2026-10-24','TRADE_AMT':None}]
  def fetch(p):
   calls.append(dict(p)); dates=re.findall(r"2026-\d\d-\d\d",p['filter']);lo,hi=dates[0],dates[1]
   if lo=='2026-10-01' and (always or (int(p['pageSize'])==1 and change and not bumps[0])):bumps[0]+=1
   rows=base+[{'SECURITY_CODE':f'{i+3:06d}','NOTICE_DATE':'2026-10-24','TRADE_AMT':'1'} for i in range(bumps[0])]
   selected=sorted([r for r in rows if lo<=r['NOTICE_DATE']<=hi],key=lambda r:(r['NOTICE_DATE'],r['SECURITY_CODE']),reverse=True)
   # Exact same sorting as the production query for same-date codes.
   selected=sorted(selected,key=lambda r:(-int(r['NOTICE_DATE'].replace('-','')),r['SECURITY_CODE']))
   size=int(p['pageSize']); start=(int(p['pageNumber'])-1)*size
   return {'success':True,'result':{'count':len(selected),'pages':math.ceil(len(selected)/size),'data':selected[start:start+size]}}
  return fetch,calls
 def test_monthly_snapshot_keeps_empty_months_and_exact_annual_count(self):
  fetch,calls=self.feed()
  with tempfile.TemporaryDirectory() as td:
   m=update_external_risk('related_transactions',root=td,fetcher=fetch,download_strategy='monthly',progress=lambda _:None)
   self.assertEqual(2,m['row_count']); self.assertEqual(10,len(m['partitions']))
   self.assertTrue(m['partitioned']);self.assertEqual('2026-10-24',m['announcement_end'])
   self.assertTrue((Path(m['snapshot_path'])/'raw/final_annual_recheck.json').exists())
 def test_changed_month_is_refreshed_without_replaying_stable_january(self):
  fetch,calls=self.feed(change=True)
  with tempfile.TemporaryDirectory() as td:
   m=update_external_risk('related_transactions',root=td,fetcher=fetch,download_strategy='monthly',progress=lambda _:None)
   self.assertEqual(3,m['row_count'])
   january=[p for p in calls if "NOTICE_DATE>='2026-01-01'" in p['filter'] and "NOTICE_DATE<='2026-01-31'" in p['filter'] and p['pageSize']=='500']
   self.assertEqual(2,len(january)) # initial page and stable first-page recheck only
 def test_continuously_changing_partition_cannot_replace_trusted_pointer(self):
  fetch,_=self.feed()
  with tempfile.TemporaryDirectory() as td:
   update_external_risk('related_transactions',root=td,fetcher=fetch,download_strategy='monthly',progress=lambda _:None)
   pointer=Path(td)/'related_transactions/current.json';old=pointer.read_bytes()
   bad,_=self.feed(always=True)
   with self.assertRaisesRegex(ValueError,'stabil'):
    update_external_risk('related_transactions',root=td,fetcher=bad,download_strategy='monthly',progress=lambda _:None)
   self.assertEqual(old,pointer.read_bytes())
 def large_feed(self, change_second_page=False, bad_tail=False):
  calls=[]; changed=[False]
  rows=[{'SECURITY_CODE':'000001','NOTICE_DATE':'2026-01-03','TRADE_AMT':'0.57'}]+[{'SECURITY_CODE':f'{i:06d}','NOTICE_DATE':'2026-10-24','TRADE_AMT':None} for i in range(2,503)]
  def fetch(p):
   calls.append(dict(p)); lo,hi=re.findall(r"2026-\d\d-\d\d",p['filter'])[:2]
   page=int(p['pageNumber']); size=int(p['pageSize'])
   if change_second_page and not changed[0] and lo=='2026-10-01' and page==2:
    rows.append({'SECURITY_CODE':'000999','NOTICE_DATE':'2026-10-24','TRADE_AMT':'1'});changed[0]=True
   selected=sorted([r for r in rows if lo<=str(r['NOTICE_DATE'])<=hi],key=lambda r:(-int(str(r['NOTICE_DATE']).replace('-','')),str(r['SECURITY_CODE'])))
   data=selected[(page-1)*size:page*size]
   if bad_tail and lo=='2026-10-01' and page==2:data=data[:-1]
   return {'success':True,'result':{'count':len(selected),'pages':math.ceil(len(selected)/size),'data':data}}
  return fetch,calls
 def test_multpage_count_change_retries_october_not_stable_january(self):
  fetch,calls=self.large_feed(change_second_page=True)
  with tempfile.TemporaryDirectory() as td:
   m=update_external_risk('related_transactions',root=td,fetcher=fetch,download_strategy='monthly',progress=lambda _:None)
   self.assertEqual(503,m['row_count']);self.assertEqual(502,m['partitions']['2026-10']['row_count'])
   self.assertEqual(2,m['partitions']['2026-10']['pages']);self.assertTrue(m['partitions']['2026-10']['path'].endswith('attempt_2'))
   january=[p for p in calls if "NOTICE_DATE<='2026-01-31'" in p['filter'] and p['pageSize']=='500']
   self.assertEqual(2,len(january))
 def test_multpage_bad_tail_preserves_current_metadata_and_manifest(self):
  import hashlib,json
  with tempfile.TemporaryDirectory() as td:
   good,_=self.large_feed();m=update_external_risk('related_transactions',root=td,fetcher=good,download_strategy='monthly',progress=lambda _:None)
   pointer=Path(td)/'related_transactions/current.json';old=pointer.read_bytes();snapshot=Path(m['snapshot_path'])
   metadata=(snapshot/'metadata.json').read_bytes();manifest=(snapshot/'sha256_manifest.json').read_bytes()
   bad,_=self.large_feed(bad_tail=True)
   with self.assertRaisesRegex(ValueError,'tail'):
    update_external_risk('related_transactions',root=td,fetcher=bad,download_strategy='monthly',progress=lambda _:None)
   self.assertEqual(old,pointer.read_bytes());self.assertEqual(metadata,(snapshot/'metadata.json').read_bytes());self.assertEqual(manifest,(snapshot/'sha256_manifest.json').read_bytes())
   self.assertEqual(hashlib.sha256(metadata).hexdigest(),json.loads(manifest)['metadata.json'])
if __name__=='__main__':unittest.main()
