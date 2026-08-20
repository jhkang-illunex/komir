# META — R10 재현성 검토(ph_psa·fgap_ni) 실행 로그

- 일시: 2026-08-04 (완료 19:2x)
- 실행: `cd <워크트리>/mineral_supply_risk && MSR_DB=/home/nuri/dev/git/ws/mine_ws/komir/warehouse/minerals.duckdb python3 -m scripts.r10_repro_check_phpsa_fgapni`
- 스크립트: `mineral_supply_risk/scripts/r10_repro_check_phpsa_fgapni.py`
  (작성 당시 워크트리 `.claude/worktrees/orktree`에만 존재)
- 산출 리포트: `mineral_supply_risk/outputs/model_opt/r10_repro_check_260804.md`
  (결론 절 포함 — 워크트리)
- DB 상태(직접 쿼리 실측): fact_price 종점 2026-07-06·6,867행 /
  mart_weekly_diagnosis 종점 2026-07-06 / 절단 기준(2026-06-08) 초과 NI 행 4행
- 결론 요약: 결정론 재현·시드 강건성 통과. 절단 대조에서 "가격 5주 갱신 효과"
  서사 정정(절단해도 두 후보 채택 유지 — 경계선 신호+08-01 cron 원천 갱신 결합).
  fgap_ni는 CI 하한 +0.004~0.005 경계선 유의.
- 관련: docs/WORKLOG.md 2026-08-04 ㊾ 항목, 메모리
  `r10_260804_price_refresh_interrupted`
