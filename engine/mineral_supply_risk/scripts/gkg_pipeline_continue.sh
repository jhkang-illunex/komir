#!/bin/bash
# 2026-07-20 /goal 후속 자동 파이프라인 — 사용자 지시("완료되면 바로바로 진행")에 따라
# 2차 검증 완료 후 별도 확인 없이 순차 실행: 결과반영 → 재발행 → SRS재검증 →
# geo_index/geo_prob 재계산 → 수급진단 모델 재평가.
set -e
cd /home/nuri/dev/git/ws/mine_ws/komir

echo "=== [1/7] 2차 검증(verify2) 프로세스 종료 대기 ==="
while pgrep -f "gkg_relevance_llm_verify2 --concurrency 16" >/dev/null; do
  sleep 30
done
echo "2차 검증 완료 확인"

echo "=== [2/7] 2차 검증 결과 store 반영 ==="
python3 -m geo.gkg_relevance_llm_verify2 --apply

echo "=== [3/7] DB 재발행(events) ==="
python3 -c "
from geo import publish
n = publish.run('warehouse/minerals.duckdb', 'events')
print('발행행수', n)
"

echo "=== [4/7] 최종 SRS 재검증(n=200) ==="
python3 -m mineral_supply_risk.scripts.srs_post_cleanup_check --db warehouse/minerals.duckdb --out-csv /tmp/srs_verify2_final.csv --seed 0.77 --n 200

echo "=== [5/7] geo_index/geo_prob 재계산 ==="
python3 -m geo index
python3 -m geo prob
python3 -m geo publish --db warehouse/minerals.duckdb --what index

echo "=== [6/7] 수급진단 모델 재학습·평가 ==="
cd mineral_supply_risk
MSR_DB=../warehouse/minerals.duckdb python3 -m scripts.diagnosis_retrain_answer
cd ..

echo "=== [7/7] 완료 ==="
