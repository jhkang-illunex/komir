# 데이터 산출물 레지스트리 (재활용·재현 가이드)

> 원칙(2026-07-08 확립): 파이프라인 실행 결과물은 삭제하지 않고 보존하며, 각 산출물 디렉토리에
> `META.md`(생성 과정·입력·재현 방법)를 함께 남긴다. 휘발성 위치(/tmp)의 검증 산출물은
> `data_archive/`로 이관해 영구 보존한다. 이 문서는 그 중앙 색인이다.
> 코드 기준: git base `96eb79e` + 미커밋 수정분(커밋 전까지는 WORKLOG 날짜 항목이 코드 이력의 정본).

## 운영 산출물 (파이프라인 정본)

| 위치 | 내용 | 생성 | 재현 |
|---|---|---|---|
| `warehouse/minerals.duckdb` | 공유 warehouse 정본(fact_*·mart_*·geo_index 2,087·geo_event 6,510 포함) | 2026-07-08 geo publish + weekly_mart 재빌드 | `GEO_DATA=./geo_data_2016plus_run python -m geo publish --db warehouse/minerals.duckdb` → `MSR_DB=... python -m msr.features.weekly_mart` |
| `warehouse/minerals_test.duckdb` | 위 반영 전 검증 사본(2026-07-08). 정본이 root 소유였던 동안의 조인 검증에 사용 | 〃 | 폐기 가능(정본 검증 완료) — 단 사용자 확인 후 |
| `geo_data_2016plus_run/` | 2016+ 전체 코퍼스(2,812건) ingest→extract 결과. manifest·이벤트 6,510건·pdf_extract_method·OCR캐시·실행로그(run*.log) | 2026-07-07~08, §9·§10 | META.md 참고 |
| `geo_data/` | **프로덕션 단일 스토어**(2026-07-12 확정): 검증 GKG 180.9만+문서 6,510 = 1,815,034건 + 지수 3,382행 + 확률 2,745행 | 2026-07-08~12 | META.md 참고 |
| NAS `광해공단/bulk/gdelt/` | GDELT GKG 원본 zip 361,407개(2016~2026) + 다운로드/파싱/검증 로그(_logs/) | 2026-07-06~08 | `python -m geo.collectors.gkg_bulk_download` (5워커, 총 ~26h) |
| NAS `광해공단/collect_out/` (예정) | 독립 수집기(`collector/` 도커, 별도 서버) 산출 — inbox 텍스트(gnews/gdelt/us_trade/cn_trade)+GKG 증분 zip. 분석기와 파일 계약으로만 연결 | 2026-07-12 구축 | `docker compose up -d` (collector/README.md) |

## 검증·분석 아카이브 (`data_archive/`)

| 위치 | 내용 | 근거 문서 |
|---|---|---|
| `data_archive/validation_runs/geo_ingest_check_260707/` | 10개 대표샘플 재실행 결과(manifest·이벤트 14건·추출텍스트 tgz) — classify/rule 버그 수정 검증에 사용 | 데이터수집현황 §7 |
| `data_archive/validation_runs/geo_pipeline_v2_check/` | opendataloader+OCR+LLM 파이프라인 v2 검증(10샘플, 이벤트 29건) | 〃 §9 도입부 |
| `data_archive/analysis/rule_vs_llm_260707/` | 룰기반 vs LLM(gemma) 추출 비교 원자료 pkl 2종 | 〃 §8 |
| `data_archive/analysis/chaksu_ocr_260708/` | 착수보고 39p OCR 전문(원본 PDF는 폰트 매핑 파손으로 텍스트 추출 불가) | mineral_risk_model_v1.md |

## 관련 문서
- 작업 이력: `docs/WORKLOG.md` (날짜별 변경·버그·결정)
- 데이터 수집 현황·실측: `documents/claude_output/지정학위기지수_데이터수집현황_260707.md`
- 모델 설계 정본: `documents/claude_output/mineral_risk_model_v1.md`
- **발주처 협의 안건서(워드)**: `documents/claude_output/발주처협의안건_4건_260716.docx`
  — 에피소드 라벨 협조·미탐:오탐 비용비 합의·CU 해석 방침 승인·품목 예측 수요 확인.
  v1 §12 기존 8건과 별개 추가 안건임을 명시.
- **광종별 HS코드 연계표(워드)**: `documents/claude_output/광종별_HS코드_연계표_260713.docx`
  — core 161코드(CU 88/NI 36/CO 15/LI 13/REE 9)를 HS 호(4단위) 품명 그룹으로 정리.
  정본은 `mineral_supply_risk/data/raw/hs_commodity_map.csv`(542행), 문서는 그 뷰.
- **발주 보고용 요약본(워드, 구성도 포함)**: `documents/claude_output/핵심광물_시스템구성_요약본_260713.docx`
  — 5모듈·구성도(수집서버 외부망/분석서버 폐쇄망)·수집기 배치·반입 절차·운영 요약. 구성도 원본
  `documents/claude_output/시스템구성도_260713.png`(matplotlib 생성, 스크립트는 세션 스크래치)
- **발주 보고용 확정본(워드)**: `documents/claude_output/핵심광물_시스템_확정아키텍처_모델링정리_v1_260713.docx`
  — 5모듈 아키텍처·데이터 흐름·지표/모델링·전통 ML 채택 근거. 생성 스크립트는 세션 스크래치
  (숫자 출처: outputs/model_opt/report.md, outputs/forecast_unit/forecast_latest.csv, WORKLOG 2026-07-12~13)
