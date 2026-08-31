# report_gen — price_group 외부 인터페이스 제거 (2026-08-31)

## 배경
메뉴별 템플릿 현황 문서(`템플릿_현황_광물자원가격_260831.md`)에 대한
사용자 피드백: "전체 광종은 필요 없어 보임." — 발주처 PDF 템플릿도
"1-2. 전체광종(**필요시**)"로 이미 조건부 기능이라 명시하고 있었다.

price_group은 streamlit_demo 9번째 탭에서 실제 쓰이고 있어(2026-08-31
API 재감사에서 확인된 유일한 실사용 사례) 완전 삭제 시 데모도 같이
정리해야 하는 문제가 있었다 — `AskUserQuestion`으로 처리 범위를
확인한 결과 **"코드는 남겨두되 외부 인터페이스만 제거, streamlit
데모에서도 제거"**로 확정됐다.

## 변경
`app/routers/analysis.py`에서 다음만 제거:
- `PriceGroupSummaryRequest` 요청 스키마 클래스
- `@router.post("/price-group", ...)` 엔드포인트(`summarize_price_group`)
- 미사용이 된 `PriceGroup` import

**의도적으로 그대로 둔 것**(전부 내부 코드, 복원 시 재사용):
- `komir_summary.py::calculate_price_group_summary()`
- `komir_summary.py::KOMIR_PAGE_CONTEXTS["price_group"]`
- `prompts.py::PRICE_GROUP_SUMMARY_INSTRUCTIONS`·`PROMPTS["price_group"]`·
  `SECTION_SENTENCE_RANGES["price_group"]`
- `models.py`의 `AnalysisSummaryRequest.price_group`/`SummaryPageId`의
  `"price_group"` 리터럴

복원하려면 이 라우터 파일에 두 조각(요청 클래스+엔드포인트 함수)만
다시 붙이면 된다 — 내부 계산·프롬프트·페이지 컨텍스트는 손댈 필요
없음.

## 검증
- `GET /openapi.json` — analysis 엔드포인트 12개→11개, `PriceGroup
  SummaryRequest` 스키마 사라짐 확인.
- `POST /api/v1/analysis/price-group` — `404 Not Found` 확인.
- 나머지 4개 가격 페이지(base/minor/iron/other-metals)는 정상 동작
  유지 확인(엔드포인트 목록에 그대로 있음).
- 내부 레이어 재확인: `calculate_price_group_summary`·`KOMIR_PAGE_
  CONTEXTS["price_group"]`·`PROMPTS["price_group"]` 전부 import 성공,
  `AnalysisSummaryRequest(page_id="price_group", ...)`도 정상 생성
  (라우터 우회 시 내부 서비스는 여전히 처리 가능 — 나중에 다른 내부
  호출 경로가 필요하면 그대로 쓸 수 있다).
- `komis_dump_smoke_test.py` 회귀 395콤보(8페이지, price_group은
  애초에 이 하네스 대상이 아니었음) 전부 mismatch 0 유지.

## 후속 조치 필요
- **streamlit_demo 9번째 탭(price_group) 제거** — streamlit-agent에
  통지 예정(이 커밋 배포 후 API가 404를 반환하므로 데모 쪽도 같은
  주기에 맞춰 제거해야 한다).

## 커밋
`app/routers/analysis.py` — main-agent 승인 후 재빌드·재기동 필요.
