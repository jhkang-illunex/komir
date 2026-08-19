# -*- coding: utf-8 -*-
"""doc_chunk.pub_date 백필 — dense 검색 날짜인식 부스트(A안) 전제조건.

배경(2026-08-19): 챗봇이 "2026년 상반기 니켈 LME 가격 동향"에 기권 응답한 원인을
조사하다가 실제로 그 문서(Argus 2026년 1~6월판 113건, 전부 니켈 언급)가 코퍼스에
있는데도 못 찾은 걸 확인 — dense 검색이 순수 코사인 유사도 top-k라 날짜를 전혀 못 씀.
`mineral_risk.doc_chunk.pub_date` 컬럼이 이미 있길래 쓰려고 봤더니 **140,031행 중
783행(0.6%)만 채워져 있고 Argus는 0건**이었다(직접 쿼리 확인) — 큰 배치 3종(Argus·
USGS·조달청보고서)은 `services/ingestion/build_okf_documents.py`가 title에 날짜를
담아뒀을 뿐 pub_date 컬럼으로 넘기는 코드가 없었다.

파싱 대상 title 패턴(실측 확인, 광종/화폐 등은 안 건드림 — title만 정규식 매칭):
  Argus:   "Argus Non-Ferrous Markets (2023-11-27)"      → 그 날짜 그대로
  조달청:   "비철금속시장동향(2012.11.06)", "...(2018.1.9)" → 그 날짜 그대로(월/일 1~2자리 허용)
  USGS:    "USGS_2023"                                    → 그 해 1/1(연간 리포트라 월일 정보 자체가 없음,
                                                              "연도만 확실"이라는 뜻으로 앵커링 — 아래 검증에서
                                                              coarse 표시)
매칭 안 되는 title(예: 조달청의 "Weekly_100928" 류, documents/산출물의 자유texttitle)은
그대로 NULL — 잘못 추정해 넣느니 정직한 결측이 낫다(프로젝트 전반의 원칙과 동일).

doc_id 단위로 한 번만 파싱해 (doc_id → date) 매핑을 만든 뒤 단일 벌크 UPDATE로
반영한다(청크당 개별 UPDATE 140,031번 대신 doc 단위 ~수천 번짜리 VALUES 조인 — 채팅
연결 왕복 비용 절감).

실행: python3 -m services.ingestion.backfill_doc_chunk_pub_date [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from services.shared.config import get_settings  # noqa: E402
from services.shared.db import pg_connect  # noqa: E402

_ARGUS_RE = re.compile(r"\((\d{4})-(\d{2})-(\d{2})\)")
_JODAL_RE = re.compile(r"\((\d{4})\.(\d{1,2})\.(\d{1,2})\)")
_USGS_RE = re.compile(r"^USGS_(\d{4})$")


def parse_pub_date(title: str) -> tuple[str, bool] | None:
    """title → (YYYY-MM-DD, is_coarse). is_coarse=True는 연도만 확실(USGS)."""
    if not title:
        return None
    m = _ARGUS_RE.search(title)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}", False
    m = _JODAL_RE.search(title)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}", False
    m = _USGS_RE.match(title.strip())
    if m:
        return f"{m.group(1)}-01-01", True
    return None


def run(dry_run: bool = False) -> dict:
    schema = get_settings().PG_SCHEMA
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {schema}.doc_chunk")
            total = cur.fetchone()[0]
            cur.execute(f"SELECT count(*) FROM {schema}.doc_chunk WHERE pub_date IS NOT NULL")
            before = cur.fetchone()[0]

            cur.execute(f"SELECT DISTINCT doc_id, title FROM {schema}.doc_chunk WHERE pub_date IS NULL")
            rows = cur.fetchall()

        mapping: list[tuple[str, str]] = []
        coarse_docs = 0
        for doc_id, title in rows:
            parsed = parse_pub_date(title or "")
            if parsed is None:
                continue
            date_str, is_coarse = parsed
            mapping.append((doc_id, date_str))
            if is_coarse:
                coarse_docs += 1

        print(f"[backfill] pub_date NULL doc_id {len(rows)}건 중 날짜 파싱 성공 {len(mapping)}건 "
              f"(연도만 확실=USGS {coarse_docs}건 포함)")

        if dry_run:
            print("[backfill] --dry-run: UPDATE 미실행")
            return {"total": total, "before": before, "matched_docs": len(mapping)}

        if mapping:
            with con.cursor() as cur:
                values_sql = ",".join(cur.mogrify("(%s,%s::date)", m).decode() for m in mapping)
                cur.execute(
                    f"""
                    UPDATE {schema}.doc_chunk c
                    SET pub_date = v.pub_date
                    FROM (VALUES {values_sql}) AS v(doc_id, pub_date)
                    WHERE c.doc_id = v.doc_id AND c.pub_date IS NULL
                    """
                )
                updated_chunks = cur.rowcount
            con.commit()
        else:
            updated_chunks = 0

        with con.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {schema}.doc_chunk WHERE pub_date IS NOT NULL")
            after = cur.fetchone()[0]

        print(f"[backfill] 청크 {updated_chunks:,}건 갱신 — pub_date 보유 {before:,} → {after:,} / 전체 {total:,}")
        return {"total": total, "before": before, "after": after, "updated_chunks": updated_chunks}
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(dry_run=args.dry_run)
