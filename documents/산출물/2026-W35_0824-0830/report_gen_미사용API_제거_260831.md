# report_gen 미사용 API 제거 (2026-08-31)

## 배경
사용자: "사용하지 않는 api는 제거해줘. price 공통 같은것 정말 필요한지
체크해고 제거할것은 제거하고 단순 심플하게 유지해줘요."

## 조사
report_gen의 API 표면 전체를 실사용 여부로 감사했다:

1. **호출자 확인**: 이 서비스의 유일한 실제 호출자는 streamlit_demo
   (`report_gen_client.py`)다 — grep으로 확인한 결과 이 파일은 항상
   `POST /api/v1/analysis/<path>` 형태로만 호출한다
   ("`response = client.post(f"/api/v1/analysis/{spec.path}", ...)`" —
   경로가 하드코딩으로 그 prefix 고정).
2. **`/api/v1/analysis/*` 12종 전부 사용 확인**: `report_gen_client.py`의
   `PAGE_SPECS`에 등록된 12개 page_id(indicator_market/supply·
   indicator_composite·map_mineral·forecast_price·price_base_metals·
   price_minor_metals·price_iron_energy·price_other·map_korea·
   map_global·**price_group**)가 `routers/analysis.py`의 12개 엔드포인트와
   1:1로 정확히 대응 — 전부 실사용 확인. **`price_group`("가격 그룹",
   비철금속/희소금속 전체 요약)도 데모 9번째 탭으로 실제 쓰이고
   있어 제거 대상이 아니다.**
3. **`routers/report_data.py`(`/api/v1/prices/*`·`/api/v1/indicators/*`·
   `/api/v1/maps/*`, 7개 엔드포인트) — 죽은 코드로 확정**: 2026-08-26에
   "발주처 프론트를 위해" REST 명명규칙으로 재노출한 별칭 레이어였는데,
   코드베이스 전체(streamlit_demo·다른 서비스·테스트) 어디에도 이
   prefix를 호출하는 곳이 하나도 없었다 — `/api/v1/analysis/*`와
   완전히 같은 page_id로 위임만 하는 순수 중복이었다.
4. **`/api/v1/dashboard/comprehensive`(`routers/comprehensive.py`) —
   유지**: 위 3개와 성격이 다르다. "AI 종합분석 및 관련뉴스"(화면기획
   ver.1.3 11p 스펙 문서 근거)라는 별개 계약(파라미터 없이 5광종 통합
   현황)이고, 2026-08-28 skeptic 감사(HIGH)로 최근에 실제 버그까지
   고친 이력이 있어 설계 의도가 뚜렷하다 — streamlit_demo가 아직 안 붙어
   있을 뿐 죽은 코드로 볼 근거가 없다. 제거 대상에서 뺐다.

## 변경
`app/routers/report_data.py` 파일 자체를 삭제(7개 엔드포인트:
`/api/v1/prices/{base-metals,minor-metals}`·`/api/v1/indicators/
{market,supply,composite}`·`/api/v1/maps/{korea,global,mineral}`).
`main.py`에서 관련 import·`app.include_router()` 3줄 제거,
`_ANALYSIS_API_PREFIXES`를 `("/api/v1/analysis/",)` 하나로 정리.
`routers/_common.py`의 스테일해진 모듈 docstring도 정정.

## 검증
- `TestClient`로 구 별칭 경로(`/api/v1/prices/base-metals`) 호출 —
  `404 Not Found`(라우트 자체가 없어짐) 확인.
- 정본 경로(`/api/v1/analysis/prices/base-metals`)는 여전히 니켈
  데이터로 `status=ok`(실제 LLM 경로까지) 정상 확인.
- 최종 OpenAPI 엔드포인트 목록 — `/api/v1/analysis/*` 12종 +
  `/api/v1/dashboard/comprehensive` + `/healthz` + `/admin/prompts/reload`
  + `/reports/*`(구 md 저장 경로) = 18개로 정리됨(구 25개에서 7개
  감소).
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지(이
  하네스는 HTTP가 아니라 `AnalysisSummaryService`를 직접 호출해 영향
  없음).

## 커밋
`app/main.py`·`app/routers/_common.py`·`app/routers/report_data.py`
(삭제) — main-agent 승인 후 재빌드·재기동 필요.
