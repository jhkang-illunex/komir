# 결론

현재 문제는 Adapter·Renderer보다 앞단의 `자연어 → IntentPlan/ActionPlan` 변환이 lexical grammar에 과도하게 묶여 있어서 발생합니다.

가장 안전한 방향은 기존 Action·Adapter·Renderer를 유지하고, `extract_action_plan()` 앞에 별도의 typed Semantic Intent Layer를 추가하는 것입니다.

새 Semantic Layer는 다음 원칙을 따릅니다.

- 자연어 표현을 canonical semantic requirement로 정규화합니다.
- `trade.concentration`, `price.series` 같은 physical action 이름은 직접 생성하지 않습니다.
- 기존 IntentPlan·ActionPlan resolver와 `validate_action_plan()`을 재사용합니다.
- 기존 lexical shortcut은 deterministic fallback으로 유지합니다.
- Semantic Parser가 실패하면 기존 LLM IntentPlan 경로로 즉시 돌아갑니다.
- Adapter와 Renderer는 1단계에서 수정하지 않습니다.
- `off` feature flag를 통해 기존 동작으로 즉시 rollback할 수 있게 합니다.

우선 `trade.import_concentration` 하나를 대상으로 다음 표현들이 동일한 semantic representation으로 수렴하는지 검증하는 것이 적절합니다.

- 니켈 수입 집중도를 알려줘
- 니켈 수입이 특정 국가에 얼마나 몰려 있어?
- 니켈 수입선이 편중되어 있어?
- 니켈을 일부 국가에 많이 의존하고 있어?
- 니켈 공급국이 몇 나라에 집중돼 있나?

1차 목표는 현재 QA 문장을 외워서 맞히는 시스템을 전면 재작성하는 것이 아니라, 같은 의미의 자연어 표현을 동일한 typed requirement로 변환하면서 기존 실행·검증·렌더링 계층을 보존하는 것입니다.
