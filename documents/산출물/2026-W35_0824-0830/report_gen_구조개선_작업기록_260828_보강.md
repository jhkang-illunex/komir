# report_gen 구조개선(작업A) 부하테스트 + 작업B geo_event 품질 확인 (2026-08-28)

담당: report-summary-agent(`worktree-report_gen`). 원 설계 문서는 main 체크아웃
`documents/산출물/2026-W35_0824-0830/report_gen_구조개선_price주요요인_작업기록_260828.md`
(이 세션은 워크트리 격리로 직접 못 씀) — 이 파일은 그 문서가 요구한 "부하테스트
실측표 + 동시요청 전/후 처리시간 대조"와 "geo_event 데이터 품질 확인" 결과를
워크트리 안에 남긴다.

## 작업A — Semaphore(N) 부하테스트 실측

### 방법
로컬 vLLM(`http://127.0.0.1:52302/v1`, `gemma-4-26b-a4b`, 컨테이너 아님 — 공유
컨테이너는 손대지 않음)에 실제 `price_base_metals` 요약 프롬프트(4개 관측치,
`calculate_price_summary`가 만드는 evidence 5건 그대로)를 `KomirJsonLLM.invoke()`
(운영과 동일한 클라이언트·`timeout=12s`·`retries=1`)로 동시 1/2/4/8/10/12/16/24/32건
호출, 각 수준 2~3회 반복. 스크립트: `/tmp/report_gen_fix_evidence/loadtest_semaphore*.py`
(세션 스크래치패드, 재현 가능 — 필요시 요청).

### 결과
| 동시성 N | p50(s) | p95(s) | max(s) | 실패 |
|---|---|---|---|---|
| 1 | 2.49 | 2.66 | 2.66 | 0 |
| 2 | 3.06 | 3.14 | 3.13 | 0 |
| 4 | 3.20 | 3.21 | 3.21 | 0 |
| 8(1차) | 3.46 | 3.47 | 3.47 | 0 |
| 8(반복1) | 3.33 | 3.46 | 3.48 | 0 |
| 8(반복2) | 3.46 | 3.48 | 3.49 | 0 |
| 10(반복1) | 3.87 | 7.64 | 7.65 | 0 |
| 10(반복2) | 3.94 | 7.91 | 7.95 | 0 |
| 12(1차) | 3.41 | 6.55 | 6.55 | 0 |
| 12(반복1) | 3.75 | 6.99 | 7.04 | 0 |
| 12(반복2) | 3.43 | 6.52 | 6.53 | 0 |
| 16 | 6.97 | 7.09 | 7.10 | 0 |
| 24 | 10.55 | 10.69 | 10.70 | 0 |
| 32 | 11.00 | 14.02 | 14.02 | **8/64 ReadTimeout(12s)** |

**해석**: N=1~8은 p50·p95가 2.5~3.5초로 평탄(추가 큐잉 지연 거의 없음, vLLM
배치가 이 구간에서 사실상 병목 없이 흡수). N=10부터 p95가 p50의 약 2배로
벌어지며(6.5~8초) 변동성이 커지고, N=24는 12초 하드타임아웃에 근접(10.7초),
N=32에서 실제 `ReadTimeout` 실패가 발생한다. **N=8을 "20초 예산 안에 안정적으로
끝나는 최대치"로 채택** — 12초 LLM 타임아웃 대비 3.4배 여유, 4회 반복 전부
평탄한 재현성. 부수적으로 `routers/_common.py::_EXECUTOR`가 이미
`max_workers=8`로 캡을 걸어놔 N=8은 스레드풀 슬롯과 세마포어 허가가 1:1로
맞아떨어져 이중 큐잉이 없다(구조적으로도 정합).

### Semaphore(8) 동시성 동작 검증(동시 N+1건)
`threading.Semaphore(8)`로 12개 스레드를 동시 기동해 `acquire(timeout=)`/
`release()` 패턴(운영 `_common.py::_call()`과 동일 로직)을 재현 — 최대 동시
활성 스레드는 정확히 8을 초과하지 않았고(관측치: `max_concurrent=8`), 12건
전부 정상 완료(대기열 방식으로 순차 처리, 유실·행 없음). zombie 억제 로직
(`deadline - now < ANALYSIS_LLM_TIMEOUT_SECONDS`면 lock 시도 자체를 포기)은
`acquire`/`release` 시그니처가 Lock과 동일해 무수정으로 그대로 유지된다.

### 참고 캐베어(수정 아님, 명시만)
- N=8 실측은 **report_gen 단독 소비 기준**이다. 같은 로컬 vLLM을 rag_chat 등
  다른 서비스도 공유하므로, 실운영에서 다른 서비스의 동시 부하가 겹치면
  체감 지연이 늘 수 있다 — 다만 측정된 p95(3.5s)와 하드타임아웃(12s) 사이
  8.5초의 헤드룸이 있어 상당 폭의 외부 부하를 흡수할 여지는 있다.
- `routers/comprehensive.py`(`/api/v1/dashboard/comprehensive`)도 같은
  `analysis_lock`(세마포어) permit을 공유하며, 이 엔드포인트 1건이 permit 1개를
  쥔 채로 LLM을 최대 2회 호출한다(`build_dashboard()` 내부) — 부하테스트가
  측정한 "동시 8건"의 정의(permit 보유 건수)에 이미 포함되는 동작이라 별도
  문제는 아니지만, N=8이 "LLM 호출 8건 동시"가 아니라 "permit(=요청) 8건
  동시"라는 점은 운영 참고용으로 남긴다.

## 작업B — geo_event 데이터 품질 확인 (설계 전 게이트, main-agent 지시 1번)

### 방법
`docker exec -w /app -e PYTHONPATH=/app komir-report-gen-test`로 postgres
`mineral_risk.geo_event`를 직접 조회(5대 광종 CU/NI/CO/LI/REE 전부 존재 확인,
obs_date 2016~2026-08-21). severity=3.0(최고등급) 이벤트를 2025-06-01~09-01
구간에서 광종별로 확인.

### 발견 — evidence_quote 직접 인용은 품질 미달, 설계 변경 필요
severity=3.0(최고등급) 표본 687건 기준 `source` 필드로 origin을 나누면:

| source | 건수 | 비율 | 품질 |
|---|---|---|---|
| (공백, GDELT GKG 원천) | 579 | 84.3% | **URL 슬러그/헤드라인 파편**(문장 아님) |
| Argus | 61 | 8.9% | 영문 정문(완결된 문장) |
| KOMIS | 23 | 3.3% | **한국어 정문**(완결된 문장) |
| WoodMac/CN_MOFCOM/IEA/PPS | 24 | 3.5% | 영문 정문 |

공백-source(84%)의 `evidence_quote` 실제 예시(verbatim, 수정 없음):
- `"trump-says-50-per-cent-tariff-on-copper-imports-to-come-into-effect-august-1"`
- `"collapse-chiles-major-copper-mine"`
- `"indonesia-nickel-miners-three-year-quota-validity"`

→ 하이픈으로 이어붙인 URL 슬러그이지 문장이 아니다. 이걸 "주요 요인" 절에
그대로 인용하면 한국어 보고서 안에 영문 URL 조각이 섞여 나온다 — PDF
템플릿의 "가격 변동의 주요 요인으로는 [상승 또는 하락 요인, 1~2건 제시] 등으로"
문형이 요구하는 자연스러운 한국어 서술과 정면으로 어긋난다.

KOMIS-source(23건, 3.3%)만 정상 한국어 정문: `"이트륨은 중국의 수출통제
지속에 따라, 타이트한 공급으로 가격 상승 흐름을 이어감."` `"인도네시아
에너지 광물자원부는 '25년 니켈 원광 생산쿼터를 2억톤으로 전년 대비 26%
감축함..."` — 이런 건수만 골라 쓰면 광종·기간 조합에 따라 매칭 이벤트가
0건인 날이 훨씬 많아진다(대부분의 실제 요청에서 "주요 요인" 절이 계속 빔).

**severity만으로 상위 1~2건을 고르면(원 설계 지시 그대로) 84% 확률로 URL
슬러그가 뽑힌다** — 원 설계의 전제("evidence_quote로 자연스러운 문장을
만들 수 있다")가 데이터로 반증됨.

`direction` 필드는 반대로 품질이 좋다 — 7개 값의 깨끗한 통제 어휘
(`supply_down`·`supply_up`·`price_up`·`price_down`·`demand_down`·
`demand_up`·`neutral`, 자유서술 아님)라 한국어 라벨 매핑이 안전하다.
반면 `event_type`은 같은 표본에서 서로 다른 값이 268종+(영어/한국어
혼재, 대소문자·구두점 불일치 — 예: `"Geopolitical/Policy"`·
`"geopolitical/policy"`·`"policy"`·`"Policy/Regulation"`이 전부 별도 값)라
직접 라벨로 못 쓴다.

### 기존 코드 재사용 검토(재발명 방지)
- `inhouse/services/shared/retrieval/evidence.py`: "주요 변동 요인" 라벨이
  있지만 다른 테이블(`out_diagnosis_alert`류의 `reason` 컬럼) 대상이라 이
  작업과 무관 — 재사용 불가, 새로 만들어야 함.
- `app/dashboard_summary.py::_recent_events()`·`app/analysis/comprehensive.py`
  (`weekly_geo_events()`)가 이미 `geo_event`를 읽지만, **LLM에게 direction·
  event_type 원문(영문)을 그대로 payload로 넘기고 LLM이 자유롭게 종합
  서술하게 하는 설계**다(`comprehensive_prompts.py:93`) — 이 방식은
  덜 엄격한 종합분석(comprehensive) 계약이라 가능하다. 반면 이번 작업B가
  붙는 `komir_summary.py::calculate_price_summary`는 **결정론적
  EvidenceClaim.fact(항상 한국어 문장)를 만들고, LLM은 그 사실을 그대로
  옮겨쓰는지만 검증**하는 엄격한 evidence-bounded 계약(`_validate_llm_summary`)
  이라 같은 패턴을 못 쓴다 — 원문 영어/슬러그를 그대로 흘려보내면 LLM이
  검증을 통과하기 위해 그걸 그대로 베낄 수도 있다. 재사용 가능한 기존
  유틸은 없음, 신규 direction→한국어 라벨 매핑이 필요.

### 권고 설계(결정 아님 — main-agent 확인 후 진행)
1. **1차 문장은 `direction`+`country`+`obs_date`만으로 결정론적 템플릿 생성**
   (항상 한국어, 항상 안전): "조회기간 중 [국가]에서 공급 감소 흐름과
   맞물린 사안이 있었다(YYYY-MM-DD 기준)." 류, 인과 단정 없이 "동시발생"
   톤 유지.
2. **`evidence_quote`는 품질 휴리스틱을 통과할 때만 보강**(예: 한글 비율
   임계치 이상 + 하이픈 연쇄 슬러그 패턴 아님) — 통과하면 그 문장을 근거로
   덧붙이고, 실패하면 1번 템플릿만 사용(폴백, 절대 빈 채로 두지 않음).
   이벤트 선택도 severity 단독이 아니라 (품질통과 여부, severity) 복합
   정렬로 바꿔 KOMIS/Argus류가 GDELT 슬러그보다 우선 선택되게 한다.
3. `event_type`은 268종+ 자유서술이라 이번 라운드에선 쓰지 않는다(직접
   라벨화하려면 별도 정규화 작업 필요 — 범위 밖).

이 설계로 진행해도 될지 확인 필요 — 대안(예: KOMIS-source만 필터링해
매칭 안 되면 그냥 빈 채로 두는 보수적 버전, 또는 아예 이번 라운드는
`direction`만 쓰는 버전으로 축소)도 가능하니 지시 바람.
