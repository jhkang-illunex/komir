# -*- coding: utf-8 -*-
"""HWP 5.0 텍스트 추출기 (OLE + zlib + HWPTAG_PARA_TEXT 직접 파싱) — 한글/MCP 불필요"""
import olefile, zlib, struct, re

HWPTAG_PARA_TEXT = 0x10 + 51  # 67
# 컨트롤 문자 분류 (HWP5 스펙)
EXT_CTRL = {1,2,3,11,12,14,15,16,17,18,21,22,23}   # 8 wchar 차지(확장)
INLINE_CTRL = {4,5,6,7,8,9,19,20}                   # 8 wchar 차지(인라인)
CHAR_CTRL = {0,10,13,24,25,26,27,28,29,30,31}       # 1 wchar(문단/행 구분 등)

def _records(buf):
    p=0; n=len(buf)
    while p+4<=n:
        header=struct.unpack_from("<I", buf, p)[0]; p+=4
        tag=header & 0x3FF
        level=(header>>10)&0x3FF
        size=(header>>20)&0xFFF
        if size==0xFFF:
            size=struct.unpack_from("<I", buf, p)[0]; p+=4
        yield tag, buf[p:p+size]; p+=size

def _decode_paratext(data):
    out=[]; i=0; n=len(data)
    while i+1<n:
        code=data[i] | (data[i+1]<<8)
        if code in CHAR_CTRL:
            if code in (10,13): out.append("\n")
            else: out.append(" ")
            i+=2
        elif code in EXT_CTRL or code in INLINE_CTRL:
            i+=16  # 8 wchar = 16 byte 건너뜀
        else:
            out.append(chr(code)); i+=2
    return "".join(out)

def extract_text(path):
    ole=olefile.OleFileIO(path)
    # 압축여부: FileHeader 36번째 바이트 bit0
    comp=True
    try:
        fh=ole.openstream("FileHeader").read()
        comp=bool(fh[36] & 1)
    except: pass
    # 섹션 스트림 수집
    secs=[]
    for e in ole.listdir():
        if len(e)==2 and e[0]=="BodyText" and e[1].lower().startswith("section"):
            secs.append(e)
    secs.sort(key=lambda e:int(re.sub(r"\D","",e[1]) or 0))
    parts=[]
    for e in secs:
        raw=ole.openstream(e).read()
        if comp:
            try: raw=zlib.decompress(raw, -15)
            except: pass
        for tag,data in _records(raw):
            if tag==HWPTAG_PARA_TEXT:
                parts.append(_decode_paratext(data))
    ole.close()
    txt="\n".join(parts)
    return re.sub(r"[ \t]+"," ", txt)

if __name__=="__main__":
    import sys
    print(extract_text(sys.argv[1])[:2000])
