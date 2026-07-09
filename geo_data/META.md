# META — geo_data (GKG 벌크 이벤트 저장소)
- store/geo_events.parquet: GKG 361,407파일 → 이벤트 2,019,023건(gkg-theme-v4 규칙 파싱, 2026-07-08 8워커)
- LLM 재검증(gkg_verify) 진행 중: 확정분은 store/events_shards/에 샤드 적재(완료 후 compact 필요),
  기각 ID는 NAS _logs/gkg_rejected.txt 누적(완료 후 compact_rejections로 실삭제)
- 상태파일: NAS 광해공단/bulk/gdelt/_logs/{gkg_parsed,gkg_verified,gkg_rejected}.txt — 재개 가능
- 로그: _logs/gkg_parse_worker*.stdout, _logs/gkg_verify_full.log
