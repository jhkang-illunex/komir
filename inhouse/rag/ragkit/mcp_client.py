# -*- coding: utf-8 -*-
"""`mcp_server_public.py`·`mcp_server_private.py`(물리적으로 분리된 별도
모듈, 2026-08-26)를 stdio 서브프로세스로 띄우고 `chatbot_graph._retrieve_node`
(동기)가 쓸 수 있는 동기 래퍼를 제공한다. 어느 프로필을 쓸지는 **어느 모듈을
띄우느냐**로 정해진다 — 예전처럼 같은 서버에 `MCP_PROFILE` 환경변수를 얹어
분기하지 않는다(그 방식은 env 전달이 깨지면 조용히 다른 프로필처럼 동작할
여지가 있었다 — 자세한 배경은 `mcp_server_public.py` 모듈독스트링).

**턴마다 재시작하지 않는다** — 백그라운드 스레드 1개 위에서 도는 asyncio
이벤트루프 1개를 프로세스당 공유하고, 그 위에 `public`/`private` 두 개의
영속 `ClientSession`(각각 자기 서브프로세스)을 lazy singleton으로 연다.
sync↔async 브리지는 `asyncio.run_coroutine_threadsafe(...).result()` 하나뿐 —
그래프 쪽(`chatbot_graph.py`)은 안 건드린다(최소·외과적 변경).

**세션 열기·닫기는 반드시 같은 asyncio Task 안에서 일어난다**(2026-08-26,
skeptic-code SC-003 후속으로 실측 발견해 재설계). `stdio_client()`가 내부적으로
쓰는 anyio cancel scope는 "연 Task와 닫는 Task가 같아야 한다"는 구조적 동시성
제약이 있다 — 예전엔 `_start_async()`(여는 코루틴)와 `stack.aclose()`(닫는
코루틴)를 `run_coroutine_threadsafe`로 각각 별도 Task로 스케줄해서, `stop()`
호출마다 `RuntimeError: Attempted to exit cancel scope in a different task
than it was entered in`이 났다(그동안 `except Exception: pass`가 완전히
조용히 삼켜서 안 드러났을 뿐 — 실제 요청 서빙엔 영향 없었지만 서브프로세스가
깔끔하게 안 닫혔다). 지금은 `_run_session()` 코루틴 하나가 열기→대기→닫기를
전부 담당하는 하나의 장수 Task이고, `stop()`은 `asyncio.Event`를 스레드 안전
(`loop.call_soon_threadsafe`)하게 set만 해서 그 Task 스스로 같은 Task 안에서
정리하게 신호를 보낸다.

MCP 도구 반환값은 FastMCP의 `structuredContent`로 받는다(**`content` 블록이
아니다** — 리스트를 반환하는 도구는 `content`가 원소별로 쪼개진 여러 TextContent
로 나뉘어 첫 블록만 읽으면 첫 원소만 보인다는 걸 실측으로 확인, 2026-08-26).
`mcp_server_public.py`/`mcp_server_private.py`의 모든 tool이 top-level에서
항상 `dict[str, Any]`(Optional도 list도 아닌 순수 object)를 반환하도록
통일해뒀으므로 `structuredContent`를 그대로(추가 언랩 없이) 쓰면 된다 —
실측 확인: FastMCP는 반환 타입이 이미 object 스키마면 그 dict를 그대로
싣지만, `dict | None`/`list[...]`처럼 top-level이 object가 아니면
`{"result": ...}`로 감싼다 — 도구마다 다른 언랩 로직을 두지 않으려고 서버
쪽 반환 타입을 맞췄다. 실패는 `CallToolResult.isError`로 판정해 그대로
예외를 올린다 — `chatbot_graph._retrieve_node`의 기존 `try/except Exception
... warnings.append(f"{name}_failed")`가 이미 도구별 실패를 부분열화로
흡수하므로 여기서 또 삼키지 않는다.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from shared.retrieval.evidence import Evidence  # noqa: E402

_logger = logging.getLogger(__name__)

#: `inhouse/rag/ragkit/mcp_client.py` -> ragkit -> rag -> inhouse. `python -m
#: rag.ragkit.mcp_server_{public,private}`는 이 디렉토리를 cwd로 해야 `rag`
#: 패키지가 보인다(CLAUDE.md §2의 "python -m geo는 부모에서" 함정과 같은 원리).
_INHOUSE_ROOT = Path(__file__).resolve().parents[2]

#: 프로필 -> 실행할 모듈. 물리적 분리의 핵심 — 접근범위는 여기서 "어느 파일을
#: 띄울지"로만 정해지고, 그 아래로는 어떤 옵션도 전달하지 않는다.
_MODULE_BY_PROFILE: dict[str, str] = {
    "public": "rag.ragkit.mcp_server_public",
    "private": "rag.ragkit.mcp_server_private",
}

_START_TIMEOUT = 30.0
_CALL_TIMEOUT = 90.0  # pageindex_agentic이 최대 MAX_AGENT_STEPS(5)회 LLM 왕복 — 여유 있게


def _loop_worker(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_loop_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """프로세스당 백그라운드 이벤트루프 1개(lazy singleton) — public/private
    두 세션이 이 루프 하나를 공유한다(세션마다 스레드를 새로 만들지 않음)."""

    global _loop
    with _loop_lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=_loop_worker, args=(loop,), daemon=True, name="mcp-client-loop").start()
            _loop = loop
    return _loop


class McpToolError(RuntimeError):
    """MCP tool 호출이 `isError=True`로 돌아왔을 때."""


class _ProfileSession:
    """public/private 중 한 프로필의 영속 MCP 세션 — 서브프로세스 1개,
    `ClientSession` 1개를 재사용한다(호출마다 새로 안 띄움).

    세션의 열기→대기→닫기는 `_run_session()` 코루틴 하나가 **하나의 asyncio
    Task**로 전 생애주기를 담당한다(2026-08-26 재설계, 모듈독스트링 참고) —
    `ensure_started()`는 그 Task를 백그라운드로 띄우고 "열렸다" 신호
    (`concurrent.futures.Future`, 스레드 안전)만 기다리고, `stop()`은 "닫아라"
    신호(`asyncio.Event`, `loop.call_soon_threadsafe`로 스레드 안전하게 set)만
    보낸 뒤 그 Task가 실제로 끝나길 기다린다 — enter/exit가 항상 같은 Task
    안에서 일어나므로 anyio cancel scope의 task 소속 제약을 위반하지 않는다."""

    def __init__(self, profile: Literal["public", "private"]) -> None:
        self.profile = profile
        self._session: ClientSession | None = None
        self._close_event: asyncio.Event | None = None
        self._run_future: concurrent.futures.Future | None = None
        self._start_lock = threading.Lock()

    def ensure_started(self, *, timeout: float = _START_TIMEOUT) -> None:
        if self._session is not None:
            return
        with self._start_lock:
            if self._session is not None:
                return
            loop = _ensure_loop()
            started: concurrent.futures.Future = concurrent.futures.Future()
            run_fut = asyncio.run_coroutine_threadsafe(self._run_session(started), loop)
            try:
                started.result(timeout=timeout)
            except Exception:
                # `.result(timeout=...)`는 대기 스레드만 풀어줄 뿐 루프 위 코루틴은
                # 취소하지 않는다(asyncio 표준 동작) — 그대로 두면 서브프로세스가
                # 백그라운드에서 계속 기동을 시도하다 뒤늦게 self._session을 채워,
                # 다음 ensure_started() 호출이 "아직 None"으로 보고 두 번째
                # 서브프로세스를 또 띄우는 경합이 생긴다. run_fut.cancel()로 루프
                # 쪽 Task에 취소 신호를 보내 정리한다(2026-08-26 skeptic-code SC-001,
                # `_run_session`이 장수 Task로 바뀐 뒤에도 같은 이유로 그대로 유지).
                run_fut.cancel()
                raise
            self._run_future = run_fut

    async def _run_session(self, started: concurrent.futures.Future) -> None:
        """열기→(close_event까지) 대기→닫기 전부를 담당하는 단일 Task.

        `stdio_client()`/`ClientSession`을 여기서 열고 여기서만 닫는다 — 다른
        Task(`stop()`이 예전에 스케줄하던 별도 코루틴 등)가 이 스택을 대신
        닫으려 하면 anyio cancel scope가 `RuntimeError: Attempted to exit
        cancel scope in a different task than it was entered in`을 던진다
        (2026-08-26 실측 발견, 재설계 계기 — 모듈독스트링 참고)."""

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", _MODULE_BY_PROFILE[self.profile]],
            cwd=str(_INHOUSE_ROOT),
            env=dict(os.environ),  # 프로필별 옵션 없음 — 어느 모듈을 띄우는지가 전부
        )
        close_event = asyncio.Event()
        self._close_event = close_event
        session: ClientSession | None = None
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._session = session
                if not started.done():
                    started.set_result(None)
                await close_event.wait()
        except Exception as exc:
            if not started.done():
                started.set_exception(exc)
            else:
                _logger.warning("%s 세션 실행 중 오류(무시)", self.profile, exc_info=True)
        finally:
            # 내가 만든 객체일 때만 지운다(2026-08-27 skeptic-code 2차 SC-002, 실측
            # 재현): _call_async가 실패 복구(SC-002 1차)로 self._session을 비우고
            # close_event를 set한 뒤, 이 Task가 subprocess 종료를 await하는 동안
            # 새 요청이 후임 _run_session을 띄워 self._session/_close_event를 새
            # 값으로 채울 수 있다 — 여기서 무조건 None으로 덮으면 후임 세션의
            # close_event가 사라져 stop()이 조기 반환하고 새 서브프로세스가
            # 영원히 안 닫힌다(좀비). identity 비교로 후임 것은 건드리지 않는다.
            if self._session is session:
                self._session = None
            if self._close_event is close_event:
                self._close_event = None

    def stop(self, *, timeout: float = 10.0) -> None:
        run_fut = self._run_future
        close_event = self._close_event
        if run_fut is None or close_event is None:
            return
        self._run_future = None
        loop = _ensure_loop()
        loop.call_soon_threadsafe(close_event.set)
        try:
            # _run_session이 close_event를 받은 뒤 같은 Task 안에서 스택을 닫고
            # 끝날 때까지 기다린다 — 여기서 새 Task로 stack.aclose()를 또 스케줄
            # 하지 않는다(그게 바로 원래 버그였다).
            run_fut.result(timeout=timeout)
        except Exception:
            # 종료 경로 실패는 턴 처리를 막지 않는다(프로세스는 어차피 곧 죽음)
            # — 그래도 좀비 서브프로세스가 쌓이는 신호는 남겨야 운영 중 알아챌
            # 수 있다(2026-08-26 skeptic-code SC-003, 완전 무음 대신 로그).
            _logger.warning("%s 세션 종료 중 오류(무시)", self.profile, exc_info=True)

    def _call(self, tool: str, arguments: dict[str, Any], *, timeout: float = _CALL_TIMEOUT) -> Any:
        self.ensure_started()
        loop = _ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(self._call_async(tool, arguments), loop)
        try:
            return fut.result(timeout=timeout)
        except Exception:
            # ensure_started()와 같은 이유(SC-001) — timeout이 호출 스레드만
            # 풀어주고 루프 위 호출은 안 멈추므로 명시적으로 취소 신호를 보낸다.
            fut.cancel()
            raise

    async def _call_async(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._session is not None
        try:
            result = await self._session.call_tool(tool, arguments=arguments)
        except Exception:
            # 서브프로세스가 죽었거나 파이프가 끊겼을 수 있다 — 세션을 살아있다고
            # 오판하면 이 프로필(public/private)이 프로세스 재시작 전까지 영구히
            # 복구 불가능해진다(2026-08-26 skeptic-code SC-002). self._session을
            # 비워 다음 ensure_started()가 새 서브프로세스를 띄우게 하고, 지금
            # 죽어가는 _run_session Task에도 close_event로 정리 신호를 보낸다
            # (안 보내면 그 Task가 close_event.wait()에 계속 걸린 채 좀비로
            # 남는다 — 이 코루틴 자신이 이미 같은 루프 위에서 돌고 있으므로
            # close_event.set()을 직접 불러도 안전하다, 다른 Task의 스택을
            # 대신 닫는 게 아니라 신호만 보내는 것이라 cancel scope 제약과 무관).
            self._session = None
            if self._close_event is not None:
                self._close_event.set()
            raise
        if result.isError:
            detail = result.content[0].text if result.content else "unknown error"
            raise McpToolError(f"mcp tool {tool!r}({self.profile}) failed: {detail}")
        return result.structuredContent  # 서버가 이미 순수 object로 반환 — 언랩 불필요

    # ---- chatbot_graph._retrieve_node가 쓰는 타입 있는 래퍼 6종 + komis_raw_lookup 1종(2026-08-31 추가, 그래프 자동 라우팅은 아직 미배선 — 호출 자체는 이 래퍼로 가능) ----

    def call_latest_diagnosis(self, commodity_code: str, target: str | None = None, months: int | None = None) -> Evidence | None:
        data = self._call("latest_diagnosis", {"commodity_code": commodity_code})["evidence"]
        return Evidence(**data) if data else None

    def call_import_forecast(self, commodity_code: str, target: str | None = None, months: int | None = None) -> Evidence | None:
        data = self._call(
            "import_forecast",
            {"commodity_code": commodity_code, "target": target or "volume", "horizon": months},
        )["evidence"]
        return Evidence(**data) if data else None

    def call_geo_index_trend(self, commodity_code: str, target: str | None = None, months: int | None = None, limit: int = 8) -> Evidence | None:
        data = self._call("geo_index_trend", {"commodity_code": commodity_code, "limit": limit})["evidence"]
        return Evidence(**data) if data else None

    def call_hybrid_search(self, query: str, k: int) -> list[Evidence]:
        data = self._call("hybrid_search", {"query": query, "k": k})["evidence"]
        return [Evidence(**d) for d in data]

    def call_pageindex_lookup(self, query: str, *, node_limit: int, with_text: bool = True) -> list[Evidence]:
        data = self._call("pageindex_lookup", {"query": query, "node_limit": node_limit, "with_text": with_text})
        return [Evidence(**d) for d in data["nodes"]]

    def call_pageindex_agentic(
        self, query: str, *, history: list[dict[str, str]] | None = None
    ) -> tuple[list[Evidence], list[str]]:
        data = self._call("pageindex_agentic", {"query": query, "history": history or []})
        return [Evidence(**d) for d in data["evidence"]], data["warnings"]

    def call_komis_raw_lookup(
        self,
        page_id: str,
        *,
        mineral_code: str | None = None,
        mineral_label: str | None = None,
        hs_code: str | None = None,
        index_type_code: str | None = None,
        price_criterion_serial: int | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        limit: int = 5,
    ) -> tuple[list[Evidence], list[str]]:
        """KOMIS 공개원천(public.KO_*) 원자료 조회 — 2026-08-31 추가. warnings에
        더미데이터 경고(§_mcp_tools_common.py::komis_raw_lookup)가 실릴 수 있다.
        `mineral_label`(2026-09-01 추가)은 근거 표시용 한글 광종명 — 안 주면
        근거 section에 `mineral_code`(MNRL0018 등)가 그대로 노출돼 verify/생성
        LLM이 광종을 못 알아볼 수 있다(실측 버그, 위 tool 독스트링 참고)."""

        data = self._call(
            "komis_raw_lookup",
            {
                "page_id": page_id, "mineral_code": mineral_code, "mineral_label": mineral_label,
                "hs_code": hs_code, "index_type_code": index_type_code,
                "price_criterion_serial": price_criterion_serial,
                "start_period": start_period, "end_period": end_period, "limit": limit,
            },
        )
        return [Evidence(**d) for d in data["evidence"]], data["warnings"]

    def call_komis_resolve_mineral(self, korean_name: str) -> dict[str, Any]:
        """한글 광종명 -> {mineral_code, price_category, warnings} — 2026-09-01
        추가. `call_komis_raw_lookup`에 넘길 `mineral_code`를 구하는 선행 호출로
        쓴다(chatbot_graph.py 참고, 하드코딩 딕셔너리 대신 ai_mnrl_mst 실조회)."""

        return self._call("komis_resolve_mineral", {"korean_name": korean_name})


public = _ProfileSession("public")
private = _ProfileSession("private")


def start_all(*, timeout: float = _START_TIMEOUT) -> None:
    public.ensure_started(timeout=timeout)
    private.ensure_started(timeout=timeout)


def stop_all(*, timeout: float = 10.0) -> None:
    public.stop(timeout=timeout)
    private.stop(timeout=timeout)
