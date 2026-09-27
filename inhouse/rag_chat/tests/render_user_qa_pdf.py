"""사용자 Q&A 라이브 점검 JSON을 질문·실제 출력·PASS 여부 PDF로 렌더링한다."""

from __future__ import annotations

import argparse
import json
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


def _font() -> str:
    # Matplotlib의 폰트 캐시가 설치 직후 시스템 fontconfig 목록을 반영하지 않는
    # 환경이 있어, 프로젝트 실행 계정에 설치된 한글 글꼴 경로를 먼저 확인한다.
    installed = Path("/home/nuri/.local/share/fonts/NotoSansKR-Regular.otf")
    if installed.is_file():
        return str(installed)
    candidates = [font for font in font_manager.fontManager.ttflist if "Noto Sans KR" in font.name]
    if not candidates:
        raise RuntimeError("Noto Sans KR 글꼴을 찾을 수 없습니다.")
    return candidates[0].fname


def _wrap(text: str, width: int) -> str:
    lines: list[str] = []
    for paragraph in (text or "(응답 없음)").splitlines() or ["(응답 없음)"]:
        lines.extend(textwrap.wrap(paragraph, width=width, break_long_words=False,
                                  break_on_hyphens=False) or [""])
    return "\n".join(lines)


def _pass_label(status: str) -> tuple[str, str]:
    if status == "PASS":
        return "PASS", "#d9ead3"
    if status == "BLOCKED_DATA":
        return "SKIP\n(원천 부재)", "#fff2cc"
    if status == "PARTIAL":
        return "FAIL\n(부분 응답)", "#fce5cd"
    return "FAIL", "#f4cccc"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_pdf", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    results = payload["results"]
    counts = Counter(row["status"] for row in results)
    font_path = _font()
    font_prop = font_manager.FontProperties(fname=font_path)
    plt.rcParams["font.family"] = font_prop.get_name()
    plt.rcParams["axes.unicode_minus"] = False

    args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(args.output_pdf) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.5, 0.78, "사용자 제공 Q&A 쌍 라이브 재점검", ha="center", va="center",
                 fontsize=24, fontproperties=font_prop, weight="bold")
        summary = " · ".join(f"{key} {value}건" for key, value in sorted(counts.items()))
        body = (
            f"대상: {payload.get('base_url')}/pubchat\n"
            f"실행 시각: {payload.get('generated_at')} (Asia/Seoul)\n"
            f"질문 수: {len(results)}건\n"
            f"집계: {summary}\n\n"
            "PASS는 SSE 종료 계약 및 질문별 기대 출력 표지가 확인된 응답입니다.\n"
            "SKIP(원천 부재)는 source_unavailable 안전 종료이며 구현 실패로 집계하지 않습니다.\n"
            "표·차트는 존재 여부만 기록하며, 이번 판정에서는 시각적 품질을 검수하지 않습니다.\n"
            "각 행의 실제 출력은 PDF 가독성을 위해 최대 1,600자로 표시하며, 전문은 함께 저장된 JSON에 보존됩니다."
        )
        fig.text(0.13, 0.58, body, ha="left", va="top", fontsize=13, fontproperties=font_prop,
                 linespacing=1.75)
        fig.text(0.13, 0.12, f"원본: {args.input_json.name}", ha="left", fontsize=9,
                 fontproperties=font_prop)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        # 두 질문씩 한 페이지에 배치해 실제 답변을 읽을 수 있게 한다.
        for offset in range(0, len(results), 2):
            rows = results[offset:offset + 2]
            fig, axes = plt.subplots(len(rows), 1, figsize=(11.69, 8.27))
            if len(rows) == 1:
                axes = [axes]
            for axis, row in zip(axes, rows):
                axis.axis("off")
                label, color = _pass_label(row["status"])
                actions = ", ".join(row.get("actions", [])) or "-"
                sources = ", ".join(row.get("sources", [])) or "-"
                notes = "; ".join(row.get("notes", [])) or "-"
                answer = row.get("answer", "")
                if len(answer) > 1600:
                    answer = answer[:1600] + "… (이하 원본 JSON 참조)"
                cells = [[
                    row["id"],
                    label,
                    _wrap(row["question"], 42),
                    _wrap(answer, 94),
                ]]
                table = axis.table(
                    cellText=cells,
                    colLabels=["ID", "PASS 여부", "질문", "실제 출력"],
                    colWidths=[0.07, 0.12, 0.25, 0.56],
                    cellLoc="left", colLoc="center", loc="upper center",
                )
                table.auto_set_font_size(False)
                table.set_fontsize(8.6)
                table.scale(1, 4.8)
                for (r, c), cell in table.get_celld().items():
                    cell.set_edgecolor("#808080")
                    cell.get_text().set_fontproperties(font_prop)
                    cell.get_text().set_va("top")
                    if r == 0:
                        cell.set_facecolor("#d9eaf7")
                        cell.get_text().set_weight("bold")
                        cell.get_text().set_ha("center")
                    elif c == 1:
                        cell.set_facecolor(color)
                        cell.get_text().set_ha("center")
                meta = (f"Action: {actions}   |   Source: {sources}   |   표 {row.get('table_count', 0)} / "
                        f"차트 {row.get('chart_count', 0)} (검수 제외)   |   비고: {notes}")
                axis.text(0.01, 0.02, _wrap(meta, 160), transform=axis.transAxes, fontsize=7.3,
                          va="bottom", fontproperties=font_prop)
            fig.tight_layout(h_pad=1.2)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


if __name__ == "__main__":
    main()
