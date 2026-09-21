# PageIndex·OKF 조회 r16 변경 및 배포 기록

## 변경 범위

- `inhouse/rag_core/ragkit/action_contract.py`: `document.lookup`, `mine.profile`, `mine.rank`의 닫힌 intent·slot 계약과 중복 요구 정규화. 광산 단위 질문을 광종·HS 교역 집계로 오분류해 발생하던 `slot_unresolved`를 제거했다.
- `inhouse/rag_core/ragkit/chatbot_graph.py`: PageIndex·OKF 본문과 명시 문서 선택을 기존 MCP 경로에 연결했다. 공개 접근 필터를 유지하며, 출처가 없는 경우 답변을 보류한다. 명시 HS 코드의 금액·중량 근거가 같은 코드·원천·단위를 충족하면 모델 출력 형식 오류로 근거가 소실되지 않도록 결정적으로 확인한다.
- `inhouse/rag_core/retrieval/pageindex.py`, `evidence.py`: 지정 문서의 실제 표 행을 선택하고 광산명·위치 열과 OKF 경로·행 번호를 인용에 보존한다. 회사명처럼 여러 광산에 걸친 질문은 단일 위치로 답하지 않는다.
- `inhouse/rag_core/retrieval/mine_aggregate.py`: 개별 광산의 국가 필터, 생산량·매장량 순위, 기간 내 생산량 증가 순위를 조회한다.
- `inhouse/rag_chat` 및 MCP 클라이언트·서버: 새 action의 공개/비공개 라우팅과 응답을 연결했다.

설계와 질문별 독립 판정은 [intent 설계](챗봇_PageIndex_OKF_intent_설계_260922.md), [독립검증](챗봇_PageIndex_OKF_독립검증_260922.md)에 있다.

## 배포 전 검증

- 격리 이미지 `sha256:91457daf43306a7671f814dd4312a653a3aa4b5e961dc6e5fddbe2b2fbbef76c`(r16), 18021 포트에서 수용했다.
- r10f 원문 30건 모두 완료. 답변 7, 실제 원천 부족 22, 질문 자체가 범위 밖인 Q30 1. `slot_unresolved`와 `unsupported_combination`은 0.
- JV Inkai·Escondida는 OKF 원문 32·33행을 인용했다. 근거 없는 개별 광산 수입액 질문은 7/7회 무인용 `source_unavailable`이었다. HS 2603000000은 별도 3회와 전체 회귀 1회에서 금액·중량 원천 2건으로 답했다.
- 관련 rag_core 단위 테스트 66건, rag_chat 테스트 23건, `git diff --check` 통과.

## Git·서버 반영

이 절에는 실제 커밋·푸시와 서버 교체 후 이미지, 포트, 요청·응답을 기록한다.
