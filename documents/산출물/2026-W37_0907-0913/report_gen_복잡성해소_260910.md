# report_gen 복잡성 해소 — 출력 계약 유지

작성: 2026-09-10. 기준 코드: `89d1741f2`의 작업 전 소스.
대상은 가격예측을 제외한 분석요약 10개 API이다. 공유 코드 변경은 가격예측에도
적용되지만 그 페이지의 기능·산식·프롬프트는 재설계하지 않았다.

## 적용한 변경

1. `analysis/input_data.py`: KOMIS 원본 JSON 파서와 기존 수동 입력 검증을
   서비스에서 분리했다. 가격 입력의 원본/명시값 우선순위를
   `normalize_price_request()` 한 곳에서 결정한다. 빈 값과 None의 기존 의미를 유지한다.
2. `analysis/indicator_summary.py`: 시장·수급지표의 등급/변화/근거 계산을 분리했다.
   계산 모듈이 DB나 LLM을 호출하지 않도록 책임을 구분했다.
3. `summary.py::_build_response()`: 6개 분석 처리 경로의 공통 응답 필드 조립을 통합했다.
   페이지별 품질 기준, LLM 실행 조건, 필터와 Markdown 내용은 유지했다.
4. `resources/prompts/*.md`: 지시문 10개를 UTF-8 파일로 옮겼다. 공통 지침과
   페이지별 지침의 문자열은 바이트 수준으로 유지한다. 가격 4개 API는 여전히
   하나의 가격 지시문을 공유한다. `PROMPTS`와 기존 상수 import도 유지한다.
5. `prompts.py`: DB 필드별 덮어쓰기의 반복 조립을 줄였다.
   `page_prompt_scope()`가 요청 시작 시 캐시 스냅샷에서 설정/지시문을 확정한다.
   계산, LLM payload, 검증이 같은 설정을 쓰고, 동시 reload는 다음 요청에 반영된다.
   ContextVar는 예외가 나더라도 reset되며 다른 요청의 페이지 설정과 섞이지 않는다.
6. `models.py`: 6곳의 페이지별 금지 필터 검사를 공통 함수로 통합했다.
   입력 필드, 검증 순서/오류 문구와 OpenAPI는 유지한다.
7. `errors.py`, `analysis/__init__.py`: 입력 오류 타입을 DB 구현에서 분리했다.
   과거 DB/미리보기 API export는 요청될 때만 로드한다. 기존 DataSourceError
   import 경로는 같은 클래스 객체를 재노출한다.
8. `main.py`: 서비스 생성 시 사용하지 않는 DB 소스 None 인자/복원용 주석 블록을
   제거했다. 기존 PG_DSN 기동 조건과 LLM timeout/retries는 유지했다.

서비스 파일은 약 3,100줄에서 약 1,500줄로 줄었다. 상당 부분은 책임에 따른
이동이며 전체 기능 삭제량을 뜻하지 않는다. 실제 중복 제거는 응답 조립,
가격 입력 우선순위 결정, 필터 검사, 프롬프트 설정 조립에 적용했다.

## 출력 보존 검증

`capture_output_contract.py`로 작업 전 소스를 별도 보관해 비교했다.

- 총 3,777개 비교 항목, 차이 0건.
- 분석 입력 3,766건: 정상 3,463건, 기존 입력 오류 303건. 오류도 종류/문구까지 동일.
- 추가 11개 항목: OpenAPI 전체 1개, 대상 10개 페이지의 기본 지시문/설정.
- 정상 입력은 Markdown 본문과 내부 구조화 응답 전체를 비교했다.
- 기존 수동 입력 스모크 하네스의 수치 불일치 0건.
- `unittest` 11개 통과: 10개 HTTP 라우트의 성공/잘못된 입력 응답,
  NO_DATA/INTERNAL_ERROR/TIMEOUT, LLM 성공/검증 실패 후 재시도/전송 실패 폴백,
  요청 예산 소진, 잘못된 DB 계약 폴백, reload 실패, 요청 중 reload,
  동시 페이지 설정 격리, 과거 오류 import 호환.
- Python 컴파일 및 `git diff --check` 통과.

명령:

```sh
PYTHONHASHSEED=0 python3 inhouse/report_gen/scripts/capture_output_contract.py /tmp/before.json
# 리팩터 후:
PYTHONHASHSEED=0 python3 inhouse/report_gen/scripts/capture_output_contract.py /tmp/after.json /tmp/before.json
python3 -m unittest discover -s inhouse/report_gen/tests -v
```

FastAPI TestClient가 샌드박스의 스레드 통신에서 정지해 HTTP 관련 unittest는
승인된 샌드박스 외부 실행으로 확인했다. 이 테스트는 DB/실제 LLM/운영 API에 접속하지 않는다.
검증 집계는 같은 폴더의 `report_gen_복잡성해소_검증_260910.json`에 보관했다.

## 검증 범위와 남은 복잡성

- 철광석·에너지/기타 2개 가격 API는 희소금속 실덤프를 동일 스키마로 재생해
  처리 경로를 확인했다. 해당 광종의 실제 원천값 정확성 검증을 대신하지 않는다.
- 실 LLM 생성문은 비결정적이므로 호출하지 않았다. 기본 지시문/설정은 이전과
  동일하며 LLM 성공/재시도/실패는 테스트 대역으로 검증했다. 운영 DB의 현재
  편집값과 실 서버 배포 결과는 이번 검증에 포함하지 않는다.
- 기존 광물지도 동률 국가 선택은 set 순회 순서에 의존한다. 비교 시
  PYTHONHASHSEED=0을 고정했다. 기존의 선택 방식 자체는 변경하지 않았다.
- API 입력 두 방식과 범용 내부 요청 모델, DB 프롬프트 편집/필드별 기본값 폴백은
  호환성을 유지한다. 이를 없애려면 실제 호출자의 사용 필드와 운영 설정 이전이 필요하다.
- 가격/광물지도 계산기의 통계·수치 보정과 문장 생성은 여전히 복잡하다.
  기존 보고서 내용과 산식을 유지하면서 가능한 구조 정리를 적용했으며,
  업무 규칙 자체를 제거하거나 보고서 섹션·문장 내용을 축소하지 않았다.
- 컨테이너 배포와 DB 시드/프롬프트 reload는 실행하지 않았다. 배포 시에는
  기존 절차에 따라 운영 설정을 확인한다. 이번 변경은 지시문 내용 변경이 아니다.
