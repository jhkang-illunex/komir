from pathlib import Path
from collections import Counter
import json
P=Path(__file__).resolve().parent
raw=json.loads(next((P/'live').glob('*.json')).read_text())['results']
notes={
'AC01':('FAIL','가격 원값 일치. 더미65일을 최근1년 답으로 선택하며 순번·건수 표시가 남음'),
'AC02':('FAIL','가격 원값 일치. 실제 LME 기준도 존재하나 더미 선택·순번·건수 표시'),
'AC03':('FAIL','가격 원값 일치. 더미 선택·순번·건수 표시'),
'AC04':('FAIL','가격 원값 일치. 더미 선택·순번·건수 표시'),
'AC05':('FAIL','가격 원값 일치. 더미 선택·순번·건수 표시'),
'AC06':('FAIL','가격3근거 조회 후 unverified_or_incomplete_observation. 결합 답변 미제공; 독립적으로 완전 부재는 입증되지 않음'),
'AC07':('FAIL','NI -3.27% 독립 계산 일치. chart y_unit=null, 메뉴 출처 누락; 가격 코드의 사용자 단위 해석 미완'),
'AC08':('PASS','LI 수입상위5 금액·전체분모·비중 일치. 더미 고지 있음. 공통 표시 개선은 별도'),
'AC09':('BLOCKED_DATA','선택 광종 매핑에는 2025년7~9월 더미40행만 존재. 전체12개월 실제 월별 데이터 선행조건 미충족'),
'AC10':('PASS','HS2603000000 품목명·수입액·중량·조회기간이 독립SQL과 일치. 전체광종 합계로 확대하지 않음'),
'AC11':('BLOCKED_DATA','LI HHI는 dummy_trade_concentration으로 의도적 기권. 실제 관측 전체교역분모 확보 필요'),
'AC12':('PASS','2026 LI 상위5 매장량·전체분모 비중 일치. 더미 고지 있음'),
'AC13':('PASS','2026 REE 생산·매장 상위5와 비중 일치. 더미 고지 있음'),
'AC14':('FAIL','광산20문서 집계 응답 존재. 실제 OKF 사용에도 done의 4소스 모두 not_selected. 전체광산 순위의 독립 원본 완전대조는 미완'),
'AC15':('PASS','PageIndex 인용과 OKF58행 Escondida in Chile 일치. source 이름 literal 비교는 검사기 오판'),
'AC16':('FAIL','TSI -1.0 계산은 일치. 무차원 지표를 USD로 표시하고 더미·부분관측 고지 누락'),
'AC17':('BLOCKED_DATA','2024 LI 수입행 없음. 2025 증감률 분모가 없어서 기권은 적절'),
'AC18':('FAIL','dependency 대신 unsupported_combination. 독립SQL상 중국28518400/전체108544000=26.2735849%; 더미 고지/실제자료 정책은 필요'),
'AC19':('PASS','RCA 세계분모 미연결에 대한 정상 기권. 계산 완료를 뜻하지 않음'),
'AC20':('PASS','TII 정상 기권 계약 충족. 로그 실제 중단점은 빈 필터값 거절; 세계분모 adapter 도달은 미검증'),
'AC21':('PASS','무역TSI에 기준국·기간만 추가 질문'),
'AC22':('FAIL','같은 session 후속 요청에서 UnboundLocalError; done 없이 SSE 종료'),
'AC23':('PASS','공개 가격 메뉴 안내·로그인 불필요 계약 충족'),
'AC24':('PASS','공개 수입 메뉴 안내·로그인 불필요 계약 충족'),
'AC25':('FAIL','관련성 부족으로 기권. dense 타광종·PageIndex0·OKF unavailable. 코퍼스가 없다고 입증된 것은 아님'),
'AC26':('FAIL','삼원계 관계 근거 미회수로 기권. 최신 로컬 직접 검색에서도 무관한 큰 절이 상위에 존재'),
'AC31':('FAIL','사용자 문구는 정확한 정상 기권. SSE reason unsupported_mineral 대 YAML unsupported_commodity 및 message_key 누락 계약 불일치'),
'AC32':('PASS','2030 실측가격0행 독립 확인. 미래실측을 만들지 않고 기권'),
'AC33':('FAIL','미가동 진단 기능에 정상 기권하나 expected_message_key action_unavailable가 SSE에 없음'),
'AC34':('PASS','날씨·점심 무관 질문 정상 기권'),
'AC35':('PASS','지원하지 않는 순위+HHI 조합 정상 기권'),
'AC36':('PASS','공개 프로필에서 private 수급지표 제공하지 않음'),
}
judgments=[dict(id=x['id'],question=x['title'],runner_status=x['status'],audit_status=notes[x['id']][0],reason=notes[x['id']][1],raw_evidence=f"live_raw/{x['id']}_turn1.events.json",runner_errors=x['errors'])for x in raw]
(P/'independent_case_adjudication.json').write_text(json.dumps({'scope':'질문별 기능과 관측된 제품/SSE 계약의 보충 판정. 고정 runner 원본을 대체하지 않음; 공통 UI 완전 수락을 뜻하지 않음','counts':dict(Counter(x['audit_status']for x in judgments)),'cases':judgments},ensure_ascii=False,indent=2))
table='\n'.join(f"| {x['id']} | {x['runner_status']} | {x['audit_status']} | {x['reason']} |"for x in judgments)
report='''# Astra 전체 챗봇 독립 재검사 — 2026-09-23

## 결론

**전체 수락은 FAIL이다.** 고정 48건을 모두 실행했으며 로컬 소스 module 10·integration 6은 PASS, 실제 18002 라이브32는 실행기 기준 **PASS9 / FAIL23 / BLOCKED0**이다. 라이브는 질문과 top-k, fixture 사실을 통과하도록 바꾸지 않았다. 각 턴의 요청·SSE 원본·파싱 결과를 즉시 파일로 보존했다.

실행기는 정상 수치 응답에도 독립 수치검증 미구현을 이유로 FAIL을 반환한다. **23건을 모두 제품의 계산 실패로 해석하면 안 된다.** 독립 SQL·원문·로그 대조를 덧붙인 질문별 보충 판정은 **PASS14 / FAIL15 / BLOCKED_DATA3 / BLOCKED_ENV0**이다. PASS는 해당 질문의 핵심 답·기권/메뉴 동작을 확인했다는 뜻이며 모든 공통 UI 요구가 완료됐다는 뜻이 아니다. 원본 실행기 결과는 수정하지 않았다.

## 실행 범위와 증거

- 소스 gate: 최초 집중 회귀 **85 PASS, subtest20 PASS** (`source_unit_gates.log`). 명시된 8개 파일 재실행 로그는 `source_reproducible_gates.log`에 별도 보존했다.
- 기존 알려진 회귀를 별도로 재실행: `test_internal_knowledge_route.py` **16 PASS / 1 FAIL / subtest30 PASS**. 실패는 citation에 추가된 `menu_source: null`을 기존 기대값이 포함하지 않은 계약 불일치다. 집중 검사 PASS를 전체 소스 테스트 PASS라고 표현하지 않는다.
- source module10 + integration6: `source_cases/chatbot_acceptance_20260923_211902.json`. integration은 사전고정 원본·OKF·Tree hash·문서ID·사실/범위·실제 dense/PageIndex 결과와 `required_checks`를 확인했다. 이는 PDF/HWP/Excel 및 OCR3 표본의 연결 성공이다. 모든 자연어 문서질의의 성공 보장은 아니다.
- live32: `live/chatbot_acceptance_20260923_211901.json`, `live_raw/`, `live_execution.log`. AC22에는 동일 session 2턴 원본이 있다.
- 독립 read-only SQL: `read_rdb_preconditions.py`, `rdb_preconditions.json`, `verify_live_numbers.py`, `independent_numeric_verification.json`. SELECT 트랜잭션에서 광종별 코드·기준·기간·합계·분모를 확인했다. 감사 스크립트의 초기 광종명 중복 키는 코드 포함으로 수정해 재실행했으며, 제품 코드는 수정하지 않았다.
- 로그: `deployed_live_server.log`. 과거 로그도 포함하므로 이번 실행은 12:19~12:21 UTC 구간으로 식별한다. **HTTP200을 응답 정상종료로 오인하면 안 된다. AC22는 서버 예외로 done 없이 종료했다.** 초기 중간 점검의 ‘HTTP 오류 없음’은 전송 헤더만의 관측이었다.

## 배포와 로컬 구분

컨테이너 `komir-rag-chat-test`, image `komir-rag-chat:260923-trade-global-port-r1`, image ID `sha256:2e5102c6e51dd5f6a2defe0420d49b08320c6a3d1ffece0411a416019defd3db`, 시작 2026-09-22T17:15:06Z다. OKF·Tree는 현재 호스트 파일의 읽기 전용 bind mount다.

`source_deployed_comparison.json`에서 router·action_contract·chatbot_graph·chatbot·chatbot_events·komis_raw·embed는 로컬과 일치한다. chunk·dense_pg·pageindex·retrieval/evidence는 다르다. 로컬 dense의 ef_search 하한200, PageIndex 본문 검색 개선을 배포 서비스에 반영했다고 주장할 수 없다. AC22 예외와 TSI 단위 문제는 같은 로컬 코드에도 있다.

독립 subprocess로 로컬/배포 코드를 각각 새로 로드해 AC25/26 고정 질문과 dense k=6, public filter를 비교했다 (`compare_document_retrieval.py`, `document_retrieval_*.json`). 실행 중인 서비스의 PageIndex 캐시는 건드리지 않았다. 새 subprocess 결과는 서비스 캐시 내용과 동일하다고 가정하지 않는다.

- AC25는 로컬·배포 fresh 모두 dense 상위에 납 등 다른 광종을 회수한다.
- AC26은 로컬 본문 검색에서 PageIndex 노드를 추가 회수하지만, 상위 노드가 알루미늄 큰 절 등 질문 관계를 직접 설명하기 어려운 구간이다. 배포 fresh에서는 노드0이다.
- 따라서 문서 검색 실패는 미배포 차이와 질의별 회수·구간 선택의 문제를 함께 다뤄야 한다. 이미지 교체만으로 자연어2건이 성공한다고 단정하지 않는다.

## 실제 보완 우선순위

### P1 — HITL 후속 요청이 응답 없이 종료

AC22의 첫 턴은 기준국·기간을 정상 요청했다. 같은 session 후속 턴은 session/status 두 이벤트 후 종료했다. `inhouse/rag_core/ragkit/chatbot.py:1284`에서 pre_gate 분기가 아직 할당되지 않은 `abstain_reason`을 `_abstain_context`에 전달해 `UnboundLocalError`가 났다. 로컬/배포 SHA가 같아 배포만으로 해결되지 않는다.

수정안: pre_gate의 명시적 사유를 저장하고 모든 분기에 terminal done/error 계약을 보장한다. 원래 intent→action→조회/근거검증 구조를 유지한 채, 실제 `_run_chat_session` 2턴에서 pre_gate가 참인 부정 fixture도 추가해야 한다. 기존 모듈 fixture PASS가 실제 서버2턴 PASS를 대체하지 못했다.

### P1 — 무역 지표의 단위·원천 고지 및 의존도 경로

AC16 TSI -1.0은 SQL X=0, M=108,544,000과 일치한다. 그러나 본문에서 ‘단위: USD’로 표시한다. `inhouse/common/komis_raw.py:1177`의 지표 공통 단위 USD가 원인이다. TSI/RCA/TII는 무차원, 증감률/의존도는 %를 사용하고 원금액 열에만 USD를 써야 한다. 선택 데이터는 DEV_DUMMY이고 2025년7~9월 관측인데 AC16은 더미·부분기간 고지도 빠졌다.

AC18의 특정국 의존도는 `unsupported_combination`으로 끝나 action을 호출하지 못했다. 독립 SQL상 중국 수입28,518,400 / 전체108,544,000 = 26.2735849%다. 이 수치를 실제 통계로 제공하라는 뜻은 아니며, 올바른 단일 trade.indicator 경로에서 더미 정책을 적용해야 한다. action 분해/승인 경계를 고정 질문으로 추가 재현해야 하고, 현재 로그만으로 특정 LLM 분해 결과까지 확정하지 않는다.

### P1 — 문서 검색/근거 연결

AC25/26 로그는 vector6, PageIndex0, OKF unavailable이다. 근거 검증이 다른 광종 또는 삼원계 관계 부족을 거절한 것은 적절하다. 하지만 보고서 조회 목적은 달성되지 않았다. 데이터가 전혀 없다는 증명 없이 BLOCKED_DATA로 면제하지 않았다. retrieval/evidence·dense_pg·pageindex의 최신 코드 배포 여부와 query별 문서/구간 연결을 구분해 재검증해야 한다. 이번에는 코드·DB·배포를 변경하지 않았다.

### P2 — 표·차트·출처/SSE 계약

- AC01~05의 실제 표 원값은 SQL과 전부 일치한다. 그러나 `mnrl_prc_crtr_sn(광물가격기준순번)` 노출, ‘관측65건’ 표시가 남았다. `chatbot_events.py:99` 숨김 키에 원천 순번 키가 빠져 있다. 더미는 고지했지만 실제 LME도 있는 NI에서 더미가 선택되는 기준은 재검토 대상이다.
- AC07 변동률 -3.27%는 맞지만 chart y_unit=null, PR001/WT002 코드 노출, menu_source=null이다. 주간 bucket 시작일2024-12-30은 2025-01-02 관측의 주간 라벨이다. 이를 2024 원자료가 조회됐다고 오해하지 않도록 실제 관측기간과 집계 라벨을 구분해야 한다.
- AC14는 실제 광산 OKF 집계를 답하면서 done에서 4소스 모두 not_selected라 추적 정보가 맞지 않는다. 전 광산 원문을 독립적으로 재집계한 것은 아니므로 top5 완전 검증 PASS도 선언하지 않았다.
- 메뉴 링크 안내 AC23/24는 통과했다. 일반 답변 일부는 원천 테이블명 footer와 menu_source=null이 남아 ‘모든 출처가 메뉴 기준’이라는 주장은 불가하다.
- AC31/33은 사용자 실패 문구 자체는 요구대로다. reason/message_key의 YAML·SSE 계약은 불일치한다. 이름 정본을 맞추고 메시지 키를 실제 이벤트로 추적하는 검증이 필요하다.
- RCA/TII는 정상 기권일 뿐 기능 계산이 완료됐다는 뜻은 아니다. AC20의 현재 로그는 빈 필터값 거절에서 멈춰 세계분모 경로 도달도 입증되지 않았다.

## 검사기 한계와 보충 판정

정상 답변에 대한 `run_acceptance_suite.py:226`의 ‘독립 수치검증 미구현’이 단독 실패사유인 사례는 **11건**이다. 독립 대조로 수치가 맞음을 확인했어도 단위·기간·표시·정책까지 자동 통과시켜서는 안 된다. AC14/15의 expected_sources 문자열 검사도 논리 PageIndex/OKF와 citation.kind/source_path를 동일시하지 못한다. AC15는 OKF58행의 ‘Escondida in Chile’와 답이 일치한다.

| 사례 | 고정 실행기 | 독립 보충 판정 | 근거/제한 |
|---|---|---|---|
'''+table+'''

## 재현 명령과 종료 범위

```bash
PYTHONPATH=inhouse:inhouse/rag_chat python3 inhouse/rag_chat/tests/run_acceptance_suite.py --layer module --report-dir documents/산출물/2026-W39_0921-0927/acceptance_cycle3/astra_full_chatbot_recheck/replay_module
PYTHONPATH=inhouse:inhouse/rag_chat python3 inhouse/rag_chat/tests/run_acceptance_suite.py --layer integration --report-dir documents/산출물/2026-W39_0921-0927/acceptance_cycle3/astra_full_chatbot_recheck/replay_integration
python3 documents/산출물/2026-W39_0921-0927/acceptance_cycle3/astra_full_chatbot_recheck/run_live_with_evidence.py
python3 documents/산출물/2026-W39_0921-0927/acceptance_cycle3/astra_full_chatbot_recheck/read_rdb_preconditions.py
python3 documents/산출물/2026-W39_0921-0927/acceptance_cycle3/astra_full_chatbot_recheck/verify_live_numbers.py
```

live wrapper는 같은 경로에 저장하므로 재실행 전 새 감사 디렉토리로 복사해 기존 증거를 보존해야 한다. live 요청은 정상 서비스의 대화기록 저장 부작용을 갖지만 감사자가 직접 corpus/업무 DB를 쓰거나 재색인하지 않았다. DB 조회는 읽기 전용이었다. 배포·재시작·커밋·제품 코드 수정은 하지 않았다. 이 보고는 수락 여부 판정이며 위 P1의 수정 완료 보고가 아니다.
'''
(P/'ASTRA_FULL_RECHECK_260923.md').write_text(report)
print(Counter(x['audit_status']for x in judgments))
