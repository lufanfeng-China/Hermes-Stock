#!/usr/bin/env python3
"""Build current-mapping theme risk clusters from Tongdaxin concept membership."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping
from app.concept_theme_clusters import build_theme_clusters


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--threshold',type=float,default=.35)
    p.add_argument('--output',type=Path,default=ROOT/'data/derived/datasets/final/dataset_concept_theme_clusters_current.json')
    a=p.parse_args()
    mapping_path=Path('/mnt/c/new_tdx64/T0002/export/概念板块.txt')
    mapping=parse_tdx_concept_mapping(mapping_path.read_text(encoding='gb18030'))
    result=build_theme_clusters(mapping,a.threshold)
    result.update({'source':'current_tdx_concept_mapping','source_path':str(mapping_path),'historical_membership_verified':False,'concept_count':len(result['concept_to_cluster'])})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(a.output),'concepts':result['concept_count'],'clusters':len(result['clusters']),'multi_concept_clusters':sum(c['concept_count']>1 for c in result['clusters']),'threshold':a.threshold},ensure_ascii=False))
if __name__=='__main__':main()
