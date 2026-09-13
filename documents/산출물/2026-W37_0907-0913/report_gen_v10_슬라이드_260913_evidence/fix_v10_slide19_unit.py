# -*- coding: utf-8 -*-
"""v10.pptx 슬라이드19(광물지도 교차비교)의 본문 텍스트를 재수정한다.
원인: fetch_v10_new_cases.py가 map_mineral 호출 시 unit='k ton'(KOMIS
원시 코드)을 그대로 넘겨 request.unit이 komis_response에서 자동유도되는
올바른 단위('톤')를 덮어썼다(summary.py::_analyze_mineral_map의
`unit = request.unit or komis_unit` 우선순위) — 그 결과 map_korea/global/
mineral 공통 후처리기 `compact_fact()`(summary.py:986, 톤/달러 단위만
정규식 매칭해 억/만으로 축약)가 'k ton' 단위 문장에는 매칭되지 않아
숫자가 축약 없이 그대로 나갔다. report_gen API 코드는 무결점 — 그저 내
스크립트가 unit을 잘못 넘겼을 뿐이다. unit 필드를 아예 안 보내(자동유도
되게) 재호출한 결과를 v10_new_cases.json에 이미 갱신해뒀고, 여기서는
그 갱신된 텍스트를 슬라이드19에 다시 채워넣기만 한다(표·캡션은 원래도
숫자값 기반이라 영향 없음, 무변경)."""
import json
import sys

sys.path.insert(0, "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad")
from pptx_helpers import find_pptx, get_shape_by_name, set_paragraph, clear_runs
from pptx import Presentation

DATA = json.load(open(
    "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/v10_new_cases.json",
    encoding="utf-8",
))


def base_style(shape):
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            return run.font.size
    return None


def fill(shape, entries):
    size = base_style(shape)
    tf = shape.text_frame
    existing = list(tf.paragraphs)
    for i, (text, is_header) in enumerate(entries):
        p = existing[i] if i < len(existing) else tf.add_paragraph()
        set_paragraph(p, [(text, False)], size=size, bold=(True if is_header else None))
    for j in range(len(entries), len(existing)):
        clear_runs(existing[j])


path = find_pptx("v10")
p = Presentation(path)
slide = p.slides[19]
title = get_shape_by_name(slide, "제목 1").text_frame.text.strip()
assert "교차비교" in title, f"unexpected slide: {title}"

d = DATA["map_mineral_cross"]
box = get_shape_by_name(slide, "TextBox 4")
major = d["sentences"]["major_changes"]
entries = [
    ("세계 매장량 현황", True), (" ".join(d["sentences"]["core_diagnosis"]), False),
    ("국가별 순위 및 변화(교차비교 포함)", True), (" ".join(major[:-1]), False),
    ("주요 변화", True), (major[-1], False),
]
fill(box, entries)

p.save(path)
print("수정 완료:", path)
print(box.text_frame.text)
