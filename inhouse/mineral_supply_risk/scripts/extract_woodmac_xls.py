# -*- coding: utf-8 -*-
"""우드맥킨지 수급/가격 모델 워크북(xls) → long 시계열 추출.
  python -m scripts.extract_woodmac_xls <glob_root> <out_parquet>
연도 헤더행을 자동탐지하고, 각 데이터행(품목 라벨)을 연도별로 melt.
출력: commodity, src_file, sheet, line_item, year, value
"""
import sys, os, glob, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np

def commodity_of(path):
    p=path.lower()
    if "동" in path or "copper" in p: return "CU"
    if "니켈" in path or "nickel" in p: return "NI"
    if "리튬" in path or "lithium" in p: return "LI"
    if "코발트" in path or "cobalt" in p: return "CO"
    return None

def is_year(v):
    try: iv=int(float(v))
    except: return False
    return 1975 <= iv <= 2040 and float(v)==iv

def label_of(row, first_year_col):
    for i in range(min(first_year_col, 4)):
        v=row[i]
        if isinstance(v,str) and len(v.strip())>2 and not is_year(v):
            return v.strip()
    return None

def extract_sheet(df, commodity, src, sheet):
    out=[]; ymap={}
    for _,row in df.iterrows():
        r=list(row.values)
        # 연도 헤더행 판정: 4자리 연도 셀 5개 이상
        yr_cols={i:int(float(v)) for i,v in enumerate(r) if is_year(v)}
        if len(yr_cols)>=5:
            ymap=yr_cols; continue
        if not ymap: continue
        first_year_col=min(ymap)
        lab=label_of(r, first_year_col)
        if not lab: continue
        for ci,yr in ymap.items():
            v=r[ci] if ci<len(r) else None
            if v is None or (isinstance(v,float) and np.isnan(v)): continue
            try: val=float(v)
            except: continue
            out.append(dict(commodity=commodity, src_file=src, sheet=sheet,
                            line_item=lab[:120], year=yr, value=val))
    return out

def main():
    root=sys.argv[1]; out=sys.argv[2]
    files=sorted(glob.glob(root, recursive=True))
    rows=[]
    for f in files:
        c=commodity_of(f); src=os.path.basename(f)
        try: xl=pd.ExcelFile(f)
        except Exception as e: print("  [skip]",src,e); continue
        for sh in xl.sheet_names:
            if sh.lower() in ("guidelines","guide","notes","cover"): continue
            try: d=xl.parse(sh, header=None)
            except Exception: continue
            got=extract_sheet(d, c, src, sh)
            if got: rows+=got; print(f"  {src} :: {sh} → {len(got)}행", flush=True)
    df=pd.DataFrame(rows)
    if len(df):
        df=df.drop_duplicates(["commodity","src_file","sheet","line_item","year"])
        df.to_parquet(out, index=False)
    print("\n=== 완료 총", len(df), "행 →", out)
    if len(df):
        print(df.groupby(["commodity","src_file"]).size().to_string())
        print("연도범위:", int(df.year.min()), "~", int(df.year.max()),
              "| 고유 line_item:", df.line_item.nunique())

if __name__=="__main__": main()
