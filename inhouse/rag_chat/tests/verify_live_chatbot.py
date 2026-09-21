"""배포된 챗봇의 핵심 질의 필수 수락 검사."""
import json
import os
import sys
import time
import urllib.request


BASE = os.environ.get("CHAT_BASE_URL", "http://127.0.0.1:18002").rstrip("/")


def ask(message):
    body = json.dumps({"user_id": "deploy-verification", "message": message}).encode()
    request = urllib.request.Request(
        BASE + "/pubchat", body, {"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines()
                  if line.startswith("data: ")]
    done = [event for event in events if event.get("done")]
    assert done, (message, events)
    return done[-1], events


def require_citation(done, action_id, source):
    assert not done.get("abstained") and not done.get("needs_clarification"), done
    matches = [item for item in done.get("citations", [])
               if item.get("action_id") == action_id and item.get("source") == source]
    assert matches, done
    return matches[0]


def tables(events):
    return [event for event in events if event.get("rows") and event.get("columns")]


def check_price_series(mineral):
    question = f"최근 1년간 {mineral} 가격 추이를 보여줘"
    done, events = ask(question)
    citation = require_citation(done, "price.series", "public.KO_MNRL_PRC")
    assert citation.get("observed_period"), done
    price_tables = [table for table in tables(events)
                    if any("기준일자" in column for column in table["columns"])
                    and any("가격" in column for column in table["columns"])]
    assert price_tables and len(price_tables[0]["rows"]) >= 2, (question, done)
    print(f"[OK] {mineral} 최근 1년 가격 추이 요청 · 실제 관측기간 명시", flush=True)


def check_import_country_share(mineral):
    question = f"{mineral} 수입 상위 5개국과 국가별 비중을 알려줘"
    done, events = ask(question)
    require_citation(done, "trade.country_rank", "public.KO_CSTM_CMMRC")
    ranking = [table for table in tables(events)
               if any("수입금액합계" in column for column in table["columns"])
               and any("비중" in column for column in table["columns"])]
    assert ranking, (question, done)
    rows = ranking[0]["rows"]
    assert 1 <= len(rows) <= 5, rows
    assert [int(row[0]) for row in rows] == list(range(1, len(rows) + 1)), rows
    shares = [float(row[3]) for row in rows]
    assert all(0 <= share <= 100 for share in shares) and sum(shares) <= 100.1, rows
    print(f"[OK] {mineral} 수입 상위국 · 국가별 비중", flush=True)


def check_rare_earth_resource_ranking():
    question = "희토류 생산량과 매장량 상위 국가를 알려줘"
    done, events = ask(question)
    for source, label in (("public.KO_RSRC_PRDCTN_QUTY", "생산량합계"),
                          ("public.KO_RSRC_BURUDG_QUTY", "매장량합계")):
        require_citation(done, "resource.rank", source)
        ranking = [table for table in tables(events)
                   if any(label in column for column in table["columns"])]
        assert ranking and ranking[0]["rows"], (question, source, done)
        assert int(ranking[0]["rows"][0][0]) == 1, ranking[0]["rows"]
    print("[OK] 희토류 생산량·매장량 상위 국가", flush=True)


def check_q01_to_q30_samples():
    # 원문: 챗봇-응답품질-평가_260916.xlsx, 질문별 평가 시트.
    success_cases = (
        ("Q03", "한국의 리튬 수입 상위 5개국과 국가별 비중을 차트로 보여줘. 대상 기간과 금액 기준인지 중량 기준인지 알려줘.",
         "trade.country_rank", "public.KO_CSTM_CMMRC", "비중"),
        ("Q14", "HS코드 2603000000의 품목명과 한국 수입 현황을 알려줘. 광종 전체 수치와 구분해줘.",
         "trade.hs_summary", "public.KO_CSTM_CMMRC", "2603000000"),
    )
    for case_id, question, action_id, source, required_text in success_cases:
        done, events = ask(question)
        citation = require_citation(done, action_id, source)
        assert citation.get("observed_period"), (case_id, done)
        assert tables(events), (case_id, done)
        assert any(event.get("spec") for event in events), (case_id, done)
        answer = "".join(event.get("delta", "") for event in events)
        assert required_text in answer, (case_id, answer)
        print(f"[OK] {case_id} 성공 응답 · 출처·표·차트", flush=True)

    failure_cases = (
        ("Q02", "코발트 광물종합지표의 최근 12개월 변화를 차트로 보여주고 주요 변화를 설명해줘.",
         "source_unavailable"),
        ("Q26", "2030년 리튬 실제 월별 가격을 차트로 보여줘. 아직 없는 실측 자료라면 없다고 알려줘.",
         "source_unavailable"),
        ("Q27", "언옵테이늄의 한국 수입국 비중과 현재 위기점수를 알려줘.",
         "source_unavailable"),
        ("Q30", "오늘 서울 날씨와 점심 메뉴를 추천해줘.", "out_of_scope"),
    )
    for case_id, question, reason in failure_cases:
        done, events = ask(question)
        assert done.get("abstained") is True and done.get("abstain_reason") == reason, (case_id, done)
        assert not done.get("citations") and not tables(events), (case_id, done)
        assert not any(event.get("spec") for event in events), (case_id, done)
        print(f"[OK] {case_id} 정상 기권 · {reason}", flush=True)


def main():
    for attempt in range(30):
        try:
            with urllib.request.urlopen(BASE + "/healthz", timeout=5) as response:
                assert response.status == 200
            break
        except (OSError, AssertionError):
            if attempt == 29:
                raise
            time.sleep(2)
    for question, expected in (
        ("니켈 가격 추이를 보려면 어느 페이지로 가야 돼?", "price_base_metals"),
        ("한국의 리튬 수입 데이터를 보려면 어디로 가야 돼?", "map_korea"),
    ):
        done, _ = ask(question)
        pages = [item.get("page_id") for item in done.get("recommendations", [])]
        assert done.get("mode") == "page" and expected in pages, (question, done)
        print(f"[OK] 페이지 안내: {expected}", flush=True)
    question = "구리 광산 생산량 최근 YoY 증가 상위 5개를 보여줘"
    done, events = ask(question)
    response_text = json.dumps(events, ensure_ascii=False)
    assert not done.get("abstained") and not done.get("needs_clarification"), done
    assert "2024" in response_text and "2025" in response_text, done
    assert "광산" in response_text and ("증가" in response_text or "YoY" in response_text), done
    print("[OK] 광산 생산량 최근 YoY 증가", flush=True)
    for mineral in ("구리", "니켈"):
        check_price_series(mineral)
    check_import_country_share("리튬")
    check_rare_earth_resource_ranking()
    check_q01_to_q30_samples()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FAIL] 라이브 챗봇 수락 검사: {exc}", file=sys.stderr)
        raise
