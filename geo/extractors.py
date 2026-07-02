# -*- coding: utf-8 -*-
"""파일 → 텍스트 추출 (pdf/hwp/xlsx). 자체 포함(외부 프로그램 불필요)."""
import io, os, struct, zlib

PDF_MAXPAGES = int(os.environ.get("PDF_MAXPAGES", "40"))

# ---- HWP 5.0 (OLE+zlib+HWPTAG_PARA_TEXT) ----
_HWPTAG_PARA_TEXT = 0x10 + 51
_EXT = {1,2,3,11,12,14,15,16,17,18,21,22,23}
_INLINE = {4,5,6,7,8,9,19,20}

def _hwp_records(buf):
    p, n = 0, len(buf)
    while p + 4 <= n:
        header = struct.unpack_from("<I", buf, p)[0]; p += 4
        tag = header & 0x3FF; size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", buf, p)[0]; p += 4
        yield tag, buf[p:p+size]; p += size

def _decode_paratext(data):
    out = []; i = 0
    while i + 1 < len(data):
        c = struct.unpack_from("<H", data, i)[0]
        if c in _EXT: i += 16; continue
        if c in _INLINE: i += 16; continue
        if c < 32:
            if c in (10, 13): out.append("\n")
            i += 2; continue
        out.append(chr(c)); i += 2
    return "".join(out)

def hwp_text(data: bytes) -> str:
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    parts = []
    for entry in ole.listdir():
        if entry and entry[0] == "BodyText":
            raw = ole.openstream(entry).read()
            try: raw = zlib.decompress(raw, -15)
            except Exception: pass
            for tag, rec in _hwp_records(raw):
                if tag == _HWPTAG_PARA_TEXT:
                    parts.append(_decode_paratext(rec))
    ole.close()
    return "\n".join(parts)

def pdf_text(data: bytes) -> str:
    import pypdf
    r = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((pg.extract_text() or "") for pg in r.pages[:PDF_MAXPAGES])

def xlsx_text(data: bytes) -> str:
    import pandas as pd
    xl = pd.ExcelFile(io.BytesIO(data))
    chunks = []
    for sh in xl.sheet_names[:20]:
        try:
            d = xl.parse(sh, header=None, nrows=200)
            chunks.append(f"[sheet:{sh}]\n" + d.to_csv(index=False, header=False))
        except Exception:
            pass
    return "\n".join(chunks)

def extract_text(path: str, data: bytes = None) -> tuple[str, str]:
    """반환 (fmt, text). 지원 외/실패는 예외."""
    if data is None:
        with open(path, "rb") as f:
            data = f.read()
    low = path.lower()
    if low.endswith(".pdf"): return "pdf", pdf_text(data)
    if low.endswith(".hwp"): return "hwp", hwp_text(data)
    if low.endswith((".xlsx", ".xls")): return "xlsx", xlsx_text(data)
    raise ValueError(f"지원하지 않는 형식: {os.path.basename(path)}")
