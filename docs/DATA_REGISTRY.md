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
| `geo_data/` | GKG 벌크 파싱 이벤트 저장소(약 2.0M건) + LLM 재검증 진행분 | 2026-07-08~ | META.md 참고 |
| NAS `광해공단/bulk/gdelt/` | GDELT GKG 원본 zip 361,407개(2016~2026) + 다운로드/파싱/검증 로그(_logs/) | 2026-07-06~08 | `python -m geo.collectors.gkg_bulk_download` (5워커, 총 ~26h) |

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
