- 이 페이지는 선택한 광종의 매장량 또는 생산량(둘 중 하나)을 주로 다룬다.
  cross_measure_comparison 근거가 없으면 분석 대상이 아닌 다른 항목(예:
  생산량 조회인데 매장량)과 비교·환산하지 않는다 — 그 근거가 있을 때만
  major_changes 마지막 문장으로 그대로 옮겨 쓴다(PDF의 "매장량 2위 호주는
  생산량 8위" 같은 교차 비교, 순위·비중 숫자를 새로 계산하지 않는다).
- 세계 전체 규모의 변화와 상위 국가 집중도(cr3·cr5) 변화를 연결해 분포가
  넓어졌는지 집중됐는지 판단한다.
- required=true인 근거는 반드시 사용하고, optional 근거는 핵심 흐름에 필요할 때만 선택한다.
- 같은 섹션의 관련 근거는 한 문장에 최대 3개까지 연결할 수 있으며, 근거를 단순 나열하지 않는다.
- 한 근거에 서로 다른 국가의 변화가 함께 있으면 두 문장으로 나누되 같은 내용을 반복하지 않는다.
- core_diagnosis는 current_state·period_total_change를 연결해 "[연도] 세계
  [광종] [매장량/생산량]은 [수치][단위]로, [기간]년간 [증감률]% [증가/감소]했습니다"처럼
  1~2문장으로 쓴다.
- major_changes는 current_leaders·third_country를 이용해 1~3위 국가의
  규모·비중·순위를 2~3문장으로 설명한다. extreme_change_countries
  근거가 있으면(2026-09-09 발주처 업무지시서 §3.3 대응 신설 — "매장량이
  가장 크게 증가/감소한 국가", top3 밖 국가도 포함될 수 있다) 그대로
  옮겨 마지막 문장으로 덧붙인다 — 이미 완성 문장이니 새 국가·수치를
  지어내지 않는다. **extreme_change_countries는 항상 evidence_ids가
  그 하나뿐인 독립된 문장으로 쓴다** — 렌더링 단계가 이 근거를
  evidence_id 기준으로 감지해 "주요 변화"라는 별도 절로 분리해 보여주므로
  (map_global의 korea_route_rank와 같은 처리), 다른 근거와 한 문장에
  섞으면 그 다른 근거의 내용까지 "주요 변화" 절로 잘못 끌려간다. 근거를
  결합해야 하는 문장(예: current_leaders+third_country, leading_country_
  changes+concentration_change)은 extreme_change_countries가 아닌
  다른 근거끼리로 만든다.
- current_position은 leading_country_changes·concentration_change·
  current_concentration_structure를 연결해 국가별 기간 변화와 CR3/CR5
  집중도 변화, 그리고 그 구조적 의미를 2~3문장으로 쓴다.
- 전체는 5~9문장으로 쓰며 같은 수치나 판단을 다른 섹션에서 반복하지 않는다.
- `상위 국가 중심`, `특정 한 국가가 압도하지 않음` 같은 판단은 이를 뒷받침하는 비중과 함께 쓴다.
- 비교연도 값이 없는 국가를 0으로 보거나 매장량·생산량이 새로 생겼다고 표현하지 않는다.
- 매장량·생산량의 수치 변화는 `성장`보다 `증가` 또는 `감소`로 표현한다.

- 물량은 근거의 `약 N만톤`·`약 N억톤` 단위를 그대로 유지한다. 숫자만 옮기고 만·억 단위를 생략하거나 재환산하지 않는다.
