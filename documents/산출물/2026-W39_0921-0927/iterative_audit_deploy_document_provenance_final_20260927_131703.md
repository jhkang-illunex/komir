# 최종 배포·문서 provenance 감사 — 2026-09-27 13:17:03 KST

## 배포 대상

- 커밋: `d1f2504f5`, `f9c1910d8`, `7503143b0`
- 이미지: `komir-rag-chat:20260927-document-provenance-audit-r3`
  (`sha256:ab087bb3f7b74d8294d430aa4289f584244706b7509a286e46d5ab78fae250a1`)
- 컨테이너: `komir-rag-chat-test` (`:18002`), `/healthz` HTTP 200
- 롤백: `komir-rag-chat-test-pre-20260927-131404`

## 변경

- 발행일·문서 종류·본문/제목/원문/요약 요청이 모두 있는 단일 질의를 LLM보다
  먼저 `document.lookup`으로 고정했다. 가격·무역 복합 요청은 이 경로에서 제외한다.
- citation envelope의 `data_status`·`warnings` 기대값을 갱신했다.

## 검증

- 회귀: 문서·Action 계약·citation 대상 103건 통과. 배포 스크립트의 기존
  단위/스모크/라이브 수락 검사도 통과했다.
- Sol HIGH 차분 감사: 신규 HIGH/CRITICAL 없음, public/private 경계 우회 없음.
- 실제 `/pubchat` SSE:

| 질의 | 결과 |
|---|---|
| `2026년 6월 16일 주간 경제 비철금속 시장 동향 내용을 알려줘` | 성공, citation 3건, 모두 해당 조달청 문서 |
| FBQ38 최근 희소금속 월간동향 제목 | `source_unavailable`, citation 0 |
| FBQ39 최근 3개월 월간동향 리튬 내용 | `source_unavailable`, citation 0 |

## provenance 판정

- `ALLOW_DUMMY`는 현재 KOMIS 정형 원천 전용이며, 문서 검색에는 `DEV_DUMMY`
  제거 분기가 없다.
- FBQ38·39의 기권은 실제 월간 문서 및 요청 기간 내 원천 부재다. 더미 정책
  결함으로 분류하지 않는다.
- public/private 문서 경계는 계속 Argus 라이선스 원천에만 적용된다.

## 잔여 권고

- 비정형 `DEV_DUMMY` 문서를 장래에 적재할 때만 ingest → index → Evidence →
  citation으로 provenance를 전달하고 `ALLOW_DUMMY + 경고` 정책을 별도 계약으로
  구현한다. 현재 코퍼스에는 이 상태의 문서가 없다.
