# -*- coding: utf-8 -*-
"""v10.pptx 슬라이드18(baseline)·19(교차비교)·21(생산량버그확인)이 쓰는 세계총계가
report_gen의 2026-09-13 world-total 버그 수정 전 값(지도 국가합계, 과소산정)으로
박제돼 있어, 수정된 코드로 다시 조회해 3개 슬라이드 데이터를 모두 새로 만든다."""
import json
import sys

sys.path.insert(0, "/home/nuri/dev/git/ws/mine_ws/komir/inhouse/report_gen")
from app.analysis.summary import AnalysisSummaryService
from app.analysis.models import AnalysisSummaryRequest

DUMP = "/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis/komis_08_mineral_map.json"
data = json.load(open(DUMP, encoding="utf-8"))
results = data["results"]


def resp(key):
    return next(r for r in results if r["key"] == key)["response"]


svc = AnalysisSummaryService(None, llm=None)


def run(**kwargs):
    req = AnalysisSummaryRequest(request_id="v10-refetch", page_id="map_mineral", **kwargs)
    out = svc.analyze(req)
    return json.loads(out.model_dump_json())


reserves_chart = resp("동|매장량|chart")
reserves_share = resp("동|매장량|table")
production_chart = resp("동|생산량|chart")
production_share = resp("동|생산량|table")
production_snapshot = resp("동|생산량|map")  # secondary(교차비교용, 기존 v10과 동일 소스)

out = {}

# 슬라이드18: baseline(매장량, 2021~2025)
out["map_mineral_baseline_2021_2025"] = run(
    mineral="MNRL0008", mineral_name="동", measure="reserves",
    start_year=2021, end_year=2025,
    komis_response=reserves_chart, komis_share_response=reserves_share,
)

# 슬라이드19: 교차비교(매장량 주, 생산량 보조 스냅샷, 2021~2025)
out["map_mineral_cross_2021_2025"] = run(
    mineral="MNRL0008", mineral_name="동", measure="reserves",
    start_year=2021, end_year=2025,
    komis_response=reserves_chart, komis_share_response=reserves_share,
    komis_snapshot_response=production_snapshot,
)

# 슬라이드21: 생산량 검색(버그 재현·수정 확인용, 2021~2025)
out["map_mineral_production_2021_2025"] = run(
    mineral="MNRL0008", mineral_name="동", measure="production",
    start_year=2021, end_year=2025,
    komis_response=production_chart, komis_share_response=production_share,
)

OUT_PATH = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/v10_map_mineral_2021_2025_worldtotal_fixed.json"
json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("saved:", OUT_PATH)
for k, v in out.items():
    core = " ".join(v["summary"]["core_diagnosis"])
    print("###", k)
    print(core)
