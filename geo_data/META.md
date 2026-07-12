# META — geo_data (프로덕션 단일 이벤트 스토어, 2026-07-12 확정)
- store/geo_events.parquet: **1,815,034건** = GKG 재검증 통과 1,808,522(LLM 확정, 기각 10.4% 제거)
  + 문서 코퍼스 6,510(geo_data_2016plus_run에서 병합) + 잔여 2. manifest 2,804건 병합.
- store/geo_index.parquet: 3,382행(주간 2,743) — 광종별 scale_k(P90 앵커, 동결) 적용.
- store/geo_prob.parquet: 2,745행 — NB2 강도모델(p_severe_next=P(≥1)·p_burst_next=P(≥P90임계)).
- 재현: GEO_DATA=./geo_data python -m geo index && python -m geo prob
  && python -m geo publish --db warehouse/minerals.duckdb
- 이력: GKG 검증 상태는 NAS bulk/gdelt/_logs/, 병합 전 문서 스토어 원본은 geo_data_2016plus_run/(보존).
