# mnrl_report — 통합보고서 주간 생성 파이프라인(규칙 엔진 + 생성형 엔진)

`public.ai_rpt_overall`(전체)·`public.ai_rpt_mnrl`(광종별)의 텍스트 섹션을 매주
채운다. 2026-09-15 신설. 양식·컬럼 정의는
`documents/산출물/2026-W38_0914-0920/통합보고서_템플릿_{전체,광종별}_260915.md`와
`통합보고서_테이블초안_ai_rpt_{overall,mnrl}_260915.md`가 정본이다.

## 구조 — 파이프라인과 엔진을 분리한다

`run.py`는 **읽고·엔진을 부르고·쓰고·기록만** 하는 파이프라인이다. 문장을 만드는 것은
`engines/`의 두 엔진이고, 각 엔진은 자기 **버전(`YYMMDD-sha8`)** 을 갖는다.

```
원장(public ko_*/ai_*) ──sources.py──▶ facts ──▶ RuleEngine.generate ──▶ RULE 컬럼 ─┐
                                                       │ (근거 = RULE 문장·수치 + 뉴스)        ├─ writer.upsert ─▶ ai_rpt_*
                                           (옵션 --llm) GenEngine.generate ──▶ LLM 컬럼 ─┘   rule_ver / llm_model_ver
                                                                                                  = 엔진 버전
        registry.register(engine)  ─▶ ai_rpt_engine_ver (엔진·버전·파일목록·모델명)
        registry.log_run(...)      ─▶ ai_rpt_gen_run    (행마다 엔진·버전·채움/폐기 컬럼·사유·근거 파일)
                                                                          검수 화면(사람) DRAFT → REVIEWED → DONE
```

| 엔진 | 파일 | 버전 해시 입력 | 만드는 컬럼 |
|---|---|---|---|
| `RuleEngine` (engine_cd=`rule`, RULE) | `engines/rule_engine.py` → `rules/{fmt,mnrl,overall}.py` | rules 3종 + `policy.py` + `config.py` 내용 | 정책 RULE 컬럼(결정론, 동일 입력→동일 문장) |
| `GenEngine` (engine_cd=`gen`, GEN) | `engines/gen_engine.py` + `engines/prompts/ai_rpt_{mnrl,overall}.md` | 엔진 소스 + 프롬프트 2종 + `LLM_PROVIDER:LLM_MODEL` | 정책 LLM 컬럼(원인·해석·정책 제언) |

버전 = `YYMMDD-sha8`: sha8은 위 파일 내용을 정렬해 이어붙인 sha256 앞 8자리(+모델명),
YYMMDD는 그 파일들의 최종 변경일(커밋된 깨끗한 파일은 git 커밋일, 미커밋 파일은 mtime).
규칙 문구 한 줄, 프롬프트 한 줄, 모델명 하나만 바뀌어도
버전이 바뀌고 `ai_rpt_engine_ver`에 새 행이 생기며, 그 뒤 만든 보고서 행은 새 버전이
`rule_ver`/`llm_model_ver`에 찍힌다(모델명은 `ai_rpt_engine_ver.model_nm`으로 역참조).
"이 문장은 어느 규칙/프롬프트/모델이 만들었나"를 행 단위로 추적하기 위한 장치다.

### 생성형 엔진(GenEngine)이 지키는 것
- 근거는 **규칙 엔진 결과(RULE 문장 + 수치 evidence)와 뉴스 제목**뿐. 원장 JSON은 주지 않는다.
- 컬럼별 지시문은 `engines/prompts/<table>.md`의 `## <컬럼>` 절(정책 LLM 컬럼과 1:1, 테스트가
  검사). 헤더에 `[needs:news]`가 붙은 컬럼(원인·사건 서술 — smry_cause·diag_key·price_bg·
  judge_basis·risk1/3 등)은 뉴스 근거가 없으면 **호출 자체를 생략**하고 `no_news_evidence`로
  폐기한다 — 수치만 보고 원인을 짓지 못하게. 현재 뉴스 원천이 미연결이라 이 컬럼들은 전부 NULL.
- 출력 검증(`validate`) 실패 시 폐기(NULL, 사유는 `ai_rpt_gen_run.dropped_json`): 빈 출력·
  `(없음)` 포함, 근거 밖 숫자(연도·월·주차·개수 표기 제외), 근거와 반대 방향어(근거 "4.61% 상승"
  → 출력 "4.61% 하락"), "정보가 없습니다"류 메타 문장, 비어 있는 자리표시자(`[원인 ]`·"에서 가
  주요"·"정보는 ."), 단정 금지어, 길이 초과.
- 공용 LLM 클라이언트는 `json_mode=False`로 쓴다(켜 두면 `{"컬럼": "…"}` 껍데기가 그대로
  저장되는 것을 실측). 코드펜스·JSON 껍데기는 `unwrap`이 벗긴다.
- vLLM(temperature 0)이라도 호출마다 문장이 흔들린다(2026-09-13 실측). 그래서 근거·버전·폐기
  사유를 반드시 로그에 남기고, 채택 여부는 검수(사람)가 정한다.

| 정책 | 누가 쓰나 | 덮어쓰기 규칙 |
|---|---|---|
| RULE | RuleEngine(결정론, 동일 입력→동일 문장) | 매 실행 재계산. 행이 DRAFT일 때만(REVIEWED/DONE은 `--force` 없이는 불변) |
| LLM | GenEngine(기본 비활성 `MNRL_REPORT_LLM_ENABLED=0`, `--llm`) | 실행했을 때만, DRAFT일 때만. 검증 실패 컬럼은 폐기(NULL) |
| MANUAL | 담당자 | 엔진은 절대 덮어쓰지 않음. 행 최초 INSERT 때 `resources/fixed_texts.json` 시드만 |
| META | 파이프라인(rule_ver·llm_model_ver=엔진 버전, llm_refined_yn)/검수 화면(gen_stts_cd·reviewer_*) | — |

정책표는 `policy.py`가 코드로 고정하며 테이블 COMMENT의 [RULE]/[LLM]/[MANUAL]
태그와 1:1이다(테스트가 45/42 컬럼 전수 대응을 검사).

핵심 원칙
- **지어내지 않는다**: 원천이 없으면 문장 컬럼은 NULL. 광종에 원천이 하나도 없으면
  행 자체를 만들지 않는다(`skipped(no source)`).
- **더미 차단**: `ai_dev_dummy_load`에 잡힌 광종×테이블, `model_ver/src_nm=DEV_DUMMY`
  행은 원천으로 쓰지 않는다(`ai_mnrl_diag`·`ai_dash_diag`·GSCPI 등은 현재 전부 더미라
  진단·지정학 문장은 실값 적재 전까지 NULL).
- **근거 스냅샷**: 실행마다 `data_lake/mnrl_report/facts_{base_ymd}.json`에 facts를
  남긴다(감사·LLM 검증 재현용, git 미추적).
- **미확정 산식은 계산하지 않는다**: 가격이격률·가격신호(B6)는 발주처와 산식·임계 확정
  전까지 NULL.

## 실행

```bash
cd inhouse
python -m unittest mnrl_report/tests/test_rules.py mnrl_report/tests/test_engines.py  # DB·LLM 없이 규칙·엔진·버전 검사
python -m mnrl_report.run --base-ymd 20260615 --dry-run     # 원장 조회·문장 조립만
python -m mnrl_report.run --base-ymd 20260615               # DRAFT 행 upsert
python -m mnrl_report.run                                   # 가장 최근 월요일 주차
python -m mnrl_report.run --minerals MNRL0018 --scope mnrl  # 광종·범위 지정(기본은 진단 대상 5광종, all=READY 전부)
python -m mnrl_report.run --llm                             # 생성형 엔진 포함
# 호스트에서 --llm: common/config가 저장소 루트 .env(컨테이너용 host.docker.internal)를 읽으므로
LLM_BASE_URL=http://localhost:52302/v1 python -m mnrl_report.run --base-ymd 20260615 --llm
```

주간 스케줄(둘 중 하나)
- 컨테이너 cron(권장, ingest와 동일): `docker build -f mnrl_report/Containerfile -t komir-mnrl-report:<tag> .`
  → `entrypoint.sh`가 `MNRL_REPORT_SCHEDULE_CRON`(기본 `0 7 * * TUE`, KST)로
  `cron_mnrl_report_weekly.sh` 실행(supercronic, flock).
- 상주 프로세스: `python -m mnrl_report.scheduler`(APScheduler, report_gen과 동일 패턴).

대상 광종은 수급위기 진단 5광종으로 고정이다(사용자 확정 2026-09-15): 동 MNRL0008·니켈
MNRL0002·코발트 MNRL0003·리튬 MNRL0001·희토류=네오디뮴 MNRL1001(`config.TARGET_MINERALS`,
희토류는 대표원소 네오디뮴으로 사용자 확정). 원천이 없는 광종은 행을 만들지 않으므로 실데이터
기준(2026-09-15) 광종별 행은 동·니켈 2행이다 — 코발트·리튬·네오디뮴은 주간가격·관세청·USGS
모두 더미(`ai_dev_dummy_load`)뿐이라 skipped(no source).

환경변수(`inhouse/.env` + 선택): `PG_DSN`(필수), `MNRL_REPORT_SCHEDULE_CRON`,
`MNRL_REPORT_LLM_ENABLED`, `MNRL_REPORT_HHI_HIGH`(기본 2500), `MNRL_REPORT_OVERALL_HIGH`
(기본 60), `MNRL_REPORT_CUSTOMS_WEIGHT_KG`(기본 1), `MNRL_REPORT_MINERALS`(기본 5광종, all=전부), `MNRL_REPORT_FACTS_DIR`.

## 원천 → 컬럼 매핑(현재 실데이터 범위)

| facts | 원천 | 실데이터 광종(2026-09-15) | 채우는 컬럼 |
|---|---|---|---|
| price | `ko_wkly_mnrl_prc`(주간 기준가·전주비·4주전·52주전) | 동·니켈·알루미늄·주석·연·아연 | price_wow_pct, smry_quant_txt(가격 문장), price_foot_txt, overall.risk2_quant_txt(가격) |
| diag | `ai_mnrl_diag`(비더미만) | 없음(전부 DEV_DUMMY) | grade_*, score*, grade_streak_wk, smry_quant_txt(지수 문장), diag_result_txt, overall A3/A4/A5 |
| customs | `ko_cstm_cmmrc`×`ai_hs_mnrl_map` | 텅스텐 | import_* 5컬럼, import_struct_txt, risk_quant_txt(수입), overall.risk4_quant_txt |
| production/reserve | `ko_rsrc_prdctn_quty`/`ko_rsrc_burudg_quty`(SU=세계합계, OT=기타) | 텅스텐 | production_txt, reserve_txt, risk_quant_txt(생산), overall.risk2_quant_txt(USGS) |
| overall / gscpi | `ai_dash_diag` / `ai_macro_indc(GSCPI)` (비더미만) | 없음 | overall_score/wow/level, gscpi_val |

`public` 쓰기는 이 모듈의 `db.WRITABLE_TABLES`(ai_rpt_overall·ai_rpt_mnrl + 이 모듈 소유
보조 테이블 ai_rpt_engine_ver·ai_rpt_gen_run)로만 제한한다(`common/db.py`의 public 금지
원칙에 대한 사용자 승인 예외, 2026-09-15). 보조 테이블 2종은 `registry.ensure_tables()`가
없을 때 만든다(IF NOT EXISTS).

## 엔진 버전·실행 이력 조회

```sql
SELECT engine_cd, ver, engine_type, model_nm, src_files, frst_reg_dt FROM public.ai_rpt_engine_ver ORDER BY frst_reg_dt;
SELECT base_ymd, tbl_nm, row_key, engine_cd, engine_ver, write_stts, cols_filled, cols_dropped, dropped_json
  FROM public.ai_rpt_gen_run WHERE base_ymd='20260615' ORDER BY run_sn DESC;
-- 어떤 보고서 행이 어느 버전으로 만들어졌나
SELECT mnrknd_unq_cd, base_ymd, rule_ver, llm_model_ver, llm_refined_yn, gen_stts_cd FROM public.ai_rpt_mnrl;
```

## 새 섹션·광종·원천을 추가할 때
1. `policy.py`에 컬럼과 정책 추가(테이블 COMMENT 태그와 맞출 것).
2. `sources.py`에 조회 함수 추가 — 더미 차단·단위 명시.
3. RULE 컬럼이면 `rules/`에 문장 조립 추가(양식 템플릿 문구 그대로, 원천 없으면 None),
   LLM 컬럼이면 `engines/prompts/<table>.md`에 `## <컬럼> [needs:news]` 절 추가.
4. `tests/test_rules.py`(고정 facts로 기대 문장)·`tests/test_engines.py`(가짜 LLM으로 검증 규칙)에
   테스트 추가. 규칙·프롬프트를 고치면 엔진 버전이 저절로 바뀐다 — 손으로 올리는 버전 상수는 없다.
5. 뉴스 원천이 연결되면 `run.py`의 ctx `"news"`에 제목 목록을 넣는다 — `[needs:news]` 컬럼이
   그때부터 생성된다.
