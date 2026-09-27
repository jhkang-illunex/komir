# 비정형 문서 provenance·검색 경계 감사 — 2026-09-27 13:02:19 KST

## 범위와 판정

- 대상: 테스트 배포 `komir-rag-chat-test` (`:18002`), 이미지
  `komir-rag-chat:20260927-multi-action-state-r1`.
- 범위: `document.retrieve`의 문서 검색, Evidence 변환, 기간 필터, 검증과
  Renderer 인용 경계. DB·문서 색인·접근정책 변경은 하지 않았다.
- 분류: HIGH. 문서 provenance와 답변 근거 계약은 공개 응답의 의미·출처에
  영향을 준다.
- 결론: FBQ38·FBQ39의 응답 부재는 `DEV_DUMMY` 제거가 아니라 실제 월간 문서
  원천·기간 부재다. 현재 비정형 문서에는 `DEV_DUMMY` provenance를 보존하는
  계약이 없으므로, 문서에 `ALLOW_DUMMY`를 적용하거나 그 정책으로 제외할 수 없다.

## 재현 근거

1. 배포 컨테이너의 PageIndex 트리 1,669건을 전수 점검했다. 트리 메타데이터에는
   `data_source`/`source_policy`/`DEV_DUMMY` 필드가 없고, 문자열 기준
   `DUMMY` 표기도 0건이었다.
2. 문서 원천 그룹은 조달청보고서 868건, Argus 비철금속 일일 690건, 광산자료
   99건, USGS 8건, 해외투자가이드 4건이다. `월간`이 제목·경로·resource에
   들어간 문서는 0건이었다.
3. public MCP가 제외하는 것은 `Argus_비철금속_일일`뿐이며, 이는
   `PRIVATE_ONLY_SOURCE_GROUPS` 라이선스 경계다. `DEV_DUMMY`에 대한 문서
   제외 조건은 없다. public/private 모두 FBQ38은 `source_unavailable`이었다.
4. 2026-09-27 기준 FBQ39의 최근 3개월 시작일은 2026-06-27이다. 최신 조달청
   문서는 2026-06-16, 최신 Argus 문서는 2026-06-15여서
   `_filter_document_evidence_to_trailing_period()`에서 모두 제외된다.
5. 명시 문서 `조달청보고서/20260616_주간_경제_비철금속_시장_동향.md`는 public
   PageIndex에서 OKF 본문을 정상 반환했다. 일반 문서 검색·Evidence 변환·Renderer가
   더미 상태 때문에 문서를 제거한다는 증거는 없다.

## 단계별 계약 확인

| 단계 | 확인 결과 | `DEV_DUMMY` 처리 |
|---|---|---|
| 검색 | dense/PageIndex는 public에서 Argus만 제외 | 없음 |
| Evidence | `from_dense_chunk()`·`from_pageindex_hit()`은 문서 provenance/caveat을 채우지 않음 | 없음 |
| 검증 | 기간·Action 계약·Advisor가 관련 근거만 유지 | 문서 더미 차단 없음 |
| Renderer/Citation | 검증된 Evidence만 인용·표시 | 문서 더미 제거 없음 |

## 회귀·후속 권고

- 기존 `test_action_contract_audit.py`의 월간동향 Action·기간 필터 회귀를
  배포 전 실행한다.
- 문서에 개발용 원천을 실제로 적재할 요구가 생기면 `ingest.source_file`부터
  PageIndex/dense metadata, `Evidence`, citation까지 `data_source`를 전달하고,
  `KOMIS_SAMPLE`/`DEV_DUMMY`/미확인의 3상태를 공통 정책으로 평가해야 한다.
- 현 시점에는 원천이 없으므로 `ALLOW_DUMMY` 확장이나 public/private 완화로
  FBQ38·FBQ39를 성공 처리하지 않는다.
