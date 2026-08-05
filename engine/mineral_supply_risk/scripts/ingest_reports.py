# -*- coding: utf-8 -*-
"""보고서 폴더 텍스트 정형화 인제스터.
  python -m scripts.ingest_reports <root> <out_parquet> [--zips]
  - <root> 아래 .hwp/.pdf 텍스트 추출 → doc_raw 호환 스키마 parquet.
  - --zips: root 아래 .zip 내부의 .pdf 도 (해제 없이) 읽음.
  - 해시(md5) dedup, 폴더/파일명으로 source·commodity_hint·pub_date 추론.
재사용: 로컬에서도 동일 실행. 대용량은 시간 소요 → nohup 백그라운드 권장.
"""
import sys, os, io, re, hashlib, zipfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, pypdf
from msr.utils import hwp_extract as hx

BUDGET = float(os.environ.get("INGEST_BUDGET", "38"))   # 초; 이 시간 지나면 flush 후 종료(exit 3)
PDF_MAXPAGES = int(os.environ.get("PDF_MAXPAGES", "60"))

def infer_source(path):
    p = path.lower()
    if "우드맥킨지" in path or "woodmac" in p or "wood" in p: return "WoodMac"
    if "asian" in p: return "AsianMetal"
    if "argus" in p: return "Argus"
    if "iea" in p: return "IEA"
    if "komis" in p or any(k in path for k in ["주간광물","희소금속","전략광종","자원정보","광업요람"]): return "KOMIS"
    if "조달" in path or "pps" in p: return "PPS"
    return "ETC"

def infer_commodity(path):
    p = path.lower()
    if any(k in path for k in ["희토","네오디"]) or any(k in p for k in ["neod","rare","ree"]): return "REE"
    if "리튬" in path or "lithium" in p: return "LI"
    if "니켈" in path or "nickel" in p: return "NI"
    if "코발트" in path or "cobalt" in p: return "CO"
    if "동_" in path or "동/" in path or "copper" in p: return "CU"
    return None

_DATE = [
    (re.compile(r"(20\d{2})[._-]?(0[1-9]|1[0-2])[._-]?(0[1-9]|[12]\d|3[01])"), "%Y%m%d"),
    (re.compile(r"(20\d{2})[._-](0[1-9]|1[0-2])"), "%Y%m"),
]
_MONTHS = {m:i for i,m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}
def infer_date(name):
    for rx,_ in _DATE:
        m = rx.search(name)
        if m:
            g = m.groups()
            return f"{g[0]}-{g[1]}-{g[2]}" if len(g)==3 else f"{g[0]}-{g[1]}-01"
    m = re.search(r"([A-Za-z]{3})[a-z]*[-_ ](20\d{2})", name)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}-01"
    return None

def pdf_text(data):
    r = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((pg.extract_text() or "") for pg in r.pages[:PDF_MAXPAGES])

def hwp_text(data):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
        f.write(data); tmp=f.name
    try: return hx.extract_text(tmp)
    finally: os.unlink(tmp)

def make_row(name, path, fmt, data):
    txt = ""
    try:
        txt = (pdf_text(data) if fmt=="pdf" else hwp_text(data)) or ""
    except Exception as e:
        return dict(status="error", error_msg=str(e)[:200], raw_text="",
                    file_name=name, file_path=path, fmt=fmt,
                    file_hash=hashlib.md5(data).hexdigest(),
                    doc_id=hashlib.md5(data).hexdigest()[:16],
                    source=infer_source(path), commodity_hint=infer_commodity(path),
                    pub_date=infer_date(name), n_chars=0)
    h = hashlib.md5(data).hexdigest()
    return dict(doc_id=h[:16], source=infer_source(path), commodity_hint=infer_commodity(path),
                pub_date=infer_date(name), fmt=fmt, file_name=name, file_path=path,
                file_hash=h, raw_text=txt, n_chars=len(txt),
                status="analyzed" if len(txt)>0 else "hold", error_msg="")

def walk(root, do_zips):
    for dp,_,fns in os.walk(root):
        for fn in fns:
            fp=os.path.join(dp,fn); low=fn.lower()
            if low.endswith(".pdf") or low.endswith(".hwp"):
                yield fn, fp, ("pdf" if low.endswith(".pdf") else "hwp"), None
            elif do_zips and low.endswith(".zip"):
                try:
                    with zipfile.ZipFile(fp) as z:
                        for m in z.namelist():
                            if m.lower().endswith(".pdf"):
                                yield os.path.basename(m), f"{fp}::{m}", "pdf", z.read(m)
                except Exception as e:
                    print("  [zip err]", fp, e, flush=True)

def main():
    root=sys.argv[1]; out=sys.argv[2]; do_zips="--zips" in sys.argv[3:]
    t0=time.time()
    # 재개: 기존 parquet의 file_path/hash 로드
    done_paths=set(); done_hash=set(); prev=None
    if os.path.exists(out):
        prev=pd.read_parquet(out)
        done_paths=set(prev["file_path"]); done_hash=set(prev["file_hash"])
    rows=[]; n=0; timed_out=False
    for name, path, fmt, data in walk(root, do_zips):
        if path in done_paths: continue
        if data is None:
            with open(path,"rb") as f: data=f.read()
        h=hashlib.md5(data).hexdigest()
        if h in done_hash:
            done_paths.add(path); continue
        done_hash.add(h); done_paths.add(path)
        rows.append(make_row(name, path, fmt, data)); n+=1
        if n%25==0: print(f"  +{n} (last: {name[:45]}) {time.time()-t0:.0f}s", flush=True)
        if time.time()-t0 > BUDGET:
            timed_out=True; break
    # flush
    df = pd.concat([prev, pd.DataFrame(rows)], ignore_index=True) if prev is not None else pd.DataFrame(rows)
    if len(df.columns): df.to_parquet(out, index=False)
    print(f"\n이번 실행 +{n}건 | 누적 {len(df)}건 | {'PARTIAL(더 있음)' if timed_out else 'DONE(폴더 완료)'}", flush=True)
    if len(df):
        print("status:", df["status"].value_counts().to_dict())
    sys.exit(3 if timed_out else 0)

if __name__=="__main__": main()
