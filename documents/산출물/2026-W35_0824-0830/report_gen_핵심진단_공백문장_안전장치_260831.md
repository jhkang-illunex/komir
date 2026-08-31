# report_gen — SummarySentence 공백 문장 안전장치 추가 (2026-08-31)

## 배경
메뉴별 템플릿 현황 문서를 작성하는 fork 3개 중 하나("광물자원가격" 담당)가
라이브 재현 과정에서 "핵심 진단" 절이 헤더만 있고 본문이 비어 보이는
사례를 보고했다. advisor 상담 결과, 이 세션 자체 트랜스크립트를 다시
확인해보니 이번 세션에서 이미 2회(compare_mineral_name 검증 시 네오디뮴
출력, price_criterion 검증 시 니켈 출력) 같은 증상이 실제로 있었다.

## 조사
- `models.py::SummaryNarrative.core_diagnosis`는 `Field(min_length=1)`이라
  구조적으로 빈 리스트가 될 수 없고, `_validate_llm_summary`
  (`summary.py`)도 섹션별 문장 "개수"를 검사해 0개면 검증 실패 →
  재시도/규칙기반 폴백으로 떨어진다 — 그런데도 증상이 관측됐다.
- 니켈(`prices/base-metals`) 6회, 네오디뮴 대비 갈륨(`prices/minor-
  metals`) 6회, 총 12회 동일 payload로 재호출했지만 재현 실패(라이브
  LLM 샘플링 변동성 탓에 재현율이 낮은 것으로 보인다).
- **구조적 허점 발견**: `SummarySentence.text: str = Field(min_length=1,
  ...)`는 문자열 "길이"만 검사한다 — 공백 1글자(`" "`)도 `min_length=1`을
  통과한다. `_validate_llm_summary`는 섹션당 문장 "개수"만 세지 문장 내용이
  공백뿐인지는 검사하지 않는다. LLM이 공백뿐인 `text`를 담은 유효한 개수의
  문장을 만들면, 검증을 통과해 그대로 렌더링되고 마크다운 상 그 절이
  비어 보이게 된다 — 확정된 근본원인은 아니지만(재현 실패로 직접
  증명은 못함), 유일하게 발견된 구조적 가능성이다.

## 변경
`app/analysis/models.py::SummarySentence`에 `text` 필드 검증기 추가 —
`.strip()`이 빈 문자열이면 `ValueError`로 거부(공백만 있는 문장 자체를
무효화)하고, 유효하면 앞뒤 공백을 잘라 저장한다.

## 안전성 확인 — 기존 폴백 경로를 그대로 탄다
`services/shared/llm_client.py::KomirJsonLLM.invoke()`가 이미
`output_model.model_validate(parsed)`를 `except (json.JSONDecodeError,
ValueError, ValidationError)`로 감싸고 1회 복구 재시도(`repair_output`
프롬프트) 후에도 실패하면 `LLMOutputError`(`LLMError`의 하위형,
`LLMError`는 `RuntimeError`의 하위형)를 던진다 — `summary.py::
_refine_with_llm`의 `except (LLMError, RuntimeError, OSError):`가 이걸
그대로 잡아 규칙 기반 응답으로 안전하게 폴백한다. 즉 이번에 추가한
검증은 **기존에 이미 다른 검증 실패(JSON 파싱 오류 등)에 쓰이던 동일한
안전망**을 타므로 새로운 실패 모드를 만들지 않는다 — 유효한 문장을
해칠 일도 없다(공백만 있는 분석문은 애초에 의미가 없다).

## 검증
- `SummarySentence(text="   ", ...)` → `ValidationError` 발생 확인.
- `SummarySentence(text="  실제 내용  ", ...)` → 정상 통과, 앞뒤 공백
  제거된 값으로 저장 확인.
- `komis_dump_smoke_test.py` 회귀 395콤보(8페이지) 전부 mismatch 0
  유지(이 하네스는 `llm=None` 규칙기반 경로만 태워 이번 변경과 무관 —
  실측으로 재확인).

## 미해결
근본 원인(왜 LLM이 가끔 공백 문장을 만드는지, 혹은 다른 경로가 진짜
원인인지)은 재현 실패로 확정하지 못했다. 이 안전장치는 증상을 막을
뿐 원인 규명은 아니다 — 재발하면(운영 로그에서 "핵심 진단에 현재 상태
근거가 없다"나 반복적인 LLM 정제 실패 경고를 관찰하면) 추가 조사
필요.

## 커밋
`app/analysis/models.py` — main-agent 승인 후 재빌드·재기동 필요.
