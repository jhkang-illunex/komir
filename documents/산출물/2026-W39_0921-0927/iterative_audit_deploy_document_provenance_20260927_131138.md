# 배포 후 문서 provenance 감사 — 2026-09-27 13:11:38 KST

## 대상

- 커밋: `d1f2504f5` (문서 provenance 감사 기록), `f9c1910d8`
  (citation envelope 회귀 기대값 보완)
- 이미지: `komir-rag-chat:20260927-document-provenance-audit-r2`
  (`sha256:81b4884026e55ca4be6b80a3618e8b2426325944dad130db05570d5ba90a318c`)
- 컨테이너: `komir-rag-chat-test` (`:18002`), `/healthz` 200
- 방법: 결정적 단위 회귀 103건, 기존 배포 수락 스크립트, 실제 `/pubchat`·`/prichat`
  SSE, Sol HIGH 차분 감사.

## 검증 결과

| 항목 | 실제 결과 | 판정 |
|---|---|---|
| FBQ38 최근 희소금속 월간동향 제목 | public `source_unavailable`, citation 0 | 월간 문서 원천 미보유 |
| FBQ39 최근 3개월 리튬 월간동향 | public `source_unavailable`, citation 0 | 기간 내 문서 원천 미보유 |
| private Argus 명시 문서 | `/prichat` 성공, citation 1 | private 문서 경로 정상 |
| public 조달청 명시 문서(2026-06-16) | `/pubchat` `source_unavailable`, citation 0 | P1 문서 선택/검증 결함 후보 |

## provenance 정책 감사

- Sol 감사와 런타임 점검 모두 `document.retrieve`에서 `DEV_DUMMY` 때문에
  문서가 제거되는 경로를 찾지 못했다.
- `ALLOW_DUMMY`는 KOMIS 정형 원천 전용 정책이다. dense/PageIndex 문서는
  현재 `data_source`·`source_policy`·`caveat`를 전달하지 않는다.
- 비정형 public 검색의 유일한 제외는 `Argus_비철금속_일일` 라이선스 경계다.
  private Argus 성공으로 이 경계와 렌더링 경로를 확인했다.
- FBQ38·39에는 `DEV_DUMMY` 경고가 잘못 표시되지 않았다.

## 감사 결론과 후속

- HIGH/CRITICAL: 없음.
- P1: public 조달청의 명시 문서가 PageIndex 직접 조회에서는 본문을 가지는데
  API `document.retrieve`에서는 기권한다. 문서 선택 query, 문서 ID 고정,
  Advisor supported-evidence 인덱스를 분리 추적해 수정 후 재검증할 항목이다.
  이는 FBQ38·39의 원천 미보유 사유나 `ALLOW_DUMMY`와는 독립이다.
- 조건부 HIGH 설계갭: 장래에 비정형 `DEV_DUMMY` 문서를 적재한다면 ingest →
  dense/PageIndex → Evidence → citation에 provenance를 전달하고,
  `ALLOW_DUMMY + 경고` 계약을 새로 구현해야 한다. 현재 코퍼스에는 해당 문서가 없어
  지금의 응답 부재를 이 갭으로 분류하지 않는다.
- 회귀: `test_internal_knowledge_route.py`의 citation `data_status`/`warnings`
  기대값 누락을 보완했으며, 관련 103건은 모두 통과했다.
