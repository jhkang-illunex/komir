"""배포된 챗봇의 핵심 질의 필수 수락 검사."""
import json
import os
import re
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


def check_nickel_price_unit_contract():
    for label, question in (
        ("Q01", "최근 1년간 니켈 가격 추이를 보여줘"),
        ("Q23", "니켈 가격 추이를 알려줘"),
    ):
        done, events = ask(question)
        citation = require_citation(done, "price.series", "public.KO_MNRL_PRC")
        unit = citation.get("unit") or ""
        assert "가격기준=LME CASH" in unit and "통화코드=PR001" in unit and "중량단위코드=WT002" in unit, (label, citation)
        answer = "".join(event.get("delta", "") for event in events)
        assert unit in answer, (label, answer)
        assert "조회된 가격 시계열의 실제 관측 기간은" in answer, (label, answer)
        assert "아래 표와 차트는 해당 기간의 원자료를 표시합니다." in answer, (label, answer)
        assert "가격 단위: 제공된 문서에 통화 단위가 명시되지 않았습니다" not in answer, (label, answer)
        assert "개발용 더미" not in answer, (label, answer)
        # 인용 뒤 목록은 같은 줄에 붙으면 Markdown 구조가 깨진다. ``\\s``는
        # 정상 줄바꿈까지 잡으므로 공백·탭만 검사한다.
        assert not re.search(r"\[\d+\][ \t]*\*", answer), (label, answer)
        assert not re.search(r"\[\d+\][ \t]*\d+\.\s+", answer), (label, answer)
        assert not re.search(r"\[\d+\]\s+\*\*\[", answer), (label, answer)
        assert not re.search(r"\[\d+\][ \t]*\|", answer), (label, answer)
        # 단일 series 본문은 관측기간·선택 기준만 결정적으로 말한다. 개별 행과
        # 고점/저점의 생성 서술은 표·차트 원자료와 불일치할 위험이 있다.
        assert not re.search(r"최고가|최저가|최고|최저|고점을\s*형성|저점을\s*형성", answer), (label, answer)
        assert not re.search(r"\d{4}-\d{2}-\d{2}[ \t]+[\d,]+(?:\.\d+)?", answer), (label, answer)
        print(f"[OK] {label} 니켈 선택 가격기준 단위·더미 경고 계약", flush=True)


def check_q15_usgs_scope_contract():
    done, events = ask("희토류와 네오디뮴은 같은 범위의 데이터야? 가격과 생산통계를 비교할 때 주의점을 알려줘.")
    require_citation(done, "document.retrieve", "생산매장량_USGS/USGS_2026.md")
    answer = "".join(event.get("delta", "") for event in events)
    for required in ("REO", "380,000", "390,000", "85,000,000", "산화네오디뮴", "73달러"):
        assert required in answer, (required, answer)
    assert "같은 범위의 단일 지표가 아닙니다" in answer, answer
    print("[OK] Q15 희토류 총괄 통계·Nd 산화물 가격 범위 및 USGS 인용", flush=True)


def check_q28_nickel_2025_claim_contract():
    done, events = ask("2025년 니켈 가격이 300% 이상 올랐어?")
    require_citation(done, "price.verify_claim", "public.KO_MNRL_PRC")
    answer = "".join(event.get("delta", "") for event in events)
    compact = answer.replace(",", "").replace(" ", "")
    assert "15010" in compact and "14519.04" in compact and "-3.27" in compact, answer
    assert "300%" in answer and any(term in answer for term in ("아닙니다", "확인되지", "반박")), answer
    print("[OK] Q28 2025 니켈 실제값·300% 전제 반박", flush=True)


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
        ("HHI+rank", "리튬 수입 상위 5개국과 국가별 비중, 그리고 국가 집중도 HHI를 계산해줘",
         "unsupported_combination"),
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
    check_nickel_price_unit_contract()
    check_q15_usgs_scope_contract()
    check_q28_nickel_2025_claim_contract()
    check_import_country_share("리튬")
    check_rare_earth_resource_ranking()
    check_q01_to_q30_samples()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FAIL] 라이브 챗봇 수락 검사: {exc}", file=sys.stderr)
        raise
