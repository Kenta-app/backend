"""Combine the original annotated set with full-text external pairs."""
from __future__ import annotations
import argparse, pandas as pd

def main():
 p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--external',nargs='+',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 original=pd.read_csv(a.original); external=pd.concat([pd.read_csv(x) for x in a.external],ignore_index=True)
 for d in (original,external):
  same=d.label_annotator_1.str.lower()==d.label_annotator_2.str.lower()
  adj=d.adjudicated_label.fillna('').str.lower()
  if not (same | adj.isin(['agree','disagree','discuss','unrelated'])).all(): raise ValueError('Unadjudicated disagreement')
  d['adjudicated_label']=adj.where(adj!='',d.label_annotator_1.str.lower())
 out=pd.concat([original[['pair_id','claim','article','adjudicated_label']],external[['pair_id','claim','article','adjudicated_label']]],ignore_index=True)
 if out.pair_id.duplicated().any() or out.article.isna().any(): raise ValueError('Invalid combined data')
 out.to_csv(a.output,index=False);print(out.adjudicated_label.value_counts().to_dict())
if __name__=='__main__': main()
