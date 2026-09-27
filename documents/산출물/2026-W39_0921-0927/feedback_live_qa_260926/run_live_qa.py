import json
import sys
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:18002"
OUT = Path("/home/nuri/dev/git/ws/mine_ws/komir/documents/산출물/2026-W39_0921-0927/feedback_live_qa_260926")
OUT.mkdir(parents=True, exist_ok=True)
QUESTIONS = [
"오늘 니켈 가격 얼마야?", "구리 가격 전주·전월 평균이랑 비교하면 어때?", "리튬 가격 최근 1년 월별 추이 보여줘", "텅스텐 가격 몇 개월째 오르고 있어?", "알루미늄 연도별 평균 가격 알려줘", "니켈 LME 재고량 알려줘", "구리랑 아연 가격 같이 비교해줘", "코발트 가격 기준가격 대비 얼마나 올랐어?", "광물가격은 언제 업데이트돼?", "광물가격 자료원이 바뀌었다던데 무슨 내용이야?", "리튬 작년 가격이랑 올해 가격 비교해도 돼?", "광물가격 데이터 엑셀로 받을 수 있어?",
"다음 달 구리 가격 전망 알려줘", "니켈 가격 앞으로 오를까 내릴까?", "가격예측 제공되는 광종은 뭐야?", "가격예측은 몇 개월 앞까지 볼 수 있어?", "오늘 광물종합지수 얼마야?", "광물종합지수가 뭐야?", "최근 3개월 광물종합지수 추세 알려줘", "광물종합지수 올해 고점·저점은?", "우리나라 리튬 어디서 주로 수입해?", "흑연 수입 중 중국 비중 얼마야?", "코발트 수입액이랑 수입량 알려줘", "니켈 수입 집중도(CR3, CR5) 알려줘", "세계 리튬 수출 상위국은 어디야?", "수급지도 기준 시점이 언제야?", "세계 리튬 생산 1위 국가는?", "희토류 생산국 순위 알려줘", "리튬 생산량 전년 대비 얼마나 늘었어?", "흑연 생산량 조회기간 전체 변화율은?", "니켈 매장량 많은 나라는?", "지도에 원 크기는 무슨 뜻이야?",
"텅스텐은 어디에 쓰여?", "갈륨 기본 특성 알려줘", "망간 주요 광석 종류는?", "전략광종이 뭐야?", "이번 달 전략광종 월간동향 요약해줘", "최근 희소금속 월간동향 보고서 제목 알려줘", "최근 3개월 월간동향에서 리튬 관련 내용 찾아줘", "월간동향 게시판 검색은 어떻게 해?", "오늘 자원뉴스 뭐 있어?", "이번 주 주간자원뉴스 요약해줘", "최근 중국 수출통제 관련 뉴스 있어?",
"리튬 현재 가격이랑 다음 달 전망 같이 알려줘", "구리 지난 6개월 가격이랑 향후 전망 이어서 보여줘", "니켈 지금 가격이 전망치보다 높은 편이야?", "광물종합지수 오를 때 같이 오른 광종은 뭐야?", "구리 가격 추세랑 광물종합지수 추세 비교해줘", "흑연 가격 추이랑 우리나라 수입국 구성 같이 보여줘", "중국 수입 비중 높은 광종 중 최근 가격 오른 건 뭐야?", "코발트 수입 상위국이랑 현재 가격 알려줘", "리튬 가격이랑 세계 생산량 변화 같이 보여줘", "생산 1위국 비중이 높은 광종들 가격 변동 어때?", "갈륨은 어디에 쓰이고 지금 가격은 얼마야?", "전략광종 가격 현황 한눈에 보여줘", "이번 달 희소금속 월간동향에 나온 광종들 가격 어때?", "텅스텐 가격 추이랑 최근 월간동향 내용 같이 알려줘", "니켈 가격 크게 오른 날 관련 뉴스 있어?", "이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘", "광물종합지수 구성 광종 중 상승 전망인 건 뭐야?", "수입 의존도 높은 광종들 가격 전망 알려줘", "리튬 주요 수입국이랑 가격 전망 같이 보여줘", "니켈 세계 생산량 추이랑 가격 전망 같이 보여줘", "구리 가격 전망이랑 월간동향 시장 전망 내용 비교해줘", "리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘", "지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘", "광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?",
"코발트 세계 생산국이랑 우리나라 수입국 비교해줘", "리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?", "흑연 생산 집중도랑 수입 집중도 비교해줘", "2차전지 광물 수입국 구성 알려줘", "망간 용도랑 주요 수입국 알려줘", "이번 달 전략광종 월간동향에 나온 광종들 우리 수입 구조 어때?", "중국 수출통제 뉴스에 나온 광종 중국 수입 비중 알려줘", "텅스텐 용도랑 세계 생산국 알려줘", "희소금속 월간동향에 나온 광종 생산량 추이 보여줘", "인도네시아 니켈 뉴스랑 인도네시아 생산량 추이 같이 보여줘", "이번 달 전략광종 월간동향에서 다룬 광종 기본 정보 알려줘", "이번 달 월간동향이랑 이번 주 뉴스에 공통으로 나온 이슈는?",
"흑연 공급 현황 종합해서 알려줘", "2차전지 광물 5종 가격이랑 전망 한 번에 보여줘", "코발트 현황 브리핑해줘", "중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘",
]
CHAINS = [
    ("trade_clarify_new_intent", ["리튬의 TSI를 계산해줘", "한국 기준 2025년으로 계산해줘", "2025년 한국 리튬 수입의 중국 의존도도 알려줘"]),
    ("price_anaphora", ["니켈 가격 알려줘", "그 데이터와 비교해서 리튬은 어때?"]),
    ("page_cancel_out_of_scope", ["광물지도 보여줘", "취소하고 오늘 서울 날씨 알려줘"]),
    ("multi_action_followup", ["리튬 수입 상위국과 가격을 알려줘", "그 기간 기준 생산량 변화도 같이 보여줘"]),
]
LEGACY_CASES = [
    ("A1", "리튬 수입수요 예측은 어느 메뉴에서 볼 수 있습니까?"),
    ("A2", "핵심광물 지표를 한 화면에서 보고 싶어요"),
    ("B3", "코발트 수급동향지표의 최근 6개월 추이를 보여주십시오"),
    ("B4", "니켈과 리튬 중 최근 변동성이 큰 광물은 무엇입니까?"),
    ("C1", "인도네시아 니켈 수출 규제 관련 최근 보고서를 찾아주십시오"),
    ("C2", "코발트 수급동향지표가 주의로 변경된 배경 문서를 알려주십시오"),
    ("C3", "리튬 공급망 관련 최근 자원뉴스를 요약해주십시오"),
    ("D1", "규회석 가격 추이를 보여주십시오"),
    ("D2", "2010년 1월 니켈 수급동향지표 알려줘"),
    ("D3", "신규 편입 광종의 장기 수요예측을 알려주세요"),
    ("D4", "니켈 데이터 보여주세요"),
    ("D5", "다른 사용자의 조회 이력을 보여주십시오"),
    ("D6", "니켈 주 지금 사도 됩니까?"),
]

def request(question, session_id):
    data = json.dumps({"user_id": "feedback-live-qa-20260926", "session_id": session_id, "message": question}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/pubchat", data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            raw = res.read()
            status = res.status
        events = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except Exception:
                    pass
        record = {"http_status": status, "elapsed_seconds": round(time.monotonic()-t0, 3), "events": events,
                  "raw_sse": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        record = {"http_status": e.code, "elapsed_seconds": round(time.monotonic()-t0, 3), "events": [], "raw_sse": body, "transport_error": repr(e), "http_error_body": body}
    except Exception as e:
        record = {"http_status": None, "elapsed_seconds": round(time.monotonic()-t0, 3), "events": [], "raw_sse": "", "transport_error": repr(e)}
    text = "".join(str(e.get("delta", "")) for e in record["events"] if isinstance(e, dict))
    done = [e for e in record["events"] if isinstance(e, dict) and e.get("done")]
    record.update({"question": question, "session_id": session_id, "answer_text": text,
                   "done_count": len(done), "done": done[-1] if done else None,
                   "event_count": len(record["events"])})
    return record

def main():
    run = {"run_id": "feedback_live_" + datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S"),
           "endpoint": BASE + "/pubchat", "started_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
           "question_count": len(QUESTIONS), "container_image_from_docker_ps": "komir-rag-chat:260926-live-qa-8a873378b",
           "retry_count": 0, "timeout_seconds": 180}
    (OUT / "run_manifest.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "single_turn_responses.jsonl").open("w", encoding="utf-8") as f:
        for n, q in enumerate(QUESTIONS, 1):
            rec = request(q, str(uuid.uuid4()))
            rec["question_id"] = f"FBQ{n:02d}"
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            print(f"{n:02d}/{len(QUESTIONS)} {rec['http_status']} done={rec['done_count']} {rec.get('elapsed_seconds')}s {q}", flush=True)
    chain_path = OUT / "multihop_responses.jsonl"
    with chain_path.open("w", encoding="utf-8") as f:
        for chain_id, questions in CHAINS:
            session = str(uuid.uuid4())
            for turn, q in enumerate(questions, 1):
                rec = request(q, session); rec.update({"chain_id": chain_id, "turn": turn})
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                print(f"{chain_id} turn {turn}/{len(questions)} {rec['http_status']} done={rec['done_count']} {rec.get('elapsed_seconds')}s", flush=True)
    run["finished_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    (OUT / "run_manifest.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False))

def run_legacy_only():
    path = OUT / "legacy_feedback_responses.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for case_id, question in LEGACY_CASES:
            rec = request(question, str(uuid.uuid4()))
            rec["case_id"] = case_id
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            print(f"{case_id} {rec['http_status']} done={rec['done_count']} {rec.get('elapsed_seconds')}s {question}", flush=True)
        session = str(uuid.uuid4())
        for turn, question in enumerate(["니켈 가격 알려줘", "그 데이터와 비교해서 리튬은 어때?"], 1):
            rec = request(question, session)
            rec.update({"case_id": "E1", "turn": turn})
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            print(f"E1 turn {turn} {rec['http_status']} done={rec['done_count']} {rec.get('elapsed_seconds')}s", flush=True)

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "legacy-only":
    run_legacy_only()
elif __name__ == "__main__":
    main()
