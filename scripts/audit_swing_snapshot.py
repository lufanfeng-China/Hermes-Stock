#!/usr/bin/env python3
"""Independently compare a published v5 snapshot against frozen research CSV."""
from __future__ import annotations
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
BASELINE=Path('/mnt/c/Users/Sky.Lu/Desktop/output/swing_main_states_v5_2026-10-30.csv')
SNAPSHOT=ROOT/'data/derived/datasets/final/swing_structure_v6_current.json'


def audit(snapshot=SNAPSHOT, baseline=BASELINE):
    payload=json.loads(Path(snapshot).read_text(encoding='utf-8'))
    rows=list(csv.DictReader(Path(baseline).open(encoding='utf-8-sig',newline='')))
    errors=[]; comparison=Counter(); counts=Counter()
    if payload['as_of_date']!='2026-10-30' or payload['completeness']!='complete':
        errors.append('wrong date or incomplete snapshot')
    if len(rows)!=5383 or len(payload['stocks'])!=5383:
        errors.append('unexpected universe count')
    for row in rows:
        key=f"{row['market']}:{row['code']}"
        observed=payload['stocks'].get(key)
        if observed is None:
            errors.append(f'{key}: missing symbol')
            continue
        if row['status']!='ok':
            comparison['baseline_invalid']+=1
            if observed.get('status')=='ok':
                errors.append(f'{key}: baseline invalid but publication marked ok')
            continue
        comparison['baseline_valid']+=1
        if observed.get('status')!='ok':
            errors.append(f"{key}: {observed.get('status')} instead of ok")
            continue
        counts[observed['state']]+=1
        fields={'state':'new_state_v5','peak_shape':'peak_shape','valley_shape':'valley_shape',
                'selected_peaks':'selected_peaks','selected_valleys':'selected_valleys'}
        for observed_key, expected_key in fields.items():
            if str(observed[observed_key])!=row[expected_key]:
                errors.append(f'{key}: {observed_key} {observed[observed_key]!r} != {row[expected_key]!r}')
        for label, source in (('last_10_peaks','last_10_peaks_json'),('last_10_valleys','last_10_valleys_json')):
            expected=json.loads(row[source])
            actual=observed[label]
            if len(actual)!=len(expected):
                errors.append(f'{key}: {label} length')
                continue
            for a,b in zip(actual,expected):
                if a['date']!=b['date'] or a['confirmed']!=b['confirmed']:
                    errors.append(f'{key}: {label} occurrence/confirmation mismatch')
                    break
        comparison['full_rows_compared']+=1
    result={'result':'PASS' if not errors else 'FAIL','research_rows':len(rows),
            'snapshot_rows':len(payload['stocks']),'compared_valid':comparison['full_rows_compared'],
            'baseline_invalid':comparison['baseline_invalid'], 'distinct_states':len(counts),
            'box_states':counts['区间震荡'],'mismatches':len(errors),'examples':errors[:20],
            'coverage':payload['coverage']}
    return result


if __name__=='__main__':
    result=audit()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['result']=='PASS' else 1)
