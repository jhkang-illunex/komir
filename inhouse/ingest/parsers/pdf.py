# -*- coding: utf-8 -*-
"""PDF → 마크다운 정규화. mineral_supply_risk가 이미 pymupdf/pdfplumber를 쓰고 있음
(requirements.txt 확인됨) — 신규 의존성 추가 전 재사용 가능한지 먼저 확인할 것.

2026-08-11: 위 스켈레톤 메모대로 재사용 확인 완료 — `inhouse/geo/extractors.py`의
opendataloader-pdf → pypdf → OCR(easyocr) 3단계 폴백 체인(`extract_with_fallback`,
2026-07-07 도입, 0807 발주처자료 PDF ETL로 재검증됨)을 그대로 쓴다. 병합계획
(documents/산출물/2026-W33_0810-0816/병합계획_komis-report-generator_260811.md)
결정③: 외부 repo(komis-report-generator-main)의 PyMuPDF 단독 파서는 채택하지
않음 — komir 쪽이 이미 검증·가동 중인 파이프라인이 정본.

페이지 단위 분할·표 구조(bbox 등)는 이 체인이 보존하지 않는다(단일 텍스트 블록만
반환) — DocumentParser 계약을 맞추기 위해 문서 전체를 ContentUnit 1개로 감싼다.
페이지별 분할이 필요해지면 geo/extractors.py 자체를 바꾸지 말고(이미 검증된 코드,
CLAUDE.md §4 "최소·외과적 변경") 이 래퍼만 확장할 것."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_geo_root(start: Path) -> Path:
    """`geo/extractors.py`를 담은 디렉토리를 위로 훑어 찾는다.

    소스 트리(inhouse/ingest/parsers/pdf.py, 3단 위가 inhouse/)와 컨테이너
    배포본(Containerfile이 ingest→./ingest, geo/→./geo로 COPY, 3단 위가 /app)은
    2026-08-27 이동 후 깊이가 같아졌지만, 과거(services/ingestion 시절)엔 달랐고
    앞으로도 배포 레이아웃이 바뀔 수 있어 고정 깊이 대신 탐색으로 맞춘다."""

    for candidate in (start, *start.parents):
        if (candidate / "geo" / "extractors.py").is_file():
            return candidate
    raise ImportError(f"geo/extractors.py를 {start} 상위에서 찾지 못함")


_GEO_ROOT = _find_geo_root(Path(__file__).resolve())
if str(_GEO_ROOT) not in sys.path:
    sys.path.insert(0, str(_GEO_ROOT))

from geo.extractors import extract_with_fallback, md_to_text, opendataloader_batch_convert  # noqa: E402

from ..models import ContentUnit
from . import ParseResult

_MIN_USABLE_CHARS = 30
_DEFAULT_OCR_CACHE_DIR = str(
    _GEO_ROOT / "data_lake/semi_structure/pdf_extract/_ocr_cache"
)


class PdfParser:
    """opendataloader-pdf → pypdf → OCR 폴백 체인으로 PDF를 파싱한다."""

    name = "komir-opendataloader-ocr-fallback"
    # v2(2026-08-11): 산출 텍스트가 평문 → 마크다운 원형으로 바뀜(_raw_markdown 참고).
    # 산출물이 달라졌으므로 버전을 올려 이전 매니페스트의 재사용(_can_reuse)을 무효화한다.
    parser_version = "2"
    signature = f"{name}:{parser_version}:komis-pdf-v1"

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or os.environ.get(
            "INGESTION_OCR_CACHE_DIR", _DEFAULT_OCR_CACHE_DIR
        )
        self._md_cache: dict[str, str] = {}

    @property
    def _md_out_dir(self) -> str:
        return self.cache_dir + "_md"

    def _raw_markdown(self, path: str) -> str:
        """opendataloader가 써 둔 .md를 **마크다운 원형 그대로** 읽는다.

        2026-08-11 수정: 예전엔 `opendataloader_batch_convert()`의 반환값을 그대로
        썼는데, 그 함수는 `md_to_text()`를 거쳐 **헤딩(#)과 표 파이프(|)를 지운
        평문**을 돌려준다(geo 파이프라인은 LLM 추출용 평문만 필요해서 그렇게 짜여
        있음 — geo/extractors.py). 그 결과 이 파서를 통과한 PDF는 "텍스트+표를
        마크다운으로 정규화"라는 이 패키지의 계약(parsers/__init__.py docstring)과
        달리 구조가 전부 날아갔다(실측: USGS_2026 원본 md 헤딩 55개·표 파이프
        187개 → 산출 텍스트 0개·0개). 문서-OKF(§5-3 "섹션/표 구조를 보존")와
        PageIndex 트리(헤딩이 없으면 노드가 1개)가 둘 다 이 구조에 의존하므로,
        변환 side effect는 검증된 batch_convert에 그대로 맡기고 **읽기만** 원본
        .md에서 한다(geo/extractors.py 자체는 건드리지 않음 — 모듈 docstring의
        "이 래퍼만 확장할 것" 지침).
        """

        md_path = os.path.join(
            self._md_out_dir, os.path.splitext(os.path.basename(path))[0] + ".md"
        )
        if not os.path.exists(md_path):
            return ""
        try:
            with open(md_path, encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        except OSError:
            return ""

    def preload_batch(self, paths: list[str]) -> None:
        """opendataloader-pdf를 배치 1회로 호출해 markdown 결과를 내부 캐시에 채운다.

        JVM 스핀업 비용 때문에 파일 단위 호출을 피하려는 최적화(모듈 docstring
        참고) — pipeline.py가 실제 파싱이 필요한 PDF 목록을 계산해 이 메서드를
        먼저 부른다. 호출하지 않아도 parse()가 1건짜리 배치로 폴백해 정확성은
        유지된다."""

        if not paths:
            return
        opendataloader_batch_convert(paths, out_dir=self._md_out_dir)
        for p in paths:
            self._md_cache[p] = self._raw_markdown(p)

    def parse(self, path: Path) -> ParseResult:
        """PDF 한 건을 파싱한다 — 원천 고유 실패는 ParseResult로 흡수한다."""

        try:
            data = path.read_bytes()
            if str(path) in self._md_cache:
                md_text = self._md_cache.pop(str(path))
            else:
                opendataloader_batch_convert([str(path)], out_dir=self._md_out_dir)
                md_text = self._raw_markdown(str(path))
            text, method = extract_with_fallback(str(path), data, md_text, self.cache_dir)
        except Exception as exc:  # noqa: BLE001 - 한 파일의 실패가 배치 전체를 막지 않게
            return ParseResult(status="parse_failed", error=f"{type(exc).__name__}: {exc}")

        real_chars = len(md_to_text(text).strip())
        if method == "failed" or not text.strip():
            return ParseResult(status="ocr_required", warnings=["pdf_text_extraction_failed_all_methods"])

        warnings = [] if method != "partial" else ["low_text_partial_result"]
        content_status = "text" if real_chars >= _MIN_USABLE_CHARS else "sparse"
        unit = ContentUnit(
            sequence=1,
            locator_type="page",
            locator=1,
            text=text,
            char_count=real_chars,
            content_status=content_status,
            ocr_required=(method == "ocr"),
            tables=[],
            warnings=warnings,
        )
        return ParseResult(status="extracted", units=[unit], text=text, warnings=warnings + [f"extraction_method:{method}"])
