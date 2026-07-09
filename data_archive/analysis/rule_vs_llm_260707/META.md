# META — 룰기반 vs LLM 추출 비교 원자료
- 생성: 2026-07-07, 9개 문서 동일 passage를 RuleExtractor와 LLMExtractor(gemma-4-26b-a4b, localhost:52302)에 병렬 투입
- 파일: llm_vs_rule.pkl(1차 — jsonutil 이중인코딩 버그로 LLM쪽 일부 유실 상태), llm_vs_rule_v2.pkl(버그 수정 후)
  {문서명: {rule: [...], llm: [...]}} 구조, pickle
- 핵심 발견: IEA 문서에서 룰=1건 vs LLM=6건(DRC 코발트 수출중단 등 룰이 구조적으로 놓침) → provider 전환 결정 근거
- 상세: 데이터수집현황 §8
