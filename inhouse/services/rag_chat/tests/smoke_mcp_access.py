# -*- coding: utf-8 -*-
"""`rag.ragkit.mcp_client`의 public/private 프로필 접근 경계 스모크 테스트 —
`python3 services/rag_chat/tests/smoke_mcp_access.py`.

`mcp_server_public.py`·`mcp_server_private.py`(2026-08-26 신설, 물리적으로
분리된 별도 모듈)를 실제 stdio 서브프로세스로 각각 띄워 실제 Postgres
(`mineral_risk.doc_chunk`)·PageIndex 트리 데이터에 대고 6개 도구를 호출한다
(더블·모의 없음 — 이 테스트의 핵심은 "SQL/트리 필터가 실제로 걸리는가"라서
진짜 데이터가 필요하다, `smoke_pageindex_agent.py`처럼 LLM만 스크립트로
대체하는 걸로는 검증이 안 됨).

검증 대상:
- hybrid_search·pageindex_lookup: public은 라이선스 제한 소스(Argus 비철금속
  일일동향)를 절대 안 돌려주고, private는 돌려준다.
- latest_diagnosis·import_forecast·geo_index_trend·pageindex_agentic: 프로필
  무관 — 둘이 완전히 같은 결과를 낸다(정형 산출물·USGS는 라이선스 이슈가 없어
  구분이 없어야 정상).
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_RAG_ROOT = next(p for p in (_HERE, *_HERE.parents) if (p / "rag" / "ragkit" / "mcp_client.py").is_file())
if str(_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(_RAG_ROOT))

from rag.ragkit import mcp_client  # noqa: E402

#: doc_chunk.src / PageIndex source_group에 실제로 찍히는 라이선스 제한 갈래.
_PRIVATE_SOURCE = "Argus_비철금속_일일"


def _has_private_source(evidence_list) -> bool:
    return any(ev.as_of == _PRIVATE_SOURCE or _PRIVATE_SOURCE in (ev.source or "") for ev in evidence_list)


def main() -> int:
    # 영문 쿼리 — Argus(영문 시장동향)가 코퍼스 최대 갈래(77,648청크)라 필터
    # 없이는 상위권을 거의 다 차지한다(실측 확인, 2026-08-26) — 필터가 새면
    # 바로 드러나는 질의를 골랐다.
    query = "aluminium premium LME inventory market"

    pub_hits = mcp_client.public.call_hybrid_search(query, 20)
    pri_hits = mcp_client.private.call_hybrid_search(query, 20)
    assert not _has_private_source(pub_hits), [ev.source for ev in pub_hits]
    assert _has_private_source(pri_hits), "private 프로필에서 Argus 청크가 하나도 안 나옴 — 데이터/필터 확인 필요"
    print(f"[OK] hybrid_search: public {len(pub_hits)}건(Argus 0건), "
          f"private {len(pri_hits)}건(Argus 포함) — 경계 확인")

    pub_nodes = mcp_client.public.call_pageindex_lookup("Argus 비철금속 알루미늄", node_limit=5)
    pri_nodes = mcp_client.private.call_pageindex_lookup("Argus 비철금속 알루미늄", node_limit=5)
    assert not _has_private_source(pub_nodes), [n.source for n in pub_nodes]
    assert any("Argus" in (n.source or "") for n in pri_nodes), [n.source for n in pri_nodes]
    print(f"[OK] pageindex_lookup: public {len(pub_nodes)}건(Argus 제외), "
          f"private {len(pri_nodes)}건(Argus 포함) — 경계 확인")

    # 정형 3종 — 프로필 무관, 완전히 동일해야 정상(라이선스 이슈 없음).
    for name, call in (
        ("latest_diagnosis", lambda s: s.call_latest_diagnosis("NI")),
        ("import_forecast", lambda s: s.call_import_forecast("NI")),
        ("geo_index_trend", lambda s: s.call_geo_index_trend("NI")),
    ):
        pub_ev = call(mcp_client.public)
        pri_ev = call(mcp_client.private)
        assert pub_ev == pri_ev, (name, pub_ev, pri_ev)
        print(f"[OK] {name}: public/private 완전 동일(프로필 무관 확인) — as_of={getattr(pub_ev, 'as_of', None)}")

    # pageindex_agentic — USGS 코퍼스만 스캔(Argus를 애초에 안 건드림). 실제 LLM이
    # 매 스텝 판단하므로(temp=0이어도 두 프로필 프로세스가 완전히 독립적으로
    # 호출해 바이트 단위 동일을 보장 못 함) "완전 동일"이 아니라 "Argus가 둘 다
    # 안 나온다"만 확인한다 — 이 도구가 프로필 무관인 이유(USGS 하드코딩)는
    # 코드 자체로 보장되고, 여기선 그 결과에 라이선스 제한 소스가 안 섞였는지만 본다.
    pub_agentic, pub_warn = mcp_client.public.call_pageindex_agentic("니켈 세계 생산 1위는?")
    pri_agentic, pri_warn = mcp_client.private.call_pageindex_agentic("니켈 세계 생산 1위는?")
    assert not _has_private_source(pub_agentic) and not _has_private_source(pri_agentic)
    print(f"[OK] pageindex_agentic: Argus 미포함 확인(public evidence {len(pub_agentic)}건 "
          f"warnings={pub_warn}, private evidence {len(pri_agentic)}건 warnings={pri_warn})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        mcp_client.stop_all()
