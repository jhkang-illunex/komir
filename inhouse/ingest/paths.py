# -*- coding: utf-8 -*-
"""ingest 디렉토리 계약 — landing / processing / data_lake 3단 (2026-09-16 사용자 지시).

    landing/     처음 데이터가 들어오는 곳(원본, 읽기 전용). 하위 폴더 = 소스 그룹(registry.py).
    processing/  작업 중 산출물 — 추출 매니페스트·documents.jsonl·texts(그룹별), OCR 캐시, 로그, 락.
                 해시 기반 재사용(변경 없는 파일 건너뜀)이 여기 매니페스트에 의존하므로 임시 디스크가
                 아니라 영속 볼륨이어야 한다.
    data_lake/   정리가 끝난 형태 — okf_documents/(문서-OKF 마크다운), pageindex_trees/(트리 JSON).
                 검색 계층(rag_core/retrieval/pageindex.py)과 rag_chat 컨테이너가 읽는다(ro).

경로는 `inhouse/.env`의 `INGEST_LANDING_DIR`·`INGEST_PROCESSING_DIR`·`INGEST_DATA_LAKE_DIR`
(common/config.Settings)에서 받는다. 비어 있으면 **레거시 기본값**(2026-09-16 이전 소스트리
고정 경로)을 그대로 쓰므로 .env를 손대지 않은 기존 호스트·컨테이너는 동작이 바뀌지 않는다:

    INGEST_PROCESSING_DIR 미설정 → <inhouse>/data_lake/semi_structure/pdf_extract
    INGEST_DATA_LAKE_DIR  미설정 → <inhouse>/data_lake/semi_structure
    INGEST_LANDING_DIR    미설정 → 그룹별 레거시 원본 위치(registry.SourceGroup.legacy_root:
                                   documents/…, documents/보고서_2/…, nas_document/학습데이터, inhouse/incoming)

경로 상수를 코드 여기저기(okf/pageindex/vectorize/parsers/extract, rag_core/ragkit/ingest.py)에
두지 않고 이 모듈만 참조한다 — 컨테이너 WORKDIR가 `/komir/inhouse`여야만 맞아떨어지던 함정
(ingest/README.md "WORKDIR" 절, 2026-08-27 사고)이 이걸로 사라진다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _INHOUSE_ROOT.parent

LEGACY_SEMI_STRUCTURE = _INHOUSE_ROOT / "data_lake" / "semi_structure"
LEGACY_PDF_EXTRACT = LEGACY_SEMI_STRUCTURE / "pdf_extract"


def _env_or_settings(name: str) -> str:
    """환경변수 우선, 없으면 common.config Settings(.env 로드)에서. 둘 다 없으면 ''."""
    v = os.environ.get(name)
    if v is not None:
        return v.strip()
    try:
        from common.config import get_settings

        return (getattr(get_settings(), name, "") or "").strip()
    except Exception:  # noqa: BLE001 — Settings 로드 실패(테스트 등)는 레거시 기본값으로
        return ""


@dataclass(frozen=True)
class IngestPaths:
    landing: Path | None        # None = 레거시(그룹별 legacy_root)
    processing: Path
    data_lake: Path

    # ── data_lake(정리 완료) ──
    @property
    def okf_documents(self) -> Path:
        return self.data_lake / "okf_documents"

    @property
    def pageindex_trees(self) -> Path:
        return self.data_lake / "pageindex_trees"

    # ── processing(작업 중) ──
    def extract_dir(self, group_key: str) -> Path:
        """그룹별 추출 산출물(manifest.json·documents.jsonl·documents/·texts/)."""
        return self.processing / group_key

    @property
    def ocr_cache(self) -> Path:
        return self.processing / "_ocr_cache"

    @property
    def shareable(self) -> Path:
        return self.processing / "shareable"

    @property
    def restricted(self) -> Path:
        return self.processing / "restricted_diagnosis_only"

    @property
    def logs(self) -> Path:
        return self.processing / "_logs"

    @property
    def locks(self) -> Path:
        return self.processing / "_locks"

    # ── landing(원본) ──
    @property
    def legacy(self) -> bool:
        return self.landing is None

    def landing_root(self, landing_subdir: str, legacy_root: Path | None) -> Path | None:
        """그룹 원본 루트. landing이 설정돼 있으면 landing/<subdir>, 아니면 그룹의 레거시 위치."""
        if self.landing is not None:
            return self.landing / landing_subdir
        return legacy_root

    def as_dict(self) -> dict:
        return {
            "mode": "legacy" if self.legacy else "layout",
            "landing": str(self.landing) if self.landing else None,
            "processing": str(self.processing),
            "data_lake": str(self.data_lake),
            "okf_documents": str(self.okf_documents),
            "pageindex_trees": str(self.pageindex_trees),
        }


def resolve_paths(landing: str = "", processing: str = "", data_lake: str = "") -> IngestPaths:
    """문자열 3개 → IngestPaths(빈 문자열은 레거시 기본값). 테스트·CLI 오버라이드용."""
    return IngestPaths(
        landing=Path(landing).expanduser().resolve() if landing else None,
        processing=Path(processing).expanduser().resolve() if processing else LEGACY_PDF_EXTRACT,
        data_lake=Path(data_lake).expanduser().resolve() if data_lake else LEGACY_SEMI_STRUCTURE,
    )


@lru_cache(maxsize=1)
def get_paths() -> IngestPaths:
    return resolve_paths(
        _env_or_settings("INGEST_LANDING_DIR"),
        _env_or_settings("INGEST_PROCESSING_DIR"),
        _env_or_settings("INGEST_DATA_LAKE_DIR"),
    )


def repo_root() -> Path:
    return _REPO_ROOT


def inhouse_root() -> Path:
    return _INHOUSE_ROOT
