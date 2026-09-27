"""사용자 제공 광물 Q&A 쌍을 라이브 챗봇에 재현하고 증적 보고서를 남긴다.

실행 예:
  python3 inhouse/rag_chat/tests/audit_user_qa_pairs.py \
    --output-dir documents/산출물/acceptance_results/20260928-user-qa-pairs

질문은 서로 영향을 주지 않도록 매번 독립 session_id를 사용한다. 이 도구는 답변의
사실성을 임의 판정하지 않고, SSE 종료 계약·실제 action/source·기대 출력 표지를
기록한다. 원천 미확보 안전 종료는 구현 실패와 구별한다.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


CASES = (
    # 광물정보·문서·뉴스 단일 메뉴
    ("MI01", "니켈은 어디에 쓰여?", ("용도",)),
    ("MI02", "니켈은 어떤 금속이야?", ("원소", "특성")),
    ("MI03", "구리 기본 특성을 알려줘", ("원소", "특성")),
    ("MI04", "망간 주요 광석 종류는?", ("광석",)),
    ("DOC01", "이번달 전략 광종 월간 동향 요약해줘", ("월간", "요약")),
    ("DOC02", "최근 월간동향 제목 알려줘", ("최신", "제목")),
    ("DOC03", "최근 3개월 월간 동향에서 니켈 관련 내용 찾아줘", ("니켈", "게시")),
    ("DOC04", "월간 동향 게시판 검색은 어떻게 해?", ("검색", "개월")),
    ("NEWS01", "최근 자원 뉴스 뭐 있어?", ("뉴스", "기사")),
    ("NEWS02", "이번주 주간 자원뉴스 요약해줘", ("주간", "뉴스")),
    ("NEWS03", "최근 중국 수출통제 관련 뉴스 있어?", ("기사", "뉴스")),
    # 가격·예측 및 지수 결합
    ("PF01", "니켈 현재 가격이랑 다음달 전망 같이 알려줘", ("가격", "전망")),
    ("PF02", "니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘", ("가격", "전망")),
    ("PF03", "니켈 지금 가격이 전망치 보다 높은 편이야?", ("현재", "전망")),
    ("IX01", "광물지수 오를때 같이 오른 광종은 뭐야?", ("광물종합지수", "가격")),
    ("IX02", "니켈 가격 추세랑 광물 종합지수 추세 비교해주세요", ("니켈", "광물")),
    ("MP01", "니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘", ("가격", "수입")),
    ("MP02", "중국 수입 비중 높은 광종 중 최근 가격 오른건 뭐야?", ("점유율", "가격")),
    ("MP03", "니켈 수입 상위국이랑 현재가격 알려줘", ("수입", "가격")),
    ("MP04", "니켈 가격이랑 세계 생산량 변화 같이 보여줘", ("가격", "생산")),
    ("MP05", "생산 1위국 비중이 높은 광종들 가격 변동 어때?", ("생산", "가격")),
    ("MP06", "니켈은 어디에 쓰이고 지금 가격은 얼마야?", ("용도", "가격")),
    ("MP07", "전략광종 가격 현황 한눈에 보여줘", ("전략", "가격")),
    ("MP08", "이번달 희소금속 월간 동향에 나온 광종들 가격 어때?", ("월간", "가격")),
    ("MP09", "니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘", ("가격", "월간")),
    # 가격·뉴스·전망 결합
    ("CN01", "니켈 가격 크게 오른 날 관련 뉴스 있어?", ("가격", "뉴스")),
    ("CN02", "이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘", ("가격", "뉴스")),
    ("CN03", "광물종합지수 구성 광종 중 상승 전망인 건 뭐야?", ("광물종합지수", "전망")),
    ("CN04", "수입 의존도 높은 광종들 가격 전망 알려줘", ("수입", "전망")),
    ("CN05", "리튬 주요 수입국이랑 가격 전망 같이 보여줘", ("수입", "전망")),
    ("CN06", "구리 가격 전망이랑 월간동향 시장 전망 내용 비교해줘", ("전망", "월간")),
    ("CN07", "리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘", ("전망", "뉴스")),
    ("CN08", "지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘", ("광물종합지수", "월간")),
    ("CN09", "광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?", ("광물종합지수", "뉴스")),
    # 생산·수입 지도 / 광물 정보 결합
    ("GM01", "코발트 세계 생산국이랑 우리나라 수입국 비교해줘", ("생산", "수입")),
    ("GM02", "리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?", ("생산", "수입")),
    ("GM03", "흑연 생산 집중도랑 수입 집중도 비교해줘", ("생산", "수입")),
    ("GM04", "2차전지 광물 수입국 구성 알려줘", ("리튬", "수입")),
    ("GM05", "망간 용도랑 주요 수입국 알려줘", ("용도", "수입")),
    ("GM06", "이번 달 전략광종 월간동향에 나온 광종들 우리 수입 구조 어때?", ("월간", "수입")),
    ("GM07", "중국 수출통제 뉴스에 나온 광종 중국 수입 비중 알려줘", ("뉴스", "중국")),
    ("GM08", "텅스텐 용도랑 세계 생산국 알려줘", ("용도", "생산")),
    ("GM09", "이번 달 전략광종 월간동향에서 다룬 광종 기본 정보 알려줘", ("월간", "광물")),
    ("GM10", "이번 달 월간동향이랑 이번 주 뉴스에 공통으로 나온 이슈는?", ("월간", "뉴스")),
    ("GM11", "흑연 공급 현황 종합해서 알려줘", ("생산", "수입")),
    ("GM12", "2차전지 광물 5종 가격이랑 전망 한 번에 보여줘", ("리튬", "전망")),
    ("GM13", "코발트 현황 브리핑해줘", ("가격", "생산")),
    ("GM14", "중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘", ("뉴스", "수입")),
    # 사용자가 별도 지적한 기본 질의
    ("REG01", "리튬 주요 수출국을 알려줘", ("수출",)),
    ("REG02", "오늘 니켈 가격 얼마야?", ("니켈", "가격")),
    ("REG03", "최근 니켈 가격 얼마야?", ("니켈", "가격")),
    ("REG04", "니켈 가격 년도별 평균 가격을 알려줘", ("가격",)),
    ("REG05", "니켈 LME 재고량 알려줘", ("LME",)),
    ("REG06", "니켈 텅스텐 가격 같이 비교해줘", ("니켈", "텅스텐")),
    ("REG07", "니켈 다음달 가격 전망 알려줘", ("니켈", "전망")),
    ("REG08", "니켈 수입 집중도를 알려줘요", ("니켈", "수입")),
)


def ask(base_url: str, question: str, timeout: int) -> tuple[list[dict], dict]:
    body = json.dumps({
        "user_id": "qa-pair-audit",
        # API가 UUID 타입을 요구하므로, 표시용 접두어를 붙이지 않는다.
        "session_id": str(uuid4()),
        "message": question,
    }).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/pubchat", body,
        {"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    terminal = [event for event in events if event.get("done")]
    if len(terminal) != 1 or not events or events[-1] is not terminal[0]:
        raise RuntimeError(f"SSE terminal contract violation: events={len(events)}, done={len(terminal)}")
    return events, terminal[0]


def answer(events: list[dict]) -> str:
    return "".join(str(event.get("delta", "")) for event in events).strip()


def classify(events: list[dict], terminal: dict, expected: tuple[str, ...]) -> tuple[str, list[str]]:
    text = answer(events)
    if terminal.get("needs_clarification"):
        return "NEEDS_CLARIFICATION", ["필수 슬롯 확인 필요"]
    if terminal.get("abstained"):
        reason = str(terminal.get("abstain_reason") or "unknown")
        return ("BLOCKED_DATA" if reason == "source_unavailable" else "FAIL"), [f"abstain_reason={reason}"]
    missing = [token for token in expected if token.casefold() not in text.casefold()]
    if missing:
        return "PARTIAL", [f"기대 표지 미검출: {', '.join(missing)}"]
    return "PASS", []


def compact(value: object, limit: int = 1800) -> str:
    text = str(value).replace("\r", "").strip()
    return text if len(text) <= limit else text[:limit] + "…(생략)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18002")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    results: list[dict] = []
    for number, (case_id, question, expected) in enumerate(CASES, start=1):
        started = time.monotonic()
        record = {"id": case_id, "question": question, "expected_markers": list(expected)}
        try:
            events, terminal = ask(args.base_url, question, args.timeout)
            status, notes = classify(events, terminal, expected)
            record.update({
                "status": status, "notes": notes,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "answer": answer(events), "terminal": terminal,
                "actions": sorted({str(item.get("action_id")) for item in terminal.get("citations", []) if item.get("action_id")}),
                "sources": sorted({str(item.get("source")) for item in terminal.get("citations", []) if item.get("source")}),
                "table_count": sum(bool(item.get("columns") and item.get("rows")) for item in events),
                "chart_count": sum(bool(item.get("spec")) for item in events),
            })
        except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
            record.update({"status": "FAIL", "notes": [f"request_error={type(exc).__name__}: {exc}"],
                           "elapsed_seconds": round(time.monotonic() - started, 2)})
        results.append(record)
        print(f"[{number:02d}/{len(CASES)}] {case_id} {record['status']} {record['elapsed_seconds']}s", flush=True)

    summary = Counter(item["status"] for item in results)
    raw_path = output_dir / f"user_qa_pair_audit_{timestamp}.json"
    raw_path.write_text(json.dumps({"generated_at": timestamp, "base_url": args.base_url,
                                    "summary": dict(summary), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output_dir / f"user_qa_pair_audit_{timestamp}.md"
    lines = [
        "# 사용자 제공 Q&A 쌍 라이브 점검 결과", "",
        f"- 실행 시각: {timestamp} (Asia/Seoul)",
        f"- 대상: `{args.base_url}/pubchat`", f"- 질문 수: {len(results)}",
        f"- 집계: " + ", ".join(f"{key} {value}" for key, value in sorted(summary.items())), "",
        "판정: `PASS`는 SSE 종료 계약과 질문별 기대 표지가 확인된 응답, `PARTIAL`은 응답은 있으나 "
        "기대 표지 일부가 없는 경우, `BLOCKED_DATA`는 `source_unavailable` 안전 종료, `FAIL`은 "
        "요청/종료 계약 오류 또는 기타 기권입니다. 키워드 검사는 형식 점검 보조 수단이며 사실성의 최종 판정은 아닙니다.", "",
        "|ID|판정|질문|Action / Source|표·차트|비고|", "|---|---|---|---|---|---|",
    ]
    for item in results:
        action_source = ", ".join(item.get("actions", []) + item.get("sources", [])) or "-"
        visual = f"표 {item.get('table_count', 0)} / 차트 {item.get('chart_count', 0)}"
        notes = "; ".join(item.get("notes", [])) or "-"
        question = item["question"].replace("|", "\\|")
        lines.append(f"|{item['id']}|{item['status']}|{question}|{compact(action_source, 220)}|{visual}|{notes}|")
    lines += ["", "## 응답 원문 발췌", ""]
    for item in results:
        lines += [f"### {item['id']} — {item['status']}", "", f"질문: {item['question']}", "",
                  compact(item.get("answer", "(응답 없음)")), ""]
    lines += [f"원본 SSE terminal·응답 전문: `{raw_path.name}`", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "raw": str(raw_path), "summary": dict(summary)}, ensure_ascii=False))
    return 0 if not summary.get("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
