# -*- coding: utf-8 -*-
"""분석문 생성 지시문과 근거로 한정된 payload — 외부 저장소
`komis_report_generator/analysis/prompts.py` 이식본(2026-08-13).

**원본에서 뺀 것**: `NARRATIVE_INSTRUCTIONS`·`build_narrative_payload()`.
둘은 profile_id 기반 분석 경로(`AnalysisResponse`/`NarrativeOutput`) 전용인데,
외부repo에서도 5개 운영 엔드포인트가 아니라
`experiments/analysis_summary_evaluation/profile_service.py`만 쓴다(2026-08-13
grep 실측) — 소비자 없는 코드를 들여오지 않는다(CLAUDE.md §4).

그 밖에는 지시문 문구·출력계약(section_sentence_ranges 등)까지 원본 그대로다.
import 경로만 상대경로로 바꿨다.

**2026-08-26**: 아래 지시문 상수들은 이제 "DB에 없을 때 쓰는 기본값"이다.
`summary_instructions()`가 `prompt_store.get_prompt()`로 `ai_cfg.cfg_prompt`
(PostgreSQL, PG_DSN) 캐시를 먼저 확인하고, 해당 `prompt_key` 행이 없으면 이
상수로 폴백한다 —
운영 중 프롬프트 문구를 바꾸고 싶으면 DB 행을 갱신하고 `POST /admin/
prompts/reload`를 호출하면 되고, DB를 아직 안 채웠거나 접속이 끊겨도 이
상수들 덕에 서비스가 하드코드 상태로 계속 동작한다(`prompt_store.py` 참고).

**2026-08-27(skeptic 감사 SC-004·005·006)**: (1) 이 파일의 `PROMPTS`가 프롬프트
본문의 단일 소스이고 `seed_prompts.py`는 이걸 import해 DB에 심는다(폴백과
시드가 따로 놀던 드리프트 제거). (2) 섹션별 문장수 계약(`SECTION_SENTENCE_RANGES`
등)도 여기 한 곳에만 두고 `summary.py::_validate_llm_summary`가 같은 상수를
쓴다. (3) payload에 `detected_patterns`(code·label)를 실어 보낸다 — price
프롬프트가 `near_period_high/low` 패턴을 참조하는데 정작 LLM은 그걸 받은 적이
없었다(실측).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from . import prompt_store
from .additional_summary import ADDITIONAL_PAGE_CONTEXTS, SummaryPageContext
from .komir_summary import KOMIR_PAGE_CONTEXTS
from .models import AnalysisSummaryResponse
from .policy import PagePolicy, load_page_policy

# 아래 10개 상수 + `PROMPTS`가 분석요약 프롬프트의 **단일 소스**다(2026-08-27,
# skeptic 감사 SC-004). 이전에는 `seed_prompts.py`(DB 시드)와 이 파일(DB 미접속
# 폴백)이 같은 문구를 따로 들고 있어 10키 중 9키가 조용히 어긋나 있었다 — 예:
# price 폴백은 "연속기간 언급 금지"였는데 계산기는 `price_streak` 근거를 만들고
# 검증기는 모든 evidence_id 사용을 요구하므로, DB가 죽은 동안 price LLM 출력이
# 항상 검증 실패→규칙기반으로 떨어졌다. 이제 `seed_prompts.py`가 여기 `PROMPTS`를
# import해 DB에 심는다(런타임 모듈이 시딩 스크립트에 의존하지 않는 방향).
# 2026-08-26: 발주처 제공 KOMIS 템플릿 PDF 2종 + 8개 페이지 실데이터 덤프를
# 근거로 다시 썼다(위 모듈 docstring "실제 반영 범위" 참고). 계산 레이어가
# 만드는 EvidenceClaim 범위를 벗어나는 지시는 넣지 않았다 — 검증기
# (`summary.py::_validate_llm_summary`)가 근거 밖 숫자·단계명·원인 서술을
# 걸러 규칙기반으로 되돌리기 때문에, 지어내도 실제로 적용되지 않는다.
SUMMARY_COMMON_INSTRUCTIONS = """\
당신은 KOMIS 수치를 단순히 읽어 주는 사람이 아니라,
확인된 근거 사이의 관계를 설명하는 분석 편집기다.
- allowed_evidence에 있는 사실만 사용하고, 각 문장에 사용한 evidence_id는 JSON의
  `evidence_ids` 필드에만 적는다 — 본문 `text` 안에 `(current_state)`처럼 id를 괄호로
  덧붙이지 않는다(id가 본문에 있으면 검증에서 거부된다).
- 일자는 `2026년 8월 25일`처럼 `YYYY년 M월 D일`로, 월은 `YYYY년 M월`로 쓴다 —
  `2026-08-25`·`2026-08` 같은 원형 표기를 본문에 남기지 않는다(숫자는 그대로).
- 관련 근거 2~3개를 한 문장에 연결해 대비, 지속 여부, 현재 위치 또는 구조적 의미를 설명한다.
- 모든 근거를 항목별로 다시 나열하지 말고, 수치가 보여 주는 핵심 판단을 먼저 쓴다.
- 숫자, 기간, 단계, 순위, 변화 방향을 바꾸거나 새로 만들지 않는다.
- 원본 DB 행, 내부 테이블명, 제공되지 않은 원인·사건·단위·발생확률을 추정하지 않는다.
- 같은 수치나 판단을 다른 섹션에서 반복하지 않는다.
- `확인할 수 있다`, `나타났다`만 반복하지 말고 `~지만`, `~인 반면`, `따라서`로 관계를 분명히 한다.
- `YYYY-MM` 형식의 기준월은 숫자를 바꾸지 않고 `YYYY년 M월`로 자연스럽게 쓴다.
- 분석범위, 데이터 결측, 면책 문구는 본문에 쓰지 않는다.
- 최근 한 달 변화만으로 장기 `추세`라고 표현하지 않는다.
- 발주처 보고서 문체를 따라 문장은 `~했습니다`, `~입니다`, `~로 나타났습니다`처럼
  격식체로 끝맺는다(예시 문구의 `~다` 종결은 evidence 원문일 뿐 그대로 베끼지 않는다).
- allowed_evidence의 evidence_id는 **빠짐없이 정확히 한 번씩** 사용한다 — "(있는
  경우)"라고 적힌 근거도 allowed_evidence에 실려 왔으면 반드시 쓴다(생략·중복 금지).
  한 문장에 묶는 근거 수는 output_contract.max_evidence_ids_per_sentence(보통 3)를
  넘기지 않고, 그래도 남으면 그 절의 문장수 상한(output_contract.section_sentence_
  ranges) 안에서 문장을 늘린다. 한 문장에 적은 사실·숫자의 근거 id는 **전부** 그
  문장의 evidence_ids에 넣는다(넣지 않은 근거의 숫자를 쓰면 검증에서 거부된다).
- 각 근거는 allowed_evidence의 section 값에 지정된 절(core_diagnosis/major_changes/
  current_position)에서만 쓴다 — 다른 절로 옮기거나 두 절에서 겹쳐 쓰지 않는다.
  어떤 절에 지정된 근거가 1개뿐이면 그 절은 그 근거 하나로만 쓴다.
"""

MARKET_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 시장동향지표(0~100점, 5단계: 신중 0~20·주의 20~40·중립 40~60·
  관심 60~80·기회 80~100)다. 점수가 높을수록 중장기 가격위험이 낮다는 뜻이다.
- core_diagnosis는 current_state·latest_score_change 근거를 연결해
  "[기준월] 기준 [광종]의 시장동향지표는 [점수]점으로 [단계]다"에 최근 한 달
  변화 방향이 같은 흐름인지 다른 흐름인지를 한 문장으로 판단한다.
- major_changes는 grade_streak·grade_transition·largest_monthly_score_change를
  연결해 다음 두 형태 중 근거에 맞는 쪽으로 쓴다:
  (a) 이번 조회기간에 단계 전환이 있었으면 "[단계]로 상승/하락했습니다"처럼
      전환을 명시한다.
  (b) 전환이 없었으면 grade_streak의 유지개월수를 그대로 써서
      "[단계]를 [N]개월째 유지중입니다"처럼 유지 사실만 쓴다.
  전환 시점과 최대 월간 변화 시점이 다르면 인과관계 없이 시간 순서로만 구분한다.
- current_position은 period_average_position을 이용해 최근 가격 움직임과
  조회기간 평균 대비 점수를 연결하되 인과관계로 단정하지 않는다.
- 단기 점수 개선에도 평균보다 위험이 높으면
  `단기 완화에도 평균보다 높은 위험`처럼 남은 약점을 분명히 쓴다.
- 단계 유지 자체를 정체·고착으로 해석하지 않고 위험 단계가 지속됐다고만 설명한다.
- "주요 요인" 절은 만들지 않는다 — 가격 변동 원인이나 투자환경지수 요인을
  분해한 근거가 없으므로, 단계·점수·유지기간 사실만 쓰고 원인은 추정하지 않는다.
"""

SUPPLY_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 수급동향지표(0~100점, 5단계: 주의 0~5·관심 5~20·안정 20~80·
  원활 80~100. 0~1점 구간은 현재 데이터만으로 단계를 확정하지 않아 evidence에
  단계명이 없을 수 있다 — 그 경우 없는 단계명을 지어내지 않는다)다. 점수가
  높을수록 수급 안정성이 강하다는 뜻이다.
- core_diagnosis는 current_state·latest_score_change 근거를 연결해
  현재 수급 단계와 최근 수급 안정성 변화가 같은 방향인지 한 문장으로 판단한다.
- major_changes는 grade_streak·grade_transition·largest_monthly_score_change를
  연결해 다음 두 형태 중 근거에 맞는 쪽으로 쓴다:
  (a) 단계 전환이 있었으면 "[단계]로 상승/하락했습니다"처럼 전환을 명시한다.
  (b) 전환이 없었으면 grade_streak의 유지개월수를 그대로 써서
      "[단계]를 [N]개월째 유지중입니다"처럼 유지 사실만 쓴다.
  최대 월간 변화 시점과 전환 시점이 다르면 인과관계 없이 시간 순서로만 구분한다.
- current_position은 period_average_position을 이용해 최근 가격 움직임과
  조회기간 평균 대비 안정성을 연결하되 원인으로 단정하지 않는다.
- 단기 개선에도 평균보다 안정성이 낮으면 `단기 반등에도 평균 수준을 회복하지 못함`을 분명히 쓴다.
- 단계 유지 자체를 정체·고착으로 해석하지 않고 수급 단계가 지속됐다고만 설명한다.
- "주요 요인" 절은 만들지 않는다 — 가격리스크·세계 수급비율·공급 편중도 등으로
  변동성을 분해한 근거가 없으므로, 단계·점수·유지기간 사실만 쓰고 원인은 추정하지 않는다.
"""

COMPOSITE_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 광물종합지수와 그 하위지수인 메이저금속지수·희소금속지수를
  함께 다룬다. 세 지수 모두 포인트 단위이며 기준연도 환산 근거(예: 특정
  연도=1000)는 evidence에 없으므로 언급하지 않는다 — "[일자] 기준 지수는
  [포인트]다"처럼 현재 값만 서술한다.
- core_diagnosis는 current_state·medium_long_term_contrast를 연결해
  "종합지수는 [포인트]로, 전월 대비 [상승/하락/보합]했지만 1년 전보다
  [고/저] 수준이다"처럼 현재 지수와 단기·1년 방향을 한 문장으로 판단한다.
  medium_long_term_contrast 근거가 없으면(조회기간에 1년 비교값 없음)
  core_diagnosis는 current_state 하나로만 쓰고, major_changes 근거
  (composite_recent_changes 등)를 core_diagnosis로 끌어오지 않는다.
- major_changes는 composite_recent_changes(전주·전월 비교)와
  weekly_subindex_comparison/monthly_subindex_comparison/yearly_subindex_comparison
  (메이저·희소 하위지수의 전주·전월·전년 비교)을 연결해 어느 하위지수의
  변화가 두드러졌는지 설명한다. 두 하위지수 방향이 다르면(예: 메이저 상승·
  희소 하락) 그 차이를 명시한다.
- current_position은 period_range_position·overall_pattern을 연결해
  조회기간 고저점 위치와 단기·장기 방향을 이어 현재 수준의 의미를 판단한다.
- 하위지수의 방향이 다르면 전체 지수만으로 가려지는 차별화를 명시하되
  구체적인 견인 광종이나 원인은 evidence에 없으므로 추정하지 않는다.
"""

MINERAL_MAP_SUMMARY_INSTRUCTIONS = """\
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
  [광종] [매장량/생산량]은 [수치][단위]로, [기간]년간 [증감률]% [증가/감소]했다"처럼
  1~2문장으로 쓴다.
- major_changes는 current_leaders·third_country를 이용해 1~3위 국가의
  규모·비중·순위를 2~3문장으로 설명한다.
- current_position은 leading_country_changes·concentration_change·
  current_concentration_structure를 연결해 국가별 기간 변화와 CR3/CR5
  집중도 변화, 그리고 그 구조적 의미를 2~3문장으로 쓴다.
- 전체는 5~8문장으로 쓰며 같은 수치나 판단을 다른 섹션에서 반복하지 않는다.
- `상위 국가 중심`, `특정 한 국가가 압도하지 않음` 같은 판단은 이를 뒷받침하는 비중과 함께 쓴다.
- 비교연도 값이 없는 국가를 0으로 보거나 매장량·생산량이 새로 생겼다고 표현하지 않는다.
- 매장량·생산량의 수치 변화는 `성장`보다 `증가` 또는 `감소`로 표현한다.
"""

PRICE_FORECAST_SUMMARY_INSTRUCTIONS = """\
- core_diagnosis는 전망 시작·종료 변화와 경로 전환을 연결해
  전체 방향과 경로의 안정성을 한 문장으로 판단한다.
- major_changes는 첫 예측값과 고점·저점을 연결해
  어느 시점에 상승·하락 압력이 두드러지는지 한 문장으로 설명한다.
- current_position은 마지막 값의 고저 범위 내 위치를 이용해
  전망 종단부가 강세·약세 어느 쪽에 가까운지 설명한다.
- 예측가격을 확정된 실제가격처럼 표현하지 말고 `예측된다`, `전망된다`, `제시됐다`로 구분한다.
- 예측 정확도, 발생확률, 외부 사건과 가격 변화의 원인을 추정하지 않는다.
- 전체 변화율과 중간 등락을 구분하고, 중간 반등만으로 전체 전망 방향을 뒤집어 설명하지 않는다.
- 예측기간의 등락을 `확정`, `실현`, `발생`으로 표현하지 않는다.
- 제공되지 않은 가격 단위나 결측정보를 본문에 추가하지 않는다.
"""

# 2026-08-26: `price`/`map_korea`/`map_global` LLM 배선 추가와 함께 실제
# 지시문으로 채웠다(위 모듈 docstring "실제 반영 범위" 참고). `komir_summary.py`가
# 만드는 EvidenceClaim id(current_state·day_over_day·week_avg/month_avg/
# year_avg·period_range, 또는 current_state·top1_country·top3_concentration·
# period_total_change) 범위 안에서만 쓰도록 지시한다.
# 2026-08-28: `price_driver_event_1`/`_2`(geo_events 요청 필드가 있을 때만
# 생기는 선택적 근거, PDF §1-1 "가격 변동의 주요 요인" 대응) 추가.
PRICE_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 등급·단계가 없다. 실거래가와 전일·전주평균·전월평균·전년평균
  대비 등락만 다룬다.
- core_diagnosis는 current_state 근거로 "[기준일] 기준 [광종] 실거래가는
  [가격]이다"를 한 문장으로 쓴다.
- major_changes는 day_over_day와 week_avg/month_avg/year_avg 중 evidence에
  있는 항목만 골라 "[전일 또는 직전 관측치] 대비 [등락률]%, 전주평균 대비
  [등락률]%, 전월평균 대비 [등락률]%, 전년평균 대비 [등락률]% [상승/하락]
  했습니다"처럼 있는 비교만 이어 쓴다 — 없는 비교기간을 만들어 채우지
  않는다. evidence의 등락률 숫자를 그대로 옮기고 평균값·차이를 새로 계산해
  적지 않는다. 이 페이지는 한 문장에 근거 5개까지 묶을 수 있으므로(output_
  contract.max_evidence_ids_per_sentence=5) 전일·전주·전월·전년 비교를 한 문장에
  이어 써도 되지만, 그 문장의 evidence_ids에 쓴 근거 id를 전부 넣는다. day_over_day 근거 문장이 "전일(...)"로 시작하면 그대로 "전일"을
  쓰고, "직전 관측치(...)"로 시작하면 관측 간격이 하루가 아니라는 뜻이니
  "전일"로 바꿔 쓰지 말고 "직전 관측치"를 그대로 유지한다.
- current_position은 period_range 근거로 조회기간 최고·최저가 대비 현재
  가격의 위치를 설명한다. near_period_high/near_period_low 패턴이 있으면
  고점·저점 근접 사실만 쓴다.
- compare_overall_change 근거가 있으면(비교광종 지정 시) current_position에
  두 번째 문장으로 "같은 조회기간 동안 [비교광종]은 [등락률]% 변동한 반면,
  [광종]은 [등락률]% 변동했다"를 그대로 옮겨 쓴다 — 어느 쪽이 더 크게
  움직였는지는 숫자로만 드러내고, 원인이나 상관관계를 추정하지 않는다.
- price_streak 근거가 있으면(연속 2회 이상 같은 방향 변동) major_changes에
  "[N][일/주/월] 연속 [상승세/하락세/보합세]를 보이고 있다"를 그대로 옮겨
  쓴다. 근거가 없으면(연속 변동이 1회뿐이거나 계산 불가) 지속 기간을
  추정해서 만들어 쓰지 않는다.
- price_driver_event_1(있으면 _2도) 근거가 있으면 "가격 변동의 주요 요인으로는
  [근거 문장 그대로]" 형태로 major_changes 마지막에 덧붙인다 — 근거 문장은
  이미 "조회기간 중 [국가]에서 [공급 감소/공급 증가/가격 상승/가격 하락/
  수요 감소/수요 증가/동향 변화] 흐름과 맞물린 사안이 있었다([날짜] 기준)"
  형태로 완성돼 있으니 그대로 옮기고, 새 원인·인과관계·수치를 지어내지
  않는다("맞물린"·"동시발생" 톤을 유지 — "때문에"·"영향으로"처럼 이 근거가
  가격 변동을 일으켰다고 단정하는 표현으로 바꿔쓰지 않는다). 근거가 없으면
  (geo_events가 없는 요청) 이 문장 자체를 만들지 않는다 — 원인을 추정해서
  채우지 않는다.
- price_driver_event_* 근거가 없을 때는 가격 변동의 원인(수급 이슈, 환율,
  지정학 이벤트 등)을 evidence 없이 절대 추정하지 않는다.
- inventory_level 근거가 있으면 current_position에 재고량 수준과(있으면) 전일
  또는 직전 관측치 대비 등락을 그대로 옮겨 쓴다 — 근거 문장이 이미 완성된
  문장이니 새 단위·거래소명(예: "LME"·"톤")을 지어 붙이지 않는다. 근거가
  없으면(inventory_level이 없는 요청) 재고량을 언급하지 않는다 — 다른 절의
  수치로 재고 수준을 추정해서 채우지 않는다.
- volatility·ma_rsi·percentile_position·drawdown·inventory_context·
  relative_value 근거는(2026-08-31 신설) 각각 current_position에 별도
  문장으로 그대로 옮겨 쓴다 — 이질적인 주제라 major_changes의 등락률
  묶어쓰기와 달리 한 문장에 합치지 않는다. 근거가 없으면(관측치 부족으로
  계산되지 않음) 그 문장 자체를 만들지 않는다 — "데이터가 부족하다"는
  문장을 지어내지 않는다.
- insufficient_history 근거가 있으면(신규 6개 층 중 일부가 관측치 부족으로
  생략됨) current_position 마지막 문장으로 그 근거를 그대로 옮겨 쓴다 —
  어떤 층이 왜 빠졌는지 새로 설명을 덧붙이지 않는다. 근거가 없으면 이
  문장 자체를 만들지 않는다.
- "추세"·"상관계수"라는 단어는 이 페이지를 포함해 어디에도 쓰지 않는다 —
  이동평균 관련 근거는 "이동평균"·"배열"로, 재고-가격 연동 근거는 "동행
  비율"로 이미 표현돼 있으니 그 어휘를 그대로 옮긴다(다른 표현으로
  바꿔 쓰지 않는다).
"""

MAP_KOREA_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 관세청 원천으로, 요청된 방향(수입 또는 수출) 기준 한국의
  상대국별 거래를 다룬다 — evidence의 current_state 문장이 이미 "수입총액"
  또는 "수출총액" 중 실제 조회 방향에 맞는 라벨로 쓰여 있으니 그대로
  옮기고, 다른 방향으로 바꿔 쓰지 않는다. 등급·단계는 없다.
- core_diagnosis는 current_state 근거를 그대로 한 문장으로 쓴다(금액 단위가
  evidence에 없으면 단위를 지어내지 않는다). evidence에 "{국가} 대상"이나
  특정 범위명(생산품유형·HS코드 등)이 붙어 있으면 그 한정어를 그대로
  살려서 쓴다 — 불필요한 수식어로 보여도 지우지 않는다(조회가 그 국가·
  범위로 좁혀졌다는 뜻이라 빼면 전체 광종 수치로 오해된다).
- major_changes는 top1_country·top3_concentration·top5_concentration(있는
  경우)을 연결해 1위국의 금액·비중, 상위 3개국 합산 비중(CR3), 상위 5개국
  합산 비중(CR5)을 순서대로 설명한다. evidence에 "이 범위 내"라는 표현이
  있으면 반드시 그 표현을 그대로 유지한다 — "전체의"와 뜻이 달라서(광종
  전체가 아니라 지정된 생산품유형/HS코드 범위 안에서의 비중), 생략하거나
  그냥 "비중은 X%"로 다듬으면 안 된다. 국가가 단 하나로 조회가 한정된
  경우엔 major_changes에 랭킹 문장 대신 "조회가 {국가} 한 국가로
  한정돼 있어 ... 전체 금액이다"류 단문 하나만 온다 — 이건 evidence
  누락이 아니라 정상이니 순위·비중을 새로 지어내 채우지 않는다.
- current_position은 period_total_change(있는 경우)로 직전 관측 대비
  총액 변동을 쓴다. single_snapshot 근거만 있으면(관측이 1건뿐) 다른 절과
  달리 "조회기간 관측이 1건뿐이라 기간별 변화는 계산하지 않았다"는 결측
  사실을 그대로 옮겨 쓴다(공통 지침의 "결측 문구 금지"는 서술 원인 설명에
  적용되는 것이지, 이 페이지처럼 결측 자체가 유일한 current_position
  근거일 때는 예외다).
- 집중도(상위국 비중)를 공급망 리스크로 단정하지 않고 사실만 서술한다.
- 증가·감소의 원인(관세, 대체 공급선 확보 등)은 evidence에 없으므로
  추정하지 않는다.
"""

MAP_GLOBAL_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 UN Comtrade 원천으로, 전세계 원산지→도착지 양자무역 "루트"
  단위 데이터를 다룬다 — 한국 한정 데이터가 아니라는 점을 흐리지 않는다.
  등급·단계는 없다.
- core_diagnosis는 current_state 근거로 "[기준일] 기준 [광종] 세계 교역
  총액은 [금액]이다"를 한 문장으로 쓴다.
- major_changes는 top1_country(1~3위 루트 랭킹)와 top3_concentration·
  top5_concentration을 연결해 상위 루트들의 금액·비중과 상위 3개·5개 루트
  합산 비중을 설명한다 — top5_concentration이 allowed_evidence에 있으면
  CR5 문장을 생략하지 말고 반드시 포함한다. 이어서 korea_route_rank 또는
  korea_route_absent 근거를 그대로 옮겨 대한민국이 관련된 루트의 순위를
  별도 문장으로 설명한다 — 순위·비중 숫자를 새로 계산하지 않는다. 근거가
  4개면 2~3문장으로 나눠 전부 쓴다.
- 루트는 근거의 `원산국→도착국` 화살표 표기를 그대로 쓰고, 화살표 표기 바로 뒤에는
  항상 `루트`를 붙인 뒤 조사를 쓴다("미국→독일 루트로 …", "페루→미국 루트가 …").
  "미국→독일로"처럼 화살표 표기에 조사를 직접 붙이거나 "미국에서 독일로 향하는"처럼
  풀어 쓰지 않는다 — 국가명 뒤 조사 오류(예: "미국로")를 피하기 위해서다.
- current_position은 period_total_change(있는 경우)로 직전 관측 대비
  총액 변동을 쓴다. country_yearly_trend 근거가 있으면 그 대신 그대로
  옮겨 쓴다 — 이건 "세계 교역 총액"이 아니라 KOMIS 차트 기준 특정 1개국
  자신의 연도별 수치이므로, 국가명·연도를 임의로 "세계"·"전체"로
  일반화하지 않는다(근거 문장에 이미 그 국가명이 명시돼 있으니 그대로
  옮기면 된다). period_total_change도 country_yearly_trend도 없이
  single_snapshot 근거만 있으면 map_korea와 같은 방식으로 관측이 1건뿐
  이라는 결측 사실을 그대로 옮겨 쓴다(공통 지침의 예외는 map_korea
  프롬프트와 동일하게 적용). 세 근거는 상호배타라 한 번에 하나만 온다.
- 루트에 등장하는 두 국가 사이의 인과관계(생산 차질, 수출 규제 등)는
  evidence에 없으므로 추정하지 않는다.
"""

PRICE_GROUP_SUMMARY_INSTRUCTIONS = """\
- 이 페이지는 광종 1개가 아니라 비철금속 또는 희소금속 그룹 전체를 다룬다.
  등급·단계는 없다.
- core_diagnosis는 current_state 근거로 "[그룹]금속 가격은 전주 대비 평균
  [증감률]% [상승/하락](, 전월 대비 평균 [증감률]% [상승/하락])했다"를 한
  문장으로 쓴다 — 전월 비교가 evidence에 없으면 전주 비교만 쓴다.
- major_changes는 group_movers(강세/약세 광종군)와 extreme_movers(최대
  상승·최대 하락 광종)를 근거에 있는 그대로 옮겨 쓴다 — "주요 요인"(가격
  변동 원인)은 evidence에 없으므로 절대 추정하지 않는다(다른 가격·지표
  페이지와 같은 이유).
- current_position은 group_composition 근거로 상승·하락·보합 광종 수를
  그대로 쓴다.
- 그룹 평균이 개별 광종 전부를 대표한다고 단정하지 않는다.
"""

PROMPTS = {
    "summary_common": SUMMARY_COMMON_INSTRUCTIONS,
    "indicator_market": MARKET_SUMMARY_INSTRUCTIONS,
    "indicator_supply": SUPPLY_SUMMARY_INSTRUCTIONS,
    "indicator_composite": COMPOSITE_SUMMARY_INSTRUCTIONS,
    "map_mineral": MINERAL_MAP_SUMMARY_INSTRUCTIONS,
    "forecast_price": PRICE_FORECAST_SUMMARY_INSTRUCTIONS,
    # 2026-08-27 price page_id 분리 — 비철금속/희소금속 지시문 내용은 그룹에 무관하게
    # 동일하다(비교광종 조건절은 데이터가 없으면 그냥 트리거되지 않는다, §models.py
    # validate_period가 이제 요청 단계에서 강제) — 그래서 같은 상수를 공유한다.
    "price_base_metals": PRICE_SUMMARY_INSTRUCTIONS,
    "price_minor_metals": PRICE_SUMMARY_INSTRUCTIONS,
    # 2026-08-28 — 같은 이유로 공유(§komir_summary.py::KOMIR_PAGE_CONTEXTS 주석).
    "price_iron_energy": PRICE_SUMMARY_INSTRUCTIONS,
    "price_other": PRICE_SUMMARY_INSTRUCTIONS,
    "map_korea": MAP_KOREA_SUMMARY_INSTRUCTIONS,
    "map_global": MAP_GLOBAL_SUMMARY_INSTRUCTIONS,
    "price_group": PRICE_GROUP_SUMMARY_INSTRUCTIONS,
}


#: 페이지별 섹션 문장수 계약 (최소, 최대) — LLM에 보내는 `output_contract`와
#: `summary.py::_validate_llm_summary`가 **같은 상수**를 쓴다(2026-08-27 skeptic
#: 감사 SC-005: 이전엔 두 파일에 복제돼 "글자 그대로 일치해야 한다"는 주석으로만
#: 묶여 있었다). map_mineral은 select_and_synthesize 모드라 별도 상수.
SECTION_SENTENCE_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    # 2026-08-27 반복 루프 1회차: 실 vLLM 384건 파일럿에서 major_changes 근거
    # 3개(grade_streak·grade_transition·largest_monthly_score_change)를 1문장에
    # 넣지 못해 근거 누락/절 이동으로 폴백하는 사례 → (1,2)로 완화.
    "indicator_market": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
    "indicator_supply": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
    "indicator_composite": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
    "forecast_price": {"core_diagnosis": (1, 1), "major_changes": (1, 1), "current_position": (1, 1)},
    # price의 current_position은 (1,2) — 비교광종(compare_observations)이 있으면
    # compare_overall_change 근거 1문장이 더 붙는다(2026-08-26. 2026-08-30 확인:
    # 비교광종은 price_* 4종 공통 기능이라 base_metals/iron_energy/other도
    # 동일하게 해당). major_changes는 근거가 최대 5개(전일·전주·전월·전년·
    # 연속)라 (1,3)(루프 1회차 완화).
    # 2026-08-31 사용자 통계확장 피드백으로 current_position이 (1,2)→(1,9)로
    # 커졌다 — 신규 6개 층(변동성·이동평균+RSI·백분위·낙폭국면·재고해석·
    # 상대가치)은 각각 이질적인 주제라 major_changes(동질적 등락률 반복)와
    # 달리 1근거=1문장으로 쓰는 게 자연스럽다(PRICE_SUMMARY_INSTRUCTIONS의
    # 해당 지시 참고). `models.py::SummaryNarrative.current_position`
    # max_length=9와 `komir_summary.py::_CURRENT_POSITION_HARD_CAP=9`를 반드시
    # 같이 맞춘다 — 위 ⚠ 미해결이던 (1,2) vs 하드제약 3의 불일치는 이번에
    # 상한을 정확히 맞춰 해소했다(9=9).
    "price_base_metals": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_minor_metals": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_iron_energy": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_other": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "map_korea": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
    # map_global major_changes는 근거 4개(1~3위 루트·CR3·CR5·한국 순위)라 (1,3).
    "map_global": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 1)},
    # 2026-08-27 신설 — group_movers·extreme_movers 2건까지 major_changes에.
    "price_group": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
}
MINERAL_MAP_SECTION_SENTENCE_RANGES: dict[str, tuple[int, int]] = {
    "core_diagnosis": (1, 2),
    "major_changes": (2, 3),
    "current_position": (2, 3),
}
MINERAL_MAP_TOTAL_SENTENCE_RANGE: tuple[int, int] = (5, 8)
MAX_EVIDENCE_IDS_PER_SENTENCE = 3
#: 페이지별 예외 — price는 PDF 1-1 템플릿이 전일·전주·전월·전년(·연속) 비교를 한
#: 문장에 담으므로 5(2026-08-27 반복 루프 4회차). `SummarySentence.evidence_ids`
#: pydantic 상한(5)이 절대 상한이다.
MAX_EVIDENCE_IDS_PER_SENTENCE_BY_PAGE: dict[str, int] = {
    "price_base_metals": 5,
    "price_minor_metals": 5,
    "price_iron_energy": 5,
    "price_other": 5,
}
_EVIDENCE_IDS_HARD_CAP = 5

_SECTIONS = ("core_diagnosis", "major_changes", "current_position")


# ────────────────────────────────────────────────────────────────────
# 페이지 정책·출력 계약의 "코드 기본값 + DB 오버레이" — 프롬프트 DB화 2단계
# (2026-08-27). 이전엔 지시문(content)만 DB였고 페이지 이름·정의·작성 제약·
# 정책버전은 YAML(indicator_market/supply)·dataclass(나머지 7종)에, 섹션 문장수
# 범위는 위 상수에 있었다. 이제 `ai_cfg.cfg_prompt`의 page_name/page_definition/
# analysis_constraints/policy_version/output_contract 컬럼이 값 단위로 이를
# 덮어쓴다(NULL = 코드 기본값). 코드 기본값은 그대로 남아 DB 없이도 동작한다.
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PageConfig:
    """한 페이지의 유효 정책·출력 계약(코드 기본값에 DB 컬럼을 덮은 결과)."""

    page_id: str
    name: str
    definition: str
    analysis_constraints: tuple[str, ...]
    policy_version: str
    section_sentence_ranges: dict[str, tuple[int, int]]
    total_sentence_range: tuple[int, int] | None
    max_evidence_ids_per_sentence: int
    #: 필드별 출처("db"|"code") — 검증 스크립트·디버깅용.
    source: dict[str, str]

    def as_context(self) -> SummaryPageContext:
        return SummaryPageContext(
            page_id=self.page_id,  # type: ignore[arg-type]
            name=self.name,
            definition=self.definition,
            analysis_constraints=list(self.analysis_constraints),
            policy_version=self.policy_version,
        )

    def output_contract_json(self) -> dict[str, Any]:
        """DB `output_contract` 컬럼(JSONB)에 그대로 저장되는 모양."""

        payload: dict[str, Any] = {
            "section_sentence_ranges": {k: list(v) for k, v in self.section_sentence_ranges.items()},
            "max_evidence_ids_per_sentence": self.max_evidence_ids_per_sentence,
        }
        if self.total_sentence_range is not None:
            payload["total_sentence_range"] = list(self.total_sentence_range)
        return payload


def code_page_config(page_id: str) -> PageConfig:
    """DB를 보지 않은 코드 기본값 — YAML 정책(2종)·dataclass 컨텍스트(7종)·위 상수."""

    if page_id in ("indicator_market", "indicator_supply"):
        policy = load_page_policy(page_id)  # type: ignore[arg-type]
        name, definition = policy.name, policy.definition
        constraints, version = policy.analysis_constraints, policy.policy_version
    elif page_id in ADDITIONAL_PAGE_CONTEXTS:
        ctx = ADDITIONAL_PAGE_CONTEXTS[page_id]
        name, definition, constraints, version = ctx.name, ctx.definition, ctx.analysis_constraints, ctx.policy_version
    elif page_id in KOMIR_PAGE_CONTEXTS:
        ctx = KOMIR_PAGE_CONTEXTS[page_id]
        name, definition, constraints, version = ctx.name, ctx.definition, ctx.analysis_constraints, ctx.policy_version
    else:
        raise KeyError(f"unknown summary page_id: {page_id}")
    if page_id == "map_mineral":
        ranges, total = dict(MINERAL_MAP_SECTION_SENTENCE_RANGES), MINERAL_MAP_TOTAL_SENTENCE_RANGE
    else:
        ranges, total = dict(SECTION_SENTENCE_RANGES[page_id]), None
    return PageConfig(
        page_id=page_id,
        name=name,
        definition=definition,
        analysis_constraints=tuple(constraints),
        policy_version=version,
        section_sentence_ranges=ranges,
        total_sentence_range=total,
        max_evidence_ids_per_sentence=MAX_EVIDENCE_IDS_PER_SENTENCE_BY_PAGE.get(page_id, MAX_EVIDENCE_IDS_PER_SENTENCE),
        source={k: "code" for k in ("name", "definition", "analysis_constraints", "policy_version", "section_sentence_ranges", "total_sentence_range", "max_evidence_ids_per_sentence")},
    )


def _parse_range(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lo, hi = value
    if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
        return None
    if lo < 1 or hi < lo:
        return None
    return (lo, hi)


def _parse_output_contract(page_id: str, raw: Any, base: PageConfig) -> tuple[dict[str, tuple[int, int]] | None, tuple[int, int] | None, int | None]:
    """DB `output_contract` JSON을 검증해 (섹션범위, 총범위, 문장당 근거수)로.
    형식이 틀린 항목은 None(=코드 기본값)으로 두고 경고만 남긴다 — 운영 중
    DB 값 하나가 틀렸다고 보고서 생성이 멈추면 안 된다."""

    log = logging.getLogger(__name__)
    if not isinstance(raw, dict):
        log.warning("%s: output_contract가 객체가 아니라 무시한다: %r", page_id, raw)
        return None, None, None
    ranges: dict[str, tuple[int, int]] | None = None
    raw_ranges = raw.get("section_sentence_ranges")
    if raw_ranges is not None:
        parsed = {section: _parse_range(raw_ranges.get(section)) for section in _SECTIONS} if isinstance(raw_ranges, dict) else {}
        if all(parsed.get(section) is not None for section in _SECTIONS):
            ranges = {section: parsed[section] for section in _SECTIONS}  # type: ignore[misc]
        else:
            log.warning("%s: output_contract.section_sentence_ranges 형식 오류 — 코드 기본값 사용: %r", page_id, raw_ranges)
    total: tuple[int, int] | None = None
    if raw.get("total_sentence_range") is not None:
        total = _parse_range(raw.get("total_sentence_range"))
        if total is None:
            log.warning("%s: output_contract.total_sentence_range 형식 오류 — 코드 기본값 사용", page_id)
    max_ids: int | None = None
    raw_max = raw.get("max_evidence_ids_per_sentence")
    if raw_max is not None:
        if isinstance(raw_max, int) and not isinstance(raw_max, bool) and 1 <= raw_max <= _EVIDENCE_IDS_HARD_CAP:
            max_ids = raw_max  # `SummarySentence.evidence_ids` max_length(5)가 절대 상한
        else:
            log.warning("%s: output_contract.max_evidence_ids_per_sentence는 1~%d이어야 한다 — 코드 기본값 사용", page_id, _EVIDENCE_IDS_HARD_CAP)
    return ranges, total, max_ids


def resolve_page_config(page_id: str) -> PageConfig:
    """코드 기본값 위에 DB 행(`prompt_store.get_page_row`)의 NULL 아닌 컬럼을 덮는다."""

    base = code_page_config(page_id)
    row = prompt_store.get_page_row(page_id)
    if row is None:
        return base
    source = dict(base.source)
    name, definition, constraints, version = base.name, base.definition, base.analysis_constraints, base.policy_version
    # 공백만 있는 값은 "없음"으로(Pass 3 R3-L3: ' '가 그대로 서술문에 들어가 "니켈  는"이 됐다).
    if row.page_name and row.page_name.strip():
        name, source["name"] = row.page_name.strip(), "db"
    if row.page_definition and row.page_definition.strip():
        definition, source["definition"] = row.page_definition.strip(), "db"
    if row.analysis_constraints is not None:
        if isinstance(row.analysis_constraints, list) and all(isinstance(item, str) for item in row.analysis_constraints):
            constraints, source["analysis_constraints"] = tuple(row.analysis_constraints), "db"
        else:
            logging.getLogger(__name__).warning("%s: analysis_constraints는 문자열 배열이어야 한다 — 코드 기본값 사용", page_id)
    if row.policy_version and row.policy_version.strip():
        version, source["policy_version"] = row.policy_version.strip(), "db"
    ranges, total, max_ids = base.section_sentence_ranges, base.total_sentence_range, base.max_evidence_ids_per_sentence
    if row.output_contract is not None:
        db_ranges, db_total, db_max = _parse_output_contract(page_id, row.output_contract, base)
        if db_ranges is not None:
            ranges, source["section_sentence_ranges"] = db_ranges, "db"
        if db_total is not None:
            total, source["total_sentence_range"] = db_total, "db"
        if db_max is not None:
            max_ids, source["max_evidence_ids_per_sentence"] = db_max, "db"
    return PageConfig(
        page_id=page_id,
        name=name,
        definition=definition,
        analysis_constraints=constraints,
        policy_version=version,
        section_sentence_ranges=ranges,
        total_sentence_range=total,
        max_evidence_ids_per_sentence=max_ids,
        source=source,
    )


def effective_page_context(page_id: str) -> SummaryPageContext:
    """`summary.py`가 응답의 policy_version/page_definition/notices에 쓰는 컨텍스트."""

    return resolve_page_config(page_id).as_context()


def apply_page_config(policy: PagePolicy) -> PagePolicy:
    """YAML 등급 정책(indicator_market/supply)에 DB 오버레이를 입힌다 — 등급 밴드
    (grade_rules)는 판정 로직이라 DB화 대상이 아니고, 이름·정의·제약·버전만 덮는다."""

    cfg = resolve_page_config(policy.page_id)
    return policy.model_copy(
        update={
            "name": cfg.name,
            "definition": cfg.definition,
            "analysis_constraints": list(cfg.analysis_constraints),
            "policy_version": cfg.policy_version,
        }
    )


def summary_instructions(page_id: str) -> str:
    """Select narrative instructions appropriate for a summary page.

    DB(`cfg_prompt`) 캐시에 `prompt_key`가 있으면 그 값을, 없으면 `PROMPTS`의
    하드코드 상수를 쓴다 — `prompt_key`는 공통 서두가 "summary_common", 페이지별
    지시문은 `page_id` 그대로다."""

    common = prompt_store.get_prompt("summary_common", default=PROMPTS["summary_common"])
    page_text = prompt_store.get_prompt(page_id, default=PROMPTS[page_id])
    return common + page_text


def build_summary_payload(
    *,
    response: AnalysisSummaryResponse,
    policy: PagePolicy | SummaryPageContext,
    allowed_evidence: list[dict[str, str]],
    previous_validation_error: str | None = None,
) -> dict[str, Any]:
    """Build an evidence-bounded payload for summary refinement.

    `policy` 인자는 호출부 호환용으로 남겼다 — 페이지 정책·출력 계약은 2026-08-27
    부터 `resolve_page_config()`(코드 기본값 + DB 오버레이)에서 가져온다."""

    cfg = resolve_page_config(response.page_id)
    if response.page_id == "map_mineral":
        required_ids = [
            item["evidence_id"]
            for item in allowed_evidence
            if item.get("required") is True
        ]
        output_contract: dict[str, Any] = {
            "mode": "select_and_synthesize",
            "required_evidence_ids": required_ids,
            "optional_evidence_ids": [
                item["evidence_id"]
                for item in allowed_evidence
                if item.get("required") is not True
            ],
            "max_evidence_ids_per_sentence": cfg.max_evidence_ids_per_sentence,
            "section_sentence_ranges": {
                section: list(bounds) for section, bounds in cfg.section_sentence_ranges.items()
            },
            "total_sentence_range": list(cfg.total_sentence_range or MINERAL_MAP_TOTAL_SENTENCE_RANGE),
        }
    else:
        output_contract = {
            "mode": "synthesize_all",
            "required_evidence_ids": [
                item["evidence_id"] for item in allowed_evidence
            ],
            "max_evidence_ids_per_sentence": cfg.max_evidence_ids_per_sentence,
            "section_sentence_ranges": {
                section: list(bounds) for section, bounds in cfg.section_sentence_ranges.items()
            },
            "require_combined_evidence_sentence": True,
        }
    payload: dict[str, Any] = {
        "page_policy": {
            "page_id": cfg.page_id,
            "name": cfg.name,
            "definition": cfg.definition,
            "analysis_constraints": list(cfg.analysis_constraints),
            "policy_version": cfg.policy_version,
        },
        "analysis_scope": response.analysis_scope,
        "mineral": response.mineral.model_dump(mode="json"),
        "applied_filters": response.applied_filters,
        "data_quality": response.data_quality.model_dump(mode="json"),
        # 2026-08-27(SC-006): 프롬프트가 참조하는 패턴(예: price의 near_period_high/
        # low)을 LLM이 실제로 볼 수 있게 code·label만 싣는다 — `evidence` 문자열은
        # 숫자를 담을 수 있어, 근거 문장에 없는 숫자를 LLM이 베끼면 검증기에
        # 걸리므로 일부러 뺀다.
        "detected_patterns": [
            {"code": pattern.code, "label": pattern.label} for pattern in response.detected_patterns
        ],
        "output_contract": output_contract,
        "allowed_evidence": allowed_evidence,
    }
    if previous_validation_error:
        payload["previous_validation_error"] = previous_validation_error
    return payload
