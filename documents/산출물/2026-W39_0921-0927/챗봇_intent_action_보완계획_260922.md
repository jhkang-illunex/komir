# 챗봇 Q01~Q30 intent-action 보완계획 (2026-09-22)

## 범위와 현행 근거

대상은 현재 `komir-rag-chat-test`의 public/auto `/pubchat`이며, 이 문서는 **구현 전 계획**이다. `챗봇_Q01_Q30_서버전수검증_260922.md`의 30건 완료 기록과 `data_archive/validation_runs/rag_chat_q30_live_260922/QXX.json` 원문을 기준선으로 삼는다. 소스는 라이브 `inhouse/rag_core/ragkit/{action_contract.py,chatbot_graph.py,_mcp_tools_common.py}`, `inhouse/common/komis_raw.py`다. `expired/`는 사용하지 않는다. API·DB 스키마·action/slot 이름을 추가하지 않는다.

현행 Q01/Q23은 `price.series`와 `public.KO_MNRL_PRC` 인용, 표·차트를 반환했지만 citation `unit=null`, 답변의 단위 불명, 실가격 선택 시리즈에 개발용 더미 경고가 붙었다. Q15는 `document.retrieve` 두 번 후 `source_unavailable`, Q20은 action 검증 단계의 `source_unavailable`, Q28은 `price.verify_claim` 조회 단계의 `source_unavailable`이었다. Q21/Q22도 `document.retrieve`를 탔으나 인용 없이 기권했다. 이는 HTTP 실패가 아니다.

원천 판정 문서 `챗봇_평가질문_에어갭_원천답변가능성_260921.md`에 따르면 니켈 가격 기준 502(LME CASH)의 2025년 255행은 개발 더미 추적키가 없고, 해당 기준 첫·끝 관측 15,010→14,519.04, 단순 변동률 −3.27%다. **이 수치는 구현 전 참고값**이며 실제 실행 시 동일 가격 기준·기간·행·추적키를 SQL로 재확인한다. `USGS_2026.md`는 희토류 전체 생산·매장과 산화네오디뮴 가격을 별도로 다룬다. Q20의 배터리용 수요 및 Q21 재활용 사례는 보유 문서의 범위 안에서만 사용한다. OKF와 PageIndex는 같은 문서의 본문·색인이므로 두 독립 출처로 세지 않는다.

## 구현 항목과 허용 기준

| 우선 | 문항·원인 | 담당 파일과 최소 변경 | 성공 기준 | 허용 실패·금지선 |
|---|---|---|---|---|
| 1 | **Q01/Q23 단위·더미**: `price.series`의 선택 가격기준 정보가 citation 단위로 전파되지 않고, `_mcp_tools_common.py`의 경고는 `ai_mnrl_mst.ko_data_src_cd` 광종 수준이라 선택 시리즈의 출처와 어긋날 수 있다. | `komis_raw.py` 가격 조회 결과에서 선택한 `MNRL_PRC_CRTR_SN`과 가격기준의 `prc_unit_cd`·`weig_unit_cd`를 유지하고, `_mcp_tools_common.py`의 가격 Evidence 생성·경고 판정을 **반환 행의 선택 시리즈**와 더미 추적키 기준으로 좁힌다. `chatbot_graph.py`의 citation 단위 전달을 점검한다. | Q01/Q23의 선택 기준, 실제 관측 시작·끝, 통화/중량 **코드 또는 검증된 표시명**이 답변·citation·표에서 일치한다. 선택 시리즈에 더미 행이 없다는 SQL 근거가 있으면 더미 경고 없음. | 단위 코드 의미를 확인할 수 없으면 원시 코드로 명시하고 임의로 USD/t 등 변환하지 않는다. 선택 시리즈의 더미 여부가 불명확하면 경고를 유지한다. 광종 전체가 실제라는 일반화 금지. |
| 2 | **Q28 전제 확인**: 현행 `price.verify_claim`은 비교 adapter 결과를 쓰며 `chatbot_graph.py`의 `_comparison_or_monthly_source_is_usable`와 Advisor가 근거를 승인해야 한다. 비교 경로 `_mcp_tools_common.py`는 `_any_dummy()`로 광종 수준 더미 판정이 가능해 실가격 기준도 막을 수 있다. | `action_contract.py`에서 `price_claim`의 2025년 기간·300%·비교기준 슬롯 보존을 점검한다. `chatbot_graph.py`의 비교 route/전제 검증 및 `_mcp_tools_common.py`의 시리즈별 출처 판정을 위 Q01 수정과 공용으로 사용한다. 새 action을 만들지 않는다. | 실제 재조회로 확인된 **한 가격기준**의 2025년 첫·끝 날짜·가격·변동률을 표와 `price.verify_claim` 출처로 제시하고, 그 기준의 300% 상승 전제가 불일치함을 말한다. `equals` 판정도 정확히 적용한다. | 다른 가격기준·연평균까지 반박하지 않는다. 상승 원인이나 하락 원인은 가격 시계열만으로 설명하지 않는다. 적합 시리즈가 없으면 `source_unavailable`, 인용·표·차트 0건. |
| 3 | **Q15 범위**: `document.retrieve` 라우팅은 됐지만 USGS의 서로 다른 절을 직접 뒷받침하는 본문으로 확보하지 못했다. | `action_contract.py`의 기존 `document`/`concept` topic 추출 지침과 `chatbot_graph.py`의 `document.retrieve` 검색어·PageIndex/OKF 본문 선택을 조정한다. 일반 설명은 현재 `document.retrieve` 유지. 필요한 경우 기존 PageIndex 본문 읽기 경로만 보강한다. | USGS_2026의 희토류 **총괄 생산·매장**과 **산화네오디뮴 가격**이 서로 다른 범위라는 두 근거 절을 각각 인용하고, 가격 대 생산 통계를 직접 같은 모집단의 값처럼 비교하지 않는다고 설명한다. | 해당 절 본문을 못 찾으면 `source_unavailable`; 문서 제목·광종명 매핑만으로 동일 범위라고 답하지 않는다. |
| 4 | **Q20 조건부 영향**: “데이터와 추론 구분”을 무기간 `price.compare`와 독립 `document.retrieve`로 과잉 분해하면 `action_contract.py` 591~606행의 조합 검증이 `source_unavailable`로 닫는다. | `action_contract.py`의 intent 추출 지침에서 가격 **수치 비교가 없는 시나리오 설명**을 기존 `document`/`concept` content로 유지한다. `chatbot_graph.py`는 문서 검색·검증을 사용한다. validator의 미지원 조합 허용 폭은 넓히지 않는다. | LI·NI·CO 각각에서 출처로 확인된 배터리 수요 사실과 “수요가 둔화된다면”이라는 조건부 방향을 분리하여 표시하며 모든 사실 문장에 직접 근거를 인용한다. | 둔화 규모, 가격 변화량, 인과계수, 한국 영향은 산출하지 않는다. 세 광종 중 직접 근거가 없는 것은 그 부분을 명시하고 부분 답변하거나 전체 근거가 없으면 기권한다. |
| 5 | **Q21/Q22 출처 우선**: 현행 `document.retrieve` 진입 후 근거 미확보. `챗봇_public_내부지식_개념질의_대응_260921.md`의 최종 정책은 무출처 일반 설명 금지다. | `chatbot_graph.py`의 문서 본문 검색 적합성·근거 귀속을 Q15와 함께 개선하고, 필요 시 `action_contract.py`의 topic을 구체화한다. Q22의 HHI·수입의존도·가격변동성 각각에 정의·분모·기간 근거가 없으면 정적 답변 템플릿을 추가하지 않는다. | Q21은 USGS의 **미국 사례**와 재활용 제약을 그 범위로 인용. Q22는 세 개념의 정의와 가상 예시를 출처·산식에 연결하고 실제 한국 지표로 오인시키지 않는다. | 직접 본문·문장별 인용 검증이 불충분하면 현행 `source_unavailable`, `citations=[]`, 표·차트 0건을 **정상 수락**한다. 모델 내부 지식만으로 성공 처리하지 않는다. |

Q07 제품 규격은 가격기준 마스터 대사 후 별도 소규모 후보로 남긴다. Q05/Q06/Q11/Q12/Q13/Q24/Q25/Q29는 연산 코드가 있어도 실자료·기간 공백이 있어 실제값 성공으로 올리지 않는다. Q02/Q08/Q09/Q10/Q16/Q18/Q19는 현행 요청 수준의 검증 원천이 없다. Q26/Q27/Q30의 정상 기권은 유지한다. Q03/Q04는 개발용 더미 **시연**이며 실제 통계 성공으로 승격하지 않는다.

## 검증 순서와 종료 조건

1. **사전 SQL/문서 대사**: 니켈 선택 기준의 가격행·관측일·통화/중량 코드, `ai_dev_dummy_load` 추적키를 조회한다. USGS_2026의 실제 OKF 본문 절과 public PageIndex 접근 가능성을 확인한다. 수치가 기존 문서와 다르면 실제 조회값을 기준으로 계획의 예시 수치를 교체한다.
2. **계약 테스트**: `inhouse/rag_core/tests/`에서 Q20이 단일 문서 content로, Q28이 2025년·300%·가격기준을 갖춘 `price.verify_claim`으로 매핑되는지 확인한다. Q15/Q21/Q22의 topic·requirement_id·role 보존과 Q02/Q26/Q27/Q30 기권 경계를 확인한다.
3. **어댑터·검색 테스트**: 선택 가격기준의 단위/더미 경고, 혼합 실가격·더미 가격, 기간 부족, 잘못된 가격기준을 검증한다. 문서 검색은 관련 OKF **본문**과 실제 절을 반환하는지, 제목만 있는 경우 기권하는지 확인한다. public/private 접근 필터를 회귀 검사한다.
4. **배포 전 게이트**: `inhouse/rag_chat/tests/verify_chatbot_changes.sh`, 관련 unittest, `git diff --check`를 통과한다. 구현 담당자가 `inhouse/rag_chat/Containerfile` 기반 테스트 이미지를 빌드·교체할 때 이미지 ID·실행 프로세스·코드 해시를 확인한다. PageIndex `lru_cache`와 MCP 세션 캐시를 비우기 위해 대상 컨테이너를 재시작한다.
5. **실제 수락**: 동일 public/auto `/pubchat`에서 Q01~Q30 원문을 전수 재실행한다. Q23→Q24→Q25는 **새 응답**의 `session_id`를 전달한다. 문항별 요청·SSE·done·인용·표·차트·abstain_reason을 저장하고 기존 `data_archive/validation_runs/rag_chat_q30_live_260922/` 기준선과 비교한다. Q03/Q04/Q14/Q17의 기능 경로, Q02/Q26/Q27의 적정 기권, Q30 `out_of_scope`, Q12 더미 통관 차단, Q24/Q25 후속 실패 연쇄를 필수 회귀로 본다. 인용 없는 성공, 단위 추측, 더미의 실측 둔갑, 원천 없는 인과 설명은 실패다.

수정→검증은 **최대 5라운드**에서 종료한다. 매 라운드에 변경 파일·SQL/문서 절·테스트 출력·실제 요청/응답·남은 실패를 기록한다. 5회 안에 직접 근거를 확보하지 못한 문항은 정책에 맞는 기권을 유지하고, 미해결 원천 공백을 별도 후속 과제로 남긴다. 이 계획 작성 단계에서는 코드 수정·배포·커밋을 하지 않는다.
