# -*- coding: utf-8 -*-
"""
지정학 리스크 추출 파이프라인 (보고서 -> doc_raw -> geo_event)
단계:  ingest(수집) -> parse(섹션태깅) -> analyze(이벤트추출)
사용:
  python geo_pipeline.py --db minerals.duckdb --schema geo_schema.sql \
      ingest  --folder "<폴더>" --source AsianMetal --commodity LI
  python geo_pipeline.py --db minerals.duckdb parse
  python geo_pipeline.py --db minerals.duckdb analyze            # 규칙기반 baseline
  # LLM 사용 시: analyze 내부 extract_events에 llm_callable 주입 (하단 어댑터 참조)
의존성: duckdb, pdfplumber  (HWP는 사전에 PDF로 변환)
"""
import argparse, os, glob, re, hashlib, json, datetime as dt, uuid
import duckdb

# ---------- 공통 유틸 ----------
def file_hash(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for ch in iter(lambda:f.read(1<<16),b""): h.update(ch)
    return h.hexdigest()

MONTHS={m:i for i,m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],1)}
def parse_pub_date(name):
    """파일명에서 발행일 추정: 'DD-DD-Mon-YYYY' 끝 날짜, 'YYYYMMDD', 'YYMMDD'"""
    m=re.search(r"(\d{1,2})-(\d{1,2})-([A-Za-z]{3})-(20\d{2})", name)  # Asian Metal
    if m: return dt.date(int(m.group(4)), MONTHS.get(m.group(3).title(),1), int(m.group(2)))
    m=re.search(r"([A-Za-z]{3})-(\d{1,2})-(20\d{2})", name)
    if m: return dt.date(int(m.group(3)), MONTHS.get(m.group(1).title(),1), int(m.group(2)))
    m=re.search(r"(20\d{2})[-_ ]?(\d{2})[-_ ]?(\d{2})", name)
    if m: return dt.date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
    m=re.search(r"_(\d{2})(\d{2})(\d{2})", name)  # 160111 -> 2016
    if m: return dt.date(2000+int(m.group(1)),int(m.group(2)),int(m.group(3)))
    return None

# ---------- PDF 추출 (2단 컬럼 인식) ----------
def extract_pdf_text(path, columns=True):
    import pdfplumber
    out=[]
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            if columns:   # 2단 컬럼(Argus/AsianMetal)
                mid=p.width/2
                l=p.crop((0,0,mid,p.height)).extract_text() or ""
                r=p.crop((mid,0,p.width,p.height)).extract_text() or ""
                out.append(l+"\n"+r)
            else:         # 단단(KOMIS 등)
                out.append(p.extract_text() or "")
    return re.sub(r"[ \t]+"," ","\n".join(out))


# ---------- HWP 5.0 추출 (OLE+zlib+HWPTAG, 한글/MCP 불필요) ----------
def extract_hwp_text(path):
    import olefile, zlib, struct
    HWPTAG_PARA_TEXT=0x10+51
    EXT={1,2,3,11,12,14,15,16,17,18,21,22,23}; INL={4,5,6,7,8,9,19,20}
    CH={0,10,13,24,25,26,27,28,29,30,31}
    def recs(buf):
        p=0;n=len(buf)
        while p+4<=n:
            h=struct.unpack_from("<I",buf,p)[0];p+=4
            tag=h&0x3FF; size=(h>>20)&0xFFF
            if size==0xFFF: size=struct.unpack_from("<I",buf,p)[0];p+=4
            yield tag,buf[p:p+size];p+=size
    def dec(data):
        o=[];i=0;n=len(data)
        while i+1<n:
            c=data[i]|(data[i+1]<<8)
            if c in CH: o.append("\n" if c in (10,13) else " ");i+=2
            elif c in EXT or c in INL: i+=16
            else: o.append(chr(c));i+=2
        return "".join(o)
    ole=olefile.OleFileIO(path); comp=True
    try: comp=bool(ole.openstream("FileHeader").read()[36]&1)
    except: pass
    secs=sorted([e for e in ole.listdir() if len(e)==2 and e[0]=="BodyText"
                 and e[1].lower().startswith("section")],
                key=lambda e:int(re.sub(r"\D","",e[1]) or 0))
    parts=[]
    for e in secs:
        raw=ole.openstream(e).read()
        if comp:
            try: raw=zlib.decompress(raw,-15)
            except: pass
        for tag,data in recs(raw):
            if tag==HWPTAG_PARA_TEXT: parts.append(dec(data))
    ole.close()
    return re.sub(r"[ \t]+"," ","\n".join(parts))

SECTION_HEADERS=[r"\d+\.\s*Market Highlights", r"\d+\.\s*Economy and Policy",
                 r"\d+\.\s*Market Movements", r"\d+\.\d+\s+[A-Z]"]
def tag_sections(text):
    """숫자 헤더 기준 섹션 분할 -> [{seq,type,text}]"""
    pat=re.compile(r"(?m)^(\s*\d+\.(?:\d+)?\s+[^\n]{0,80})$")
    idxs=[(m.start(),m.group(1).strip()) for m in pat.finditer(text)]
    secs=[]
    if not idxs:
        return [{"seq":0,"type":"body","text":text.strip()}]
    for i,(pos,title) in enumerate(idxs):
        end=idxs[i+1][0] if i+1<len(idxs) else len(text)
        body=text[pos:end].strip()
        secs.append({"seq":i,"type":title[:60],"text":body})
    return secs

# ---------- 규칙기반 baseline 추출기 (LLM 미사용 시 동작) ----------
COUNTRIES=["China","Indonesia","Chile","Argentina","Australia","Zimbabwe",
           "Congo","DRC","United States","US","Bolivia","Brazil","Canada","Russia","Korea","Myanmar",
           "중국","인도네시아","인니","칠레","아르헨티나","호주","짐바브웨","콩고","미국","볼리비아",
           "브라질","러시아","미얀마","페루"]
EVENT_RULES=[  # (event_type, regex, base_severity, direction)  — 영문+한국어
    ("sanction",        r"sanction|embargo|제재|금수",                          0.90,"negative"),
    ("export_restriction", r"export ban|export control|export restrict|export quota|export tax|export licen|수출통제|수출제한|수출금지|수출쿼터|수출세|수출 제한", 0.85,"negative"),
    ("nationalization", r"nationali[sz]|state[- ]control|government takeover|국유화", 0.85,"negative"),
    ("conflict",        r"\bwar\b|conflict|coup|unrest|protest|civil|전쟁|분쟁|내전|쿠데타|소요|시위", 0.80,"negative"),
    ("supply_disruption", r"strike|shutdown|mine closure|force majeure|disruption|outage|suspend|halt|파업|가동중단|생산차질|공급차질|감산|생산쿼터 감축|폐쇄", 0.70,"negative"),
    ("tariff",          r"tariff|customs duty|anti[- ]dumping|관세|반덤핑",      0.60,"negative"),
    ("regulation",      r"regulat|permit|environmental|quota|licen[cs]e|규제|허가|쿼터|환경", 0.50,"neutral"),
    ("policy_subsidy",  r"subsid|stimulus|incentive|state support|보조금|지원금|인센티브", 0.40,"positive"),
    ("trade_data",      r"foreign trade|trade up|trade down|trade surplus|YoY|무역수지", 0.30,"neutral"),
]
def split_sentences(text):
    parts=re.split(r"(?<=[.!?])\s+|\n|(?=ㅇ\s)|(?=□)|(?=※)|(?=\*\s)", text)
    return [s.strip() for s in parts if len(s.strip())>15]

def baseline_extract(sections, commodity_hint):
    events=[]
    for sec in sections:
        for sent in split_sentences(sec["text"]):
            low=sent.lower()
            countries=[c for c in COUNTRIES if re.search(r"\b"+re.escape(c)+r"\b",sent)]
            for etype,pat,sev,dirn in EVENT_RULES:
                if re.search(pat,low):
                    severity=sev*(1.0 if countries else 0.7)
                    events.append({
                        "section_seq":sec["seq"],
                        "country": countries[0] if countries else None,
                        "commodity_code": commodity_hint,
                        "event_type": etype, "severity": round(severity,3),
                        "direction": dirn, "confidence": 0.5,
                        "evidence_quote": sent[:300],
                        "extractor":"baseline","model_version":"rule-v1",
                    })
                    break  # 문장당 최상위 1개 이벤트
    return events

# ---------- (옵션) LLM 추출 어댑터 : 운영 시 사용 ----------
LLM_PROMPT = """다음 광물시장 보고서 단락에서 '지정학/정책 이벤트'만 추출해 JSON 배열로 출력.
각 원소: {country, commodity_code(CU/NI/LI/CO/REE), event_type, severity(0~1), direction(negative/positive/neutral), confidence(0~1), evidence_quote}.
이벤트 없으면 []. 단락:\n---\n{TEXT}\n---"""
def llm_extract(sections, commodity_hint, call_llm):
    """call_llm(prompt:str)->str(JSON). 운영에서 Anthropic/OpenAI 등 주입."""
    events=[]
    for sec in sections:
        if len(sec["text"])<40: continue
        try:
            raw=call_llm(LLM_PROMPT.replace("{TEXT}",sec["text"][:6000]))
            for e in json.loads(raw):
                e.update({"section_seq":sec["seq"],"extractor":"llm","model_version":"llm-v1"})
                e.setdefault("commodity_code",commodity_hint)
                events.append(e)
        except Exception:
            continue
    return events


# ---------- 운영용 LLM 호출자 (Anthropic 예시) ----------
def make_anthropic_caller(model="claude-sonnet-4-6", api_key=None):
    """ANTHROPIC_API_KEY 환경변수 또는 인자로 키 주입. call_llm(prompt)->JSON문자열 반환."""
    import os, json as _json
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("pip install anthropic 필요")
    client=anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    def _call(prompt):
        msg=client.messages.create(
            model=model, max_tokens=2000,
            system="너는 광물시장 보고서에서 지정학/정책 이벤트를 추출하는 정밀 추출기다. 반드시 JSON 배열만 출력.",
            messages=[{"role":"user","content":prompt}])
        txt=msg.content[0].text.strip()
        m=re.search(r"\[.*\]", txt, re.S)   # JSON 배열만 추출
        return m.group(0) if m else "[]"
    return _call

# ---------- 단계 함수 ----------
def ingest(con, folder, source, commodity, exts=("pdf",)):
    files=[]
    for e in exts: files+=glob.glob(os.path.join(folder,"**","*."+e),recursive=True)
    n_new=0
    for f in sorted(set(files)):
        h=file_hash(f)
        if con.execute("SELECT 1 FROM doc_raw WHERE file_hash=?",[h]).fetchone(): continue
        con.execute("""INSERT INTO doc_raw
            (doc_id,source,commodity_hint,pub_date,received_at,fmt,file_name,file_path,file_hash,status)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [h[:16], source, commodity, parse_pub_date(os.path.basename(f)),
             dt.datetime.now(), f.rsplit(".",1)[-1], os.path.basename(f), f, h, "received"])
        n_new+=1
    print(f"  ingest: 신규 {n_new}건 (source={source})")

def parse(con):
    rows=con.execute("SELECT doc_id,file_path,source FROM doc_raw WHERE status='received'").fetchall()
    for doc_id,path,source in rows:
        try:
            if path.lower().endswith((".hwp",".hwpx")):
                txt=extract_hwp_text(path)
            else:
                cols = source not in ("KOMIS","PPS")   # KOMIS/조달청은 단단
                txt=extract_pdf_text(path, columns=cols)
            secs=tag_sections(txt)
            con.execute("UPDATE doc_raw SET raw_text=?,sections=?,n_sections=?,status='parsed' WHERE doc_id=?",
                        [txt, json.dumps(secs,ensure_ascii=False), len(secs), doc_id])
        except Exception as ex:
            con.execute("UPDATE doc_raw SET status='failed',error_msg=? WHERE doc_id=?",[str(ex)[:200],doc_id])
    print(f"  parse: {len(rows)}건 처리")

def analyze(con, call_llm=None):
    rows=con.execute("SELECT doc_id,commodity_hint,pub_date,sections FROM doc_raw WHERE status='parsed'").fetchall()
    total=0
    for doc_id,hint,pub,sections_json in rows:
        secs=json.loads(sections_json) if sections_json else []
        evs = llm_extract(secs,hint,call_llm) if call_llm else baseline_extract(secs,hint)
        for e in evs:
            con.execute("""INSERT INTO geo_event
                (event_id,doc_id,section_seq,obs_date,country,commodity_code,event_type,
                 severity,direction,confidence,evidence_quote,extractor,model_version,analyzed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [uuid.uuid4().hex[:16], doc_id, e.get("section_seq"), pub, e.get("country"),
                 e.get("commodity_code"), e.get("event_type"), e.get("severity"),
                 e.get("direction"), e.get("confidence"), e.get("evidence_quote"),
                 e.get("extractor"), e.get("model_version"), dt.datetime.now()])
            total+=1
        con.execute("UPDATE doc_raw SET status='analyzed' WHERE doc_id=?",[doc_id])
    print(f"  analyze: {len(rows)}문서 -> {total} 이벤트")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",default="minerals.duckdb")
    ap.add_argument("--schema",default=os.path.join(os.path.dirname(__file__),"geo_schema.sql"))
    sub=ap.add_subparsers(dest="cmd",required=True)
    pi=sub.add_parser("ingest"); pi.add_argument("--folder",required=True)
    pi.add_argument("--source",required=True); pi.add_argument("--commodity",default=None)
    pi.add_argument("--exts",default="pdf")
    sub.add_parser("parse")
    pa=sub.add_parser("analyze"); pa.add_argument("--llm",action="store_true"); pa.add_argument("--model",default="claude-sonnet-4-6")
    a=ap.parse_args()
    con=duckdb.connect(a.db)
    con.execute(open(a.schema,encoding="utf-8").read())
    if a.cmd=="ingest": ingest(con,a.folder,a.source,a.commodity,tuple(a.exts.split(",")))
    elif a.cmd=="parse": parse(con)
    elif a.cmd=="analyze":
        caller=make_anthropic_caller(a.model) if getattr(a,"llm",False) else None
        analyze(con, call_llm=caller)
    con.close()

if __name__=="__main__":
    main()
