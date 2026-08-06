# -*- coding: utf-8 -*-
"""파일 → 텍스트 추출 (pdf/hwp/xlsx). 자체 포함(외부 프로그램 불필요)."""
import io, os, re, struct, zlib

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


# ---- opendataloader-pdf 배치 변환 + OCR 폴백 (2026-07-07 도입) ----
# 실측(2026-07-07): pypdf는 일부 구형 PDF(조달청 2013~2014년경 hwp→pdf 변환본)에서 한글 띄어쓰기를
# 통째로 날려버림("다만장기적으로보았을때..."). opendataloader-pdf(레이아웃 기반 XY-Cut 재구성)는
# 같은 문서에서 정상 띄어쓰기 복원을 확인. 배치 호출 전제(문서: "convert()는 호출마다 JVM이 뜨므로
# 파일 하나씩 부르면 느림") — 반드시 여러 파일을 한 번에 묶어서 호출.
OCR_MAXPAGES = int(os.environ.get("OCR_MAXPAGES", str(PDF_MAXPAGES)))
OCR_MIN_CHARS = int(os.environ.get("OCR_MIN_CHARS", "50"))   # 이 미만이면 스캔본으로 간주해 OCR 폴백

_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_HR = re.compile(r"^-{3,}\s*$", re.MULTILINE)


def md_to_text(md: str) -> str:
    """opendataloader markdown → 평문. 표 파이프는 공백으로 풀어 단어 경계를 보존."""
    t = _MD_IMG.sub("", md or "")
    t = _MD_HEADING.sub("", t)
    t = _MD_HR.sub("", t)
    t = t.replace("|", " ")
    return t


def opendataloader_batch_convert(paths: list, out_dir: str) -> dict:
    """paths(문자열 경로 리스트) → {path: text|None(변환실패/미생성)}. 배치 1회 JVM 호출.
    파일명 충돌(동일 basename, 다른 폴더) 시 opendataloader가 산출물을 덮어쓰므로, 충돌분은
    호출자가 개별 폴더로 분리해 전달해야 함(이 함수는 이미 충돌 없는 배치라고 가정).
    실측(2026-07-07): 청크 내 파일 1개가 CLI를 비정상 종료(return code 1)시켜도, Java는
    그 전까지 처리한 파일들의 .md를 이미 디스크에 써놓은 상태 — 예외를 잡았다고 청크 전체를
    None 처리하면 이미 성공한 산출물까지 버리고 불필요한 OCR 폭주를 유발함(실측: 121개 정상
    변환분이 전부 재-OCR로 넘어가 CPU 212분 낭비). 그래서 예외가 나도 .md 존재 여부로 개별
    판정한다. 이미 .md가 있는 파일은 재변환을 건너뛰어(resume) 재실행 시 중복 작업도 방지."""
    import opendataloader_pdf
    os.makedirs(out_dir, exist_ok=True)

    def _stem_md(p):
        return os.path.join(out_dir, os.path.splitext(os.path.basename(p))[0] + ".md")

    to_convert = [p for p in paths if not os.path.exists(_stem_md(p))]
    if to_convert:
        try:
            opendataloader_pdf.convert(
                input_path=list(to_convert), output_dir=out_dir, format="markdown",
                pages=f"1-{PDF_MAXPAGES}", quiet=True,
            )
        except Exception as e:
            print(f"  [warn] opendataloader 청크 일부 실패(반환코드 비정상) — 파일별 .md 존재로 개별 판정: {e}")

    out = {}
    for p in paths:
        md_path = _stem_md(p)
        if os.path.exists(md_path):
            try:
                out[p] = md_to_text(open(md_path, encoding="utf-8", errors="ignore").read())
            except Exception:
                out[p] = None
        else:
            out[p] = None
    return out


_OCR_READER = None


def _get_ocr_reader():
    """easyocr Reader는 로드 비용(수 초)이 커서 프로세스당 1회만 생성(지연 초기화)."""
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(["ko", "en"], gpu=False)
    return _OCR_READER


def ocr_pdf_text(path: str, max_pages: int = None) -> str:
    """스캔본(이미지) PDF용 OCR 폴백. GPU 미가용 환경 실측: 페이지당 ~2~4초(easyocr, CPU)."""
    import fitz
    import numpy as np
    max_pages = max_pages or OCR_MAXPAGES
    reader = _get_ocr_reader()
    doc = fitz.open(path)
    parts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=200)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        try:
            result = reader.readtext(img, detail=0, paragraph=True)
        except Exception:
            continue
        parts.append("\n".join(result))
    return "\n".join(parts)

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
    if low.endswith(".txt"): return "txt", data.decode("utf-8", errors="ignore")
    raise ValueError(f"지원하지 않는 형식: {os.path.basename(path)}")
