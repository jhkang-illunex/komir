"""복합 Action의 근거 귀속 지시와 결정적 실패 안내를 조립한다."""
from __future__ import annotations

from .action_results import RetrievalResult


_ACTION_LABELS = {
    "price.series": "광물가격", "price.compare": "광물가격 비교",
    "forecast.price": "가격예측", "indicator.series": "광물지표",
    "trade.country_rank": "수출입 국가 순위", "trade.monthly": "수출입 현황",
    "trade.concentration": "수출입 집중도", "resource.rank": "생산·매장량 순위",
    "document.retrieve": "문서 내용", "document.lookup": "문서 원문",
    "mine.profile": "광산 정보", "mine.rank": "광산 순위",
}


class AnswerComposer:
    """수치 계산 없이 검증된 Action 결과만 생성 모델에 전달한다."""

    def instruction(self, result: RetrievalResult | None) -> str:
        if result is None or result.action_plan is None or len(result.action_plan.actions) < 2:
            return ""
        evidence_indices: dict[str, list[int]] = {}
        for index, evidence in enumerate(result.evidence, 1):
            if evidence.requirement_id:
                evidence_indices.setdefault(evidence.requirement_id, []).append(index)
        outcomes = {item.requirement_id: item for item in result.action_results}
        lines = [
            "[복합 질의 응답 규칙]",
            "아래 요구사항별 근거 번호만 사용해 각각 별도 절로 답하십시오. "
            "다른 요구사항의 수치·기간·광종·출처를 섞지 마십시오.",
        ]
        for call in result.action_plan.actions:
            outcome = outcomes.get(call.requirement_id)
            indices = evidence_indices.get(call.requirement_id, [])
            if indices and (outcome is None or outcome.status == "success"):
                refs = ", ".join(f"[{index}]" for index in indices)
                lines.append(
                    f"- requirement_id={call.requirement_id}; action_id={call.action_id}; "
                    f"상태=성공; 사용 가능한 근거={refs}"
                )
            else:
                lines.append(
                    f"- requirement_id={call.requirement_id}; action_id={call.action_id}; "
                    "상태=조회 불가; 사용 가능한 근거=없음"
                )
        lines.append(
            "조회 불가 요구사항의 사실·수치를 생성하지 마십시오. 해당 안내는 코드가 별도로 덧붙입니다. "
            "근거에 없는 수치·원인·전망을 추정하지 마십시오.\n"
        )
        return "\n".join(lines)

    def failure_notice(self, result: RetrievalResult | None) -> str:
        if result is None or result.action_plan is None or len(result.action_plan.actions) < 2:
            return ""
        notices = []
        for item in result.action_results:
            if item.status == "success" or item.action_id == "forecast.price":
                # 가격예측 부분 응답은 기존 _partial_forecast_notice가 담당한다.
                continue
            label = _ACTION_LABELS.get(item.action_id, "요청 정보")
            if item.status == "blocked":
                detail = "앞선 조회 결과가 없어 처리할 수 없습니다."
            elif item.status == "no_data":
                detail = "조회한 조건에 해당하는 데이터를 찾지 못했습니다."
            else:
                detail = "확인 가능한 자료가 없어 답변할 수 없습니다."
            notices.append(f"{label}: {detail}")
        return ("\n\n" + "\n".join(notices)) if notices else ""
