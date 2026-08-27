# -*- coding: utf-8 -*-
"""비정형 dense 검색 — pgvector(komis_demo `mineral_risk.doc_chunk`) 버전.

**날짜인식 부스트(2026-08-19, A안)**: "2026년 상반기 니켈..." 같은 질문이 실제로
코퍼스에 있는 문서(Argus 2026년 1~6월판 113건)를 못 찾고 기권한 사례를 조사하다가,
순수 코사인 top-k엔 날짜 개념이 전혀 없다는 걸 확인했다(`pub_date` 컬럼은 있었지만
백필 전엔 140,031행 중 783행뿐이라 애초에 못 씀 — `backfill_doc_chunk_pub_date.py`로
96,780행까지 채운 뒤 이 부스트를 넣는다). `extract_date_range()`가 질의에서 연도(+
상반기/하반기/분기)를 뽑아 그 범위에 `pub_date`가 든 청크의 코사인 거리를 소폭
깎아(=유사도 상향) 우선순위를 올린다 — **하드 필터가 아니다**(`pub_date`가 여전히
44%는 NULL이라 하드 필터는 관련 청크를 대량으로 잘라낼 위험, 2026-08-19 조사에서
직접 확인). 날짜 언급이 없거나 매칭되는 청크가 없으면 기존 동작과 동일하게 전락한다.

`rag/ragkit/retrieve.py`의 `dense_search()`(DuckDB `list_cosine_similarity`)와
**같은 역할·같은 반환 계약**을 갖는 교체 가능한 구현이다. RRF 융합 로직은
여기 재구현하지 않는다(재구현 금지) — 이 모듈은 하이브리드의 dense 절반만
담당하고, BM25 절반은 당분간 rag/index/rag.duckdb의 DuckDB FTS 그대로다
(2026-08-11 작업 범위: dense 벡터 저장소 전환만).

질의 임베딩은 `rag/ragkit/embed.encode_query()`를 그대로 쓴다 — 적재
(build_pgvector_index.py)와 같은 모델·같은 접두어("query: "/"passage: ")를
써야 벡터 공간이 일치한다. 로컬 sentence-transformers라 외부 API 호출 없음
(airgap 전제).

⚠ 스키마는 항상 `get_settings().PG_SCHEMA`(mineral_risk)로만 한정한다 —
   "public"을 하드코딩하지 않는다(services/shared/db.py 규약, public은 타 팀 소유).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..config import get_settings
from ..db import pg_connect

# 코사인 거리(0~2 범위, 정규화 벡터라 사실상 0~2이나 실전은 대개 0.1~0.6대)에서
# 날짜매칭 청크에 빼주는 보너스. 전체 랭킹을 뒤엎을 만큼 크진 않게(순수 의미
# 매칭이 압도적으로 좋은 청크를 날짜만으로 밀어내지 않는다), 그러나 top-5 경계의
# 근소한 차이는 뒤집을 만큼(2026-08-19 도입 — 경험적 상수, 실사용 중 재조정 가능).
_DATE_BOOST = 0.08

# \b(word boundary)는 안 쓴다 — Python re가 한글을 \w로 취급해 "2026년"처럼
# 숫자 바로 뒤에 한글이 붙으면 \b가 안 걸린다(실측 발견: 최초 버전은 모든
# "YYYY년" 질의에서 None을 반환하는 버그였음). 대신 숫자 앞뒤로 다른 숫자만
# 안 오면 되므로 (?<!\d)/(?!\d) lookaround로 대체.
_YEAR_RE = re.compile(r"(?<!\d)(20[01][0-9]|202[0-9])(?!\d)")
_HALF_RE = re.compile(r"(상반기|하반기)")
_QUARTER_RE = re.compile(r"([1-4])\s*분기")
_MONTH_RE = re.compile(r"(?<!\d)([1-9]|1[0-2])\s*월(?!\d)")
# "최근"류는 연도가 없어 위 정규식엔 안 걸린다 — 2026-08-27, 실사용자 피드백:
# "12개월 가격"·"수요 및 전망" 같은 절대연도 없는 질의가 2018년·2026년 문서를
# 구분 없이 섞어 근거로 냈다(오래된 자료가 최신인 것처럼 보임). 상대적 최근
# 표현도 같은 부스트로 처리 — 하드 필터가 아니므로 정말 그 기간 자료뿐이면
# 여전히 그걸 쓴다(질의 의도를 존중하되 억지로 비우지 않음, 위 date_range와
# 동일 원칙).
_RECENT_RE = re.compile(r"(최근|요즘|요\s*근래|최신)")
_RECENT_WINDOW_DAYS = 365


def extract_date_range(query: str) -> tuple[str, str] | None:
    """질의에서 "2026년 상반기"/"2025년 3분기"/"2024년 7월" 류 절대연도 표현,
    또는 "최근"/"요즘" 류 상대 표현을 뽑아 (시작일, 종료일) ISO 문자열로
    돌려준다. 어느 쪽도 없으면 None(날짜 무관 질의 — 부스트 생략). 월/분기/
    반기가 없으면 그 해 전체로 넓힌다."""

    m = _YEAR_RE.search(query)
    if not m:
        if _RECENT_RE.search(query):
            today = date.today()
            return (today - timedelta(days=_RECENT_WINDOW_DAYS)).isoformat(), today.isoformat()
        return None
    year = int(m.group(1))

    month_m = _MONTH_RE.search(query)
    if month_m:
        mo = int(month_m.group(1))
        start = date(year, mo, 1)
        end_month = mo + 1
        end_year = year
        if end_month > 12:
            end_month, end_year = 1, year + 1
        end = date(end_year, end_month, 1)
        return start.isoformat(), end.isoformat()

    q_m = _QUARTER_RE.search(query)
    if q_m:
        q = int(q_m.group(1))
        start = date(year, (q - 1) * 3 + 1, 1)
        end_month, end_year = start.month + 3, year
        if end_month > 12:
            end_month, end_year = end_month - 12, year + 1
        return start.isoformat(), date(end_year, end_month, 1).isoformat()

    half_m = _HALF_RE.search(query)
    if half_m:
        if half_m.group(1) == "상반기":
            return date(year, 1, 1).isoformat(), date(year, 7, 1).isoformat()
        return date(year, 7, 1).isoformat(), date(year + 1, 1, 1).isoformat()

    return date(year, 1, 1).isoformat(), date(year + 1, 1, 1).isoformat()


def _find_rag_parent(start: Path) -> Path:
    """`rag/ragkit/embed.py`를 담은 디렉토리를 위로 훑어 찾는다(소스트리는
    inhouse/, 컨테이너 배포본은 COPY 깊이가 달라 고정 depth를 못 쓴다 —
    services/shared/db.py `_find_msr_root`와 같은 이유·같은 패턴)."""

    for candidate in (start, *start.parents):
        if (candidate / "rag" / "ragkit" / "embed.py").is_file():
            return candidate
    raise ImportError(f"rag/ragkit/embed.py를 {start} 상위에서 찾지 못함")


_RAG_PARENT = _find_rag_parent(Path(__file__).resolve())
if str(_RAG_PARENT) not in sys.path:
    sys.path.insert(0, str(_RAG_PARENT))

from rag.ragkit.embed import encode_query  # noqa: E402


@dataclass
class PgRetrievedChunk:
    """`rag/ragkit/retrieve.RetrievedChunk`와 필드명을 맞춘 결과 레코드.

    dense 전용이라 bm25_rank/rrf_score는 없고, 대신 코사인 유사도(score)를
    싣는다 — RRF 융합 쪽에 넘길 땐 chunk_id/dense_rank만 있으면 된다."""

    chunk_id: str
    doc_id: str
    source_path: str
    week: str
    title: str
    section_heading: str
    text: str
    dense_rank: int
    score: float


def _vector_literal(vec) -> str:
    """pgvector 텍스트 리터럴(build_pgvector_index._vector_literal과 동일 규약)."""

    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def dense_search_pg(
    query: str, k: int = 8, *, exclude_src: frozenset[str] = frozenset()
) -> list[PgRetrievedChunk]:
    """pgvector 코사인 유사도 상위 k개 청크.

    `<=>`(vector_cosine_ops)는 코사인 **거리**라 오름차순 정렬이고, 적재 벡터가
    정규화돼 있으므로 유사도 = 1 - 거리다. 인덱스(idx_doc_chunk_embedding_hnsw)와
    같은 연산자를 써야 인덱스를 탄다.

    참고(2026-08-11 실측): 현재 코퍼스(1,206행)에선 플래너가 HNSW 인덱스 스캔
    대신 Seq Scan을 고른다 — 테이블이 작아 그게 실제로 더 싸고, 부수적으로
    근사(ANN)가 아니라 **정확한** top-k가 나온다(그래서 DuckDB dense와 결과가
    완전히 일치했다). enable_seqscan=off로 확인한 결과 인덱스 자체는 정상
    동작한다(Index Scan using idx_doc_chunk_embedding_hnsw). 코퍼스가 커지면
    자연히 인덱스 경로로 전환된다.

    `exclude_src`: `doc_chunk.src`(=OKF source_group, `build_pgvector_okf.py`가
    적재) 값이 이 집합에 있는 청크를 SQL 단에서 제외한다 — MCP public 프로필이
    라이선스 제한 소스(`shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`)를
    걸러내는 유일한 지점. 기본값(빈 집합)이면 기존 동작과 완전히 동일하다."""

    schema = get_settings().PG_SCHEMA
    qvec = _vector_literal(encode_query(query))
    date_range = extract_date_range(query)
    exclude_clause = " AND src <> ALL(%s)" if exclude_src else ""
    exclude_param = (list(exclude_src),) if exclude_src else ()

    con = pg_connect()
    try:
        with con.cursor() as cur:
            # HNSW 탐색 폭 — 기본 40. k가 크면 재현율 확보를 위해 넉넉히 잡는다.
            cur.execute("SET hnsw.ef_search = %s", (max(40, k * 4),))
            if date_range:
                # 날짜매칭 청크만 거리 보너스(=순위 상향), 나머지는 순수 코사인
                # 그대로 — 하드 필터가 아니므로 매칭 0건이어도 결과가 비지 않는다.
                cur.execute(
                    f"""
                    SELECT chunk_id, doc_id, source_path, week, title, section_heading, txt,
                           (embedding <=> %s::vector)
                           - CASE WHEN pub_date >= %s::date AND pub_date < %s::date
                                  THEN %s ELSE 0 END AS ranking_dist,
                           embedding <=> %s::vector AS raw_dist
                    FROM {schema}.doc_chunk
                    WHERE embedding IS NOT NULL{exclude_clause}
                    ORDER BY ranking_dist
                    LIMIT %s
                    """,
                    (qvec, date_range[0], date_range[1], _DATE_BOOST, qvec, *exclude_param, k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT chunk_id, doc_id, source_path, week, title, section_heading, txt,
                           embedding <=> %s::vector AS raw_dist
                    FROM {schema}.doc_chunk
                    WHERE embedding IS NOT NULL{exclude_clause}
                    ORDER BY raw_dist
                    LIMIT %s
                    """,
                    (qvec, *exclude_param, k),
                )
            rows = cur.fetchall()
    finally:
        con.close()

    # 두 분기(날짜부스트 유무) 모두 raw_dist(진짜 코사인 거리, score 표시용)가
    # 마지막 컬럼이라 음수 인덱스로 통일해 받는다 — ranking_dist(부스트 반영,
    # 정렬 전용)는 score에 안 쓴다(사용자에게 보여줄 유사도는 왜곡 없는 값이어야 함).
    return [
        PgRetrievedChunk(
            chunk_id=r[0], doc_id=r[1], source_path=r[2] or "", week=r[3] or "",
            title=r[4] or "", section_heading=r[5] or "", text=r[6] or "",
            dense_rank=i + 1, score=1.0 - float(r[-1]),
        )
        for i, r in enumerate(rows)
    ]


def dense_search_pg_ids(query: str, k: int) -> list[str]:
    """`rag/ragkit/retrieve.dense_search()`의 드롭인 대체(chunk_id 리스트만).

    hybrid_search의 RRF 융합부에 그대로 꽂을 수 있는 형태 — 융합 로직 자체는
    건드리지 않는다."""

    return [c.chunk_id for c in dense_search_pg(query, k)]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "핵심광물 진단모델 QWK 성능은 얼마인가"
    for c in dense_search_pg(q, k=5):
        print(f"[{c.score:.4f}] #{c.dense_rank} {c.source_path} :: {c.section_heading}")
        print("   ", c.text[:120].replace("\n", " "))
