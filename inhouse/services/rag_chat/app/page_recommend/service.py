# -*- coding: utf-8 -*-
"""페이지추천 진입점 — 레지스트리·LLM·메타데이터를 묶어 한 턴을 실행한다.

이식 출처: komis-report-generator-main `search/service.py`(2026-08-11 스냅샷).
komir 이식에서 바꾼 것:

1. **대화상태 저장소를 들이지 않는다.** 원본은 LangGraph 체크포인터(SqliteSaver,
   `.state/komis-search.sqlite3`)에 스레드 상태를 얹어 `thread_id`만 넘기면 이전
   턴 상태가 자동 복원되는 구조였다. komir는 이미 chat_session/chat_message
   (MSR_DB, app/session_store.py)로 세션을 관리하므로 SQLite를 새로 들이면 대화
   저장소가 2개가 된다. 그래서 체크포인터 없이 컴파일하고(그래프는 상태를 스스로
   보관하지 않음), 직전 상태(message_history·active_artifact)를 호출자가 넣고
   결과 상태를 돌려받는 형태로 계약을 바꿨다 — DB 접근은 이 파일이 아니라
   routers/chat.py가 session_store로 처리한다(이 모듈은 DB를 모르므로 LLM 더블만
   있으면 테스트 가능).
2. 설정: `search/config.Settings.from_env()` 대신 services/shared/config.py의
   통합 Settings(get_settings)를 쓴다. LLM은 KomirJsonLLM.

원본에 있던 `close()`/컨텍스트매니저는 없앴다 — httpx 클라이언트와 sqlite 커넥션을
직접 소유하던 원본과 달리 여기서는 닫을 자원이 없다(OpenAICompatChat의 requests
세션은 프로세스 수명과 함께 감)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.config import get_settings
from shared.llm_client import KomirJsonLLM

from .graph import SearchWorkflow, validate_response
from .metadata import MetadataResolver, SnapshotMetadataResolver
from .models import SearchResponse
from .registry import ServiceRegistry, load_source_registry
from .temporal import build_request_context, utc_now


@dataclass(frozen=True)
class PageRecommendTurn:
    """한 턴의 응답 + 다음 턴에 넘겨줄 대화상태(원본의 체크포인터 대체물)."""

    response: SearchResponse
    active_artifact: dict[str, Any] | None
    message_history: list[dict[str, str]]


class PageRecommendService:
    """레지스트리·LLM·메타데이터를 묶어 페이지추천 한 턴을 실행한다."""

    def __init__(
        self,
        *,
        registry: ServiceRegistry,
        llm: KomirJsonLLM,
        metadata_resolver: MetadataResolver | None = None,
        clock: Callable[[], datetime] = utc_now,
        timezone_name: str = "Asia/Seoul",
    ) -> None:
        self.registry = registry
        self.llm = llm
        self._clock = clock
        self._timezone_name = timezone_name
        self.workflow = SearchWorkflow(registry, llm, None, metadata_resolver=metadata_resolver)

    @classmethod
    def from_settings(cls) -> PageRecommendService:
        """services/shared/config.py의 통합 설정으로 서비스를 만든다."""

        settings = get_settings()
        return cls(
            registry=load_source_registry(),
            llm=KomirJsonLLM(),
            metadata_resolver=SnapshotMetadataResolver.from_path(),
            timezone_name=settings.KOMIS_TIMEZONE,
        )

    def recommend(
        self,
        question: str,
        *,
        thread_id: str,
        message_history: list[dict[str, str]] | None = None,
        active_artifact: dict[str, Any] | None = None,
    ) -> PageRecommendTurn:
        """한 턴 실행 — 직전 상태를 받아 응답과 다음 상태를 돌려준다."""

        state = self.workflow.graph.invoke(
            {
                "current_question": question,
                "request_context": build_request_context(self._clock(), self._timezone_name),
                "message_history": list(message_history or []),
                "active_artifact": active_artifact,
            }
        )
        return PageRecommendTurn(
            response=validate_response(thread_id, state),
            active_artifact=state.get("active_artifact"),
            message_history=state.get("message_history", []),
        )


_service: PageRecommendService | None = None


def get_service() -> PageRecommendService:
    """프로세스당 1회만 구성(레지스트리 YAML 43건 파싱을 매 요청마다 하지 않기 위함)."""

    global _service
    if _service is None:
        _service = PageRecommendService.from_settings()
    return _service
