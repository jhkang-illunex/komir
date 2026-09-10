- 이 페이지는 광물종합지수와 그 하위지수인 메이저금속지수·희소금속지수를
  함께 다룬다. 세 지수 모두 포인트 단위이며 기준연도 환산 근거(예: 특정
  연도=1000)는 evidence에 없으므로 언급하지 않는다 — "[일자] 기준 지수는
  [포인트]입니다"처럼 현재 값만 서술한다.
- core_diagnosis는 current_state·medium_long_term_contrast를 연결해
  "종합지수는 [포인트]로, 전월 대비 [상승/하락/보합]했지만 1년 전보다
  [고/저] 수준입니다"처럼 현재 지수와 단기·1년 방향을 한 문장으로 판단한다.
  medium_long_term_contrast 근거가 없으면(조회기간에 1년 비교값 없음)
  이 문장은 만들지 않는다. 이어서 period_value_comparison 근거가 있으면
  (2026-09-10 발주처 피드백[3] 신설 — 전주/전월/전년 동기의 실제 지수값과
  등락률을 함께 밝힌다) 그 문장을 그대로 옮긴다 — 이미 "전주 [값]포인트
  대비 [등락률]% 상승, 전월 ..., 전년 동기 ...했습니다." 형태로 완성된
  문장이라 값·등락률을 새로 계산하거나 순서를 바꾸지 않는다. 두 근거
  모두 없으면 core_diagnosis는 current_state 하나로만 쓰고, major_changes
  근거(composite_recent_changes 등)를 core_diagnosis로 끌어오지 않는다.
- major_changes는 composite_recent_changes(전주·전월 비교)와
  weekly_subindex_comparison/monthly_subindex_comparison/yearly_subindex_comparison
  (메이저·희소 하위지수의 전주·전월·전년 비교)을 연결해 어느 하위지수의
  변화가 두드러졌는지 설명한다. weekly_subindex_comparison에 포함된 두 하위지수의
  현재 포인트 값도 빠뜨리지 않는다. 두 하위지수 방향이 다르면(예: 메이저 상승·
  희소 하락) 그 차이를 명시한다.
- current_position은 period_range_position·overall_pattern을 연결해
  조회기간 고저점 위치와 단기·장기 방향을 이어 현재 수준의 의미를 판단한다.
- 하위지수의 방향이 다르면 전체 지수만으로 가려지는 차별화를 명시하되
  구체적인 견인 광종이나 원인은 evidence에 없으므로 추정하지 않는다.
- index_top_weighted_minerals(있으면, major_changes) — 광물종합·메이저금속·
  희소금속지수 각각의 구성 광종과 산정 가중치(%)다. 이번 조회기간에 그
  광종의 가격이 실제로 오르내렸는지는 evidence에 없으므로, "이 광종의
  가격 상승/하락이 원인"이라고 쓰지 않는다 — "비중이 큰 구성 광종이라
  지수 변동에 상대적으로 민감하다"처럼 구조적 사실로만 그대로 옮긴다.
