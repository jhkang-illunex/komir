# `public.ko_*`(KOMIS 원천 테이블) 스키마 매핑 — 1차 추론 (2026-08-31)

챗봇 MCP에 postgres 검색 도구를 추가하기 전, "스키마 정의서가 없다"는 요청에 따라
`public` 스키마(komis_demo DB, **타 팀 소유 — 읽기 전용**)를 직접 조회해 만든
1차 매핑이다. 문서·원본 코드 예시를 그대로 믿지 않고 전부 실측했다(쿼리는 각
표 아래 각주로 남김). **이번 라운드는 조사만 했고, MCP 도구 코드는 아직 만들지
않았다** — §5(다음 단계)에서 설계 시 고려사항만 정리한다.

## 0. 요약 — 가장 먼저 알아야 할 것

- `public` 스키마엔 **37개 테이블**이 있다: `ko_*` 9개(이번 조사 대상, KOMIS
  원천 데이터) + `ai_*` 28개(§4 참고, 이번엔 조사 범위 밖).
- `ko_*` 9개는 사실 **완전히 새로 조사할 필요가 없었다** —
  `inhouse/services/shared/komis_raw.py`(report_gen이 이미 쓰고 있는 읽기전용
  접근계층)에 이미 9개 테이블 전부의 컬럼명·의미가 `_PAGE_DATASETS`로 정의돼
  있다(2026-08-11, komis-report-generator-main에서 이식). 이 문서는 그 정의를
  기준점 삼아 **실제 데이터로 재검증**하고, 표 형태로 재정리하고, report_gen이
  안 쓰는 하우스키핑 컬럼까지 채운 것이다.
- **⚠ 가장 중요한 발견(§1)**: 우리 발주 대상 5광종(CU·NI·CO·LI·REE)의 `ko_*`
  데이터는 **거의 전부 개발용 더미(DEV_DUMMY)**다. 실제 KOMIS 원본 표본은
  텅스텐(MNRL0018, 발주 대상 아님) 하나뿐이다. 챗봇 MCP가 이 테이블을 그대로
  조회해 사용자에게 보여주면 **가짜 숫자를 실데이터인 것처럼 노출**하게 된다 —
  도구를 만들기 전에 반드시 확인해야 하는 사실이라 최상단에 둔다.

## 1. ⚠ 데이터 오염 실태 — DEV_DUMMY vs 실샘플

`ai_mnrl_mst`(광종 마스터, 28행)에 각 광종 코드의 출처가 `ko_data_src_cd`로
명시돼 있다:

| 광종코드 | 광종명 | `ko_data_src_cd` | 비고(마스터 `rm` 컬럼 원문) |
|---|---|---|---|
| `MNRL0001` | 리튬(LI) | `DEV_DUMMY` | "[DEV_DUMMY] 개발용. 공단 전달 실샘플 아님. load=DEV_DUMMY_20260819" |
| `MNRL0002` | 니켈(NI) | `DEV_DUMMY` | 위와 동일 |
| `MNRL0003` | 코발트(CO) | `DEV_DUMMY` | 위와 동일 |
| `MNRL0008` | 동(CU) | `DEV_DUMMY` | 위와 동일 |
| `MNRL1001` | 네오디뮴(REE 대표원소) | `DEV_DUMMY` | 위와 동일 |
| `MNRL0018` | 텅스텐(발주 대상 아님) | `KOMIS_SAMPLE` | "공단 KO_* 실샘플(텅스텐)" |

실제 테이블에서도 이 표시가 그대로 확인된다 — 더미 여부를 판단할 때 마스터
테이블 하나만 믿지 말고 아래처럼 직접 확인할 수 있다:
- `ko_rsrc_burudg_quty`/`ko_rsrc_prdctn_quty`의 `se_cd` 컬럼이 우리 5광종
  행에선 전부 `'DEV'`(텅스텐 등 기존 데이터는 `'-'`).
- `ko_cstm_cmmrc.item_nm`에 문자 그대로 `"[DEV_DUMMY] 동 품목A"`처럼 더미
  태그가 박혀 있다. `hs_cd`도 `9900000801`류로 실제 HS 코드 체계와 다르다.

**실측 커버리지 대조**(행수·기간, 쿼리는 §2 각주):

| 테이블 | 텅스텐(실샘플) | CU/NI/CO/LI/REE(더미) |
|---|---|---|
| `ko_mnrl_prc`(가격) | 12,549행, 1997-01~2025-02 | 각 60~66행, 2026-06~2026-08(약 2개월) |
| `ko_cstm_cmmrc`(국내 관세청 교역) | 20,736행, 2014-01~2024-12 | 각 50~100행, 2025-08~2026-08 |
| `ko_un_cmmrc`(세계 교역) | 포함(HS 8101* 계열) | **HS코드 자체가 없음 — 0건**(아래 참고) |
| `ko_rsrc_burudg_quty`/`ko_rsrc_prdctn_quty`(매장량/생산량) | 포함(19개 광종 중 1) | 2019~2026, `se_cd='DEV'` |
| `ko_mnrl_prc_predc`(가격예측)·`ko_mrkt_prspect_idct`(시장전망)·`ko_spdm_stbt_indx`(수급안정) | **텅스텐만 존재**(각 76·170·98행) | **0행 — 아예 없음** |

즉 가격예측·시장전망지표·수급안정지수·세계교역 **4개 테이블**은 5광종 데이터가
**행 자체가 없다**(`ko_un_cmmrc`는 `ai_hs_mnrl_map`의 5광종 HS코드 10건 전부를
직접 조인해 실측 확인 — 12종 실제 HS코드 중 일치 0건). 가격·국내교역·매장량·
생산량 4개 테이블은 있긴 하지만 전부 더미. **결론: 지금 이 시점에 `ko_*`에서
5광종 관련 응답을 만들면 100% 더미이거나 0건이다** — MCP 도구를 실제로
배선하기 전에 발주처가 실데이터를 적재했는지 재확인 필수(§5).

**더미 판별 규칙 하나 더(공통 컷오프)**: 실샘플(텅스텐) 관측 데이터의 최신
일자는 테이블 불문 공통적으로 **2024-11~2025-02 근방**에서 멈춰 있다(가격
2025-02-17, 시장전망 2025-02, 수급안정 2025-02, 국내교역 2024-12, 세계교역
2024-11 — 이게 표본 스냅샷 시점으로 보인다). 그러니 **관측일자(`crtr_ymd`)가
2025-02 이후인 행은 실샘플이 아닐 가능성이 높다**(`ko_mnrl_prc_predc`처럼
미래 예측 목표시점을 담는 컬럼은 예외 — 그건 원래 미래 날짜가 정상이다).
위의 `se_cd='DEV'`·`item_nm`의 `[DEV_DUMMY]` 태그와 함께 세 번째 판별
단서로 쓸 수 있다.

## 2. 마스터/매핑 테이블 3종 — `ko_*` 조회 전에 항상 거쳐야 함

`ko_*` 테이블 대부분이 광종을 **직접 코드로 갖지 않고**(가격·교역 테이블)
일련번호/HS코드로만 연결돼 있어, 아래 3개 매핑 테이블을 먼저 조회해야
"광종 → 실제 조회조건"으로 변환할 수 있다(`komis_raw.py`가 이미 이 패턴으로
구현돼 있음, 그대로 재사용 가능).

| 테이블 | 역할 | 핵심 컬럼 |
|---|---|---|
| `ai_mnrl_mst`(28행) | 광종 마스터 — 코드·한글명·영문명·데이터출처 | `mnrknd_unq_cd`(예 `MNRL0008`), `mnrl_nm_ko`(예 "동"), `mnrl_nm_en`, `ko_data_src_cd`(`KOMIS_SAMPLE`/`DEV_DUMMY`), `use_yn` |
| `ai_prc_mnrl_map` | 광종 → 가격기준일련번호(`ko_mnrl_prc.mnrl_prc_crtr_sn`) 매핑, 광종 1개당 여러 건 가능 | `mnrknd_unq_cd`, `mnrl_prc_crtr_sn`, `use_yn` |
| `ai_hs_mnrl_map` | 광종 → HS코드(`ko_cstm_cmmrc`/`ko_un_cmmrc.hs_cd`) 매핑, 광종 1개당 여러 건 가능 | `mnrknd_unq_cd`, `hs_cd`, `use_yn` |

⚠ `ai_mnrl_mst`엔 코드 체계가 **두 종류 섞여 있다** — `CU`/`NI`/`CO`/`LI`/`ND`
같은 2~3자 알파코드(`use_yn='N'`, "26년 개발광종(샘플 미적재)")와
`MNRL0008`/`MNRL1001` 같은 숫자코드(`use_yn='Y'`, `ko_*` 테이블이 실제로 쓰는
쪽)가 둘 다 있다. **`ko_*` 조회엔 반드시 `MNRL0xxx`/`MNRL1xxx` 코드를 써야
한다** — 알파코드는 아직 미사용 상태다.

## 3. `ko_*` 9개 테이블 개별 매핑

### 3-1. `ko_mnrl_prc` — 광종별 일별 가격
| 컬럼 | 추정 의미 | 비고 |
|---|---|---|
| `mnrl_prc_crtr_sn` | 가격기준일련번호(광종 아님, `ai_prc_mnrl_map`으로 광종 역참조) | numeric |
| `crtr_ymd` | 기준일자(YYYYMMDD, 8자리) | varchar |
| `lowst_prc`/`hghst_prc`/`cmerc_prc` | 최저가/최고가/실거래가 | numeric |
| `invt` | 재고량 | 대부분 NULL(텅스텐 표본 기준) |
| `status` | 상태('Y'=유효로 추정) | |
| `frst_rgtr_id`/`frst_reg_dt`/`last_mdfr_id`/`last_mdfcn_dt`/`last_del_*` | 등록/수정/삭제 이력(하우스키핑, 조회엔 불필요) | |

실측: 13,731행, `mnrl_prc_crtr_sn` 25종, 기간 1997-01-06~2026-08-25(전체
합산 — 광종별로는 §1 표 참고).

### 3-2. `ko_mnrl_prc_predc` — 광종별 가격 예측
| 컬럼 | 추정 의미 | 비고 |
|---|---|---|
| `mnrl_prc_predc_sn` | 예측 일련번호(PK 성격) | bigint |
| `mnrknd_unq_cd` | 광종코드(직접 보유 — 위 두 매핑표 안 거쳐도 됨) | |
| `crtr_ymd` | 예측 기준일자 | |
| `prd_se_cd` | 예측 시계열 구분(실측 `PE201~PE204` 4종 — 순번상 향후 1~4분기 예측 시점으로 추정, 확정 아님) | |
| `prc_unit_cd` | 가격단위코드 | **실측 전부 NULL** |
| `cmerc_prc` | 실거래가(예측 시점 기준) | **실측 전부 NULL**(예측만 있고 실측은 없는 게 정상 — 미래 시점 행이라) |
| `predc_prc` | 예측가격 | |

실측: 76행, 전부 `MNRL0018`(텅스텐), 5광종 행 **0건**.

### 3-3. `ko_mnrl_snths_indx` — 광물 종합지수
| 컬럼 | 추정 의미 | 비고 |
|---|---|---|
| `indx_se_cd` | 지수구분코드(실측 `HI001`/`HI002`/`HI003` 3종 — 광종코드 체계와 무관, 별도 지수군으로 추정. 구성 의미는 미확인, 발주처 확인 필요) | |
| `crtr_ymd` | 기준일자 | |
| `indx` | 지수값 | |
| `prvdy_cprs` | 전일대비 | |
| `uplmt`/`lwlmt`/`center` | 상한/하한/중심값(밴드 표시용으로 추정) | 실측 샘플에선 전부 NULL |

실측: 10,899행, 기간 2011-01-04~2025-02-18 — §1의 "실샘플 공통 컷오프
2025-02" 규칙과 일치하는 정상적인 실샘플 범위다(더미 행이 안 섞여 있어
최신 날짜가 더 안 늘어난 것뿐, 이 테이블만 유독 정체된 게 아니다). 광종코드
없이 지수 자체가 목적이라 5광종 매핑 불가/불필요일 수 있음(미확인).

### 3-4. `ko_mrkt_prspect_idct` — 광종별 시장전망지표
| 컬럼 | 추정 의미 |
|---|---|
| `mnrknd_unq_cd` | 광종코드 |
| `crtr_ymd` | 기준일자(8자리, day 정밀도) |
| `mrkt_prspect_idct` | 시장전망지표값 |
| `real_prc` | 실제가격(지표와 나란히 비교용으로 추정) |
| `prvmm_cprs` | 전월대비 |

실측: 170행, 전부 `MNRL0018`, 5광종 **0건**.

### 3-5. `ko_spdm_stbt_indx` — 광종별 수급안정지수
| 컬럼 | 추정 의미 |
|---|---|
| `mnrknd_unq_cd` | 광종코드 |
| `crtr_ymd` | 기준연월(**6자리 YYYYMM** — 위 테이블과 정밀도 다름, 주의) |
| `spdm_stbt_indx` | 수급안정지수값 |
| `real_prc`/`prvmm_cprs`/`prc` | 실제가격/전월대비/가격(용도 미확정, 셋 다 가격 계열로 추정) |
| `incm_weig`/`incm_amt` | 수입중량/수입금액 | 실측 샘플 전부 NULL |

실측: 98행, 전부 `MNRL0018`, 5광종 **0건**.

### 3-6. `ko_rsrc_burudg_quty` — 국가별 매장량
| 컬럼 | 추정 의미 |
|---|---|
| `mnrknd_unq_cd` | 광종코드 |
| `crtr_yr` | 기준연도(4자리) |
| `ntn_eng_cd` | 국가코드(영문 2자, ISO 유사 — `CL`칠레·`AU`호주·`CN`중국·`ID`인도네시아 등 실측 확인) |
| `mass_unit_cd` | 중량단위코드(실측 `TON`) |
| `rsrc_invt_cd` | 자원분류코드(실측 `RI001` 또는 5광종 더미행은 `'DEV'`) |
| `burudg_quty`/`burudg_quty_ton` | 매장량(원단위/톤환산) |
| `se_cd` | 구분코드(더미행 `'DEV'`, 기존행 `'-'` — **더미 판별에 가장 쓰기 쉬운 컬럼**) |

실측: 272행, 19개 광종(5광종 포함, §1 참고). 기간 2019~2026.

### 3-7. `ko_rsrc_prdctn_quty` — 국가별 생산량
`ko_rsrc_burudg_quty`와 컬럼 구조 거의 동일(매장량→생산량 컬럼명만
`prdctn_quty`/`prdctn_quty_ton`로 대체, `rsrc_invt_cd` 없음). 실측: 279행,
19개 광종, 2019~2026.

### 3-8. `ko_cstm_cmmrc` — 국내(관세청) 수출입
| 컬럼 | 추정 의미 |
|---|---|
| `hs_cd` | HS코드(10자리) — `ai_hs_mnrl_map`으로 광종 역참조 |
| `crtr_ymd` | 기준일자 |
| `trgt_ntn_cd`/`trgt_ntn` | 대상국코드/대상국명(한글) |
| `incm_weig`/`incm_amt` | 수입중량/수입금액 |
| `exp_weig`/`exp_amt` | 수출중량/수출금액 |
| `item_nm` | 품목명(한글 — 더미행은 `"[DEV_DUMMY] 동 품목A"`류로 태그가 그대로 박혀 있어 판별이 제일 쉬움) |

실측: 22,486행, HS코드 56종·대상국 107개국. 5광종 HS코드는 `9900000801`류의
비정상 코드(실제 HS 체계와 다름 — 더미 확정)이고 기간도 짧다(§1).

### 3-9. `ko_un_cmmrc` — 세계(UN Comtrade) 수출입
| 컬럼 | 추정 의미 |
|---|---|
| `hs_cd` | HS코드(6자리 — 국내표보다 자릿수 적음, UN 표준 6단위로 추정) |
| `crtr_ymd` | 기준일자 |
| `incm_ntn_cd`/`exp_ntn_cd` | 수입국/수출국 코드 |
| `imxprt_se_cd` | 수출입구분(`I`=수입/`O`=수출로 추정, 실측 두 값만 존재) |
| `crtr_ntn_nm`/`trgt_ntn_nm` | 기준국명/대상국명(영문) |
| `weig`/`amt` | 중량/금액 |
| `mnrknd_unq_cd` | **전 25,342행 100% NULL** — 이 컬럼으로 광종 필터링 불가, `ai_hs_mnrl_map`으로 `hs_cd` 경유 필터만 가능(`komis_raw.py`에 이미 이렇게 처리돼 있음) |

실측: 25,342행, HS코드 12종, 기간 2022-01~2024-11. **더미 태그 없음** —
표본이 진짜 UN Comtrade 데이터로 보인다(예: 아이슬란드→미국/일본 HS
820900(공구류) 거래). 다만 5광종 관련 HS코드가 이 12종 안에 있는지는
미확인 — 다음 조사 항목.

## 4. 참고 — `public.ai_*` 28개 테이블(이번 조사 범위 밖)

요청이 `ko_*`로 명확히 한정돼 있어 이번엔 테이블 목록만 확인하고 내용은
안 열어봤다. 이름으로 미루어(추정, 미검증): `ai_mnrl_diag`(광종 진단)·
`ai_dash_diag`/`ai_dash_factor`(대시보드 진단/요인)·`ai_report`·`ai_evid`(근거)·
`ai_news`·`ai_threshold`·`ai_item_card`/`ai_item_grade_hist`·`ai_macro_indc`
(거시지표)·`ai_anal_req`/`ai_anal_rslt`(분석요청/결과)·`ai_user_mst`/
`ai_user_role`·`ai_audit_log`·`ai_ntn_mst`/`ai_ntn_grp`(국가마스터/그룹)
등 — 이름만으로는 출처가 갈리는 두 가설이 있다: (a) KOMIS 사이트 자체의
기존 AI 기능(로그인 후 보이는 수급동향지표 등)이 쓰는 테이블, 또는
(b) **komir 자신의 산출물을 발행하는 대상 스키마**(CLAUDE.md 과업개요 ⑤
"운영 DB 발행" — `ai_item_card`가 0807 발주처 자료의 "AI관리카드" 용어와
겹치고, `ai_mnrl_diag`/`ai_dash_diag`/`ai_evid`의 이름 구조가 komir가 이미
만드는 산출물(경보·근거·요인)과 닮아 있다). 둘 다 미검증 추측이다 — 챗봇
MCP가 여길 조회할 필요가 있다면 별도 라운드로 어느 가설이 맞는지부터
확인하고(마스터 3종처럼 더미/실데이터 오염 여부도 §1과 같은 패턴으로
재확인 필요).

## 5. 다음 단계 — MCP 도구 설계 시 고려사항(코드 미작성, 제안만)

1. **더미 데이터 노출 방지가 최우선**: 도구를 지금 그대로 배선하면 챗봇이
   가짜 CU/NI/CO/LI/REE 가격·교역 수치를 실측인 것처럼 답할 위험이 있다.
   최소한 (a) `se_cd`/`rsrc_invt_cd`가 `'DEV'`인 행 제외, (b) `item_nm`에
   `[DEV_DUMMY]` 포함 행 제외, (c) `ai_mnrl_mst.ko_data_src_cd != 'KOMIS_SAMPLE'`
   인 광종은 조회 결과에 "이 데이터는 개발용 표본이며 KOMIS 실데이터가 아님"
   경고를 강제로 동봉하는 안전장치 중 하나는 반드시 필요.
2. **자유형 SQL 생성 금지 원칙 재사용**: `komis_raw.py`·`structured.py`가 이미
   쓰는 "정적 스펙 + 화이트리스트 리터럴만 조합, LLM이 SQL 문자열을 직접 짓지
   않음" 패턴을 그대로 따를 것 — `public`은 타 팀 소유라 쓰기 사고 리스크는
   없지만(SELECT만), 그래도 원칙은 동일하게 지키는 게 안전.
3. **`komis_raw.KomisRawDataRepository`를 그대로 재사용할지, 챗봇 전용
   레이어를 새로 만들지 결정 필요** — 이미 9개 테이블 전부에 대해 검증된
   구현이 있으므로(`fetch`/`fetch_complete`/`resolve_mineral`/
   `resolve_price_criterion_serials`/`resolve_hs_codes`), 처음부터 새로
   짜기보다 이 클래스를 `services/shared/`에 이미 있으니 rag_chat 쪽 MCP
   툴에서 import해 얇은 어댑터만 추가하는 쪽이 report_gen과의 로직 중복도
   피하고 검증된 코드를 재사용하는 길일 수 있음(다만 report_gen 전용
   가정이 섞여 있는지는 재확인 필요).
3. **`ko_mnrl_snths_indx`의 `HI001~003` 의미, `ko_un_cmmrc`의 5광종 HS코드
   존재 여부, `ai_*` 28개 테이블**은 이번에 확정 못 한 열린 질문 — 실제로
   MCP 도구를 만들기로 결정되면 그 전에 마저 확인 필요.

## 6. 조사 방법(재현용)

전부 `cd inhouse && python3`로 `services.shared.db.read_sql_pg()`(.env의
`PG_DSN` 사용, DSN 값 자체는 출력하지 않음) 통해 SELECT만 실행 — INSERT/
UPDATE/DELETE/DDL 없음. 테이블 목록은
`information_schema.tables`/`information_schema.columns` 조회, 커버리지는
각 테이블 `count(*)`/`min`/`max`/`count(distinct ...)` 집계, 더미 여부는
`ai_mnrl_mst.ko_data_src_cd`·`se_cd`·`item_nm` 실제 값 확인으로 판별했다.
