# -*- coding: utf-8 -*-
"""챗봇 전용 Langfuse 관측 헬퍼.

Langfuse 장애나 미설정 상태가 챗봇 응답 경로를 막지 않도록 모든 SDK 경계를
부분 열화한다. 실제 관측은 ``chat_trace`` 문맥 안에서만 활성화되므로 같은 공용
LLM 클라이언트를 쓰는 report_gen/ingest 호출은 자동으로 수집하지 않는다.
"""
from __future__ import annotations

import logging
import os
import threading
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

try:
    from langfuse import Langfuse, propagate_attributes
except ImportError:  # 로컬 단위테스트는 컨테이너 의존성을 설치하지 않을 수 있다.
    Langfuse = None  # type: ignore[assignment,misc]
    propagate_attributes = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)
_client: Any | None = None
_client_initialized = False
_client_lock = threading.Lock()
_chat_trace_active: ContextVar[bool] = ContextVar("langfuse_chat_trace_active", default=False)


def _get_client() -> Any | None:
    """환경변수가 모두 있을 때만 프로세스 단일 Langfuse 클라이언트를 만든다."""

    global _client, _client_initialized
    if _client_initialized:
        return _client
    with _client_lock:
        if _client_initialized:
            return _client
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        base_url = (os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "").strip()
        if Langfuse is None or not (public_key and secret_key and base_url):
            _client_initialized = True
            return None
        try:
            _client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=base_url,
            )
        except Exception:  # 관측 초기화 실패는 서비스 실패로 전파하지 않는다.
            _logger.exception("Langfuse 클라이언트 초기화 실패; 관측 없이 계속합니다")
            _client = None
        _client_initialized = True
        return _client


@contextmanager
def _observation(**kwargs: Any) -> Iterator[Any | None]:
    """SDK context manager의 시작·종료 오류만 흡수하고 업무 예외는 보존한다."""

    client = _get_client()
    if client is None:
        yield None
        return
    try:
        manager = client.start_as_current_observation(**kwargs)
        observation = manager.__enter__()
    except Exception:
        _logger.exception("Langfuse observation 시작 실패; 관측 없이 계속합니다")
        yield None
        return
    try:
        yield observation
    except BaseException as exc:
        try:
            observation.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}"[:500])
        except Exception:
            _logger.warning("Langfuse 오류 상태 기록 실패", exc_info=True)
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            _logger.warning("Langfuse observation 오류 종료 실패", exc_info=True)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            _logger.warning("Langfuse observation 종료 실패", exc_info=True)


@contextmanager
def chat_trace(*, user_id: str, session_id: str, message: str, profile: str) -> Iterator[Any | None]:
    """챗봇 한 턴을 root span으로 만들고 user/session 속성을 하위 호출에 전파한다."""

    # trace 속성은 root observation을 시작하기 전에 현재 context에 있어야 한다.
    # 또한 SDK context manager 자체의 장애가 챗봇 응답을 막지 않아야 한다.
    attributes_manager = None
    if propagate_attributes is not None and _get_client() is not None:
        try:
            attributes_manager = propagate_attributes(
                trace_name="rag-chat.turn",
                user_id=user_id,
                session_id=session_id,
                tags=["rag-chat", profile],
                metadata={"profile": profile},
            )
            attributes_manager.__enter__()
        except Exception:
            _logger.exception("Langfuse trace 속성 전파 시작 실패; 관측 없이 계속합니다")
            attributes_manager = None
    try:
        with _observation(
            as_type="chain",
            name="rag-chat.turn",
            input={"message": message, "profile": profile},
            metadata={"service": "rag_chat"},
        ) as span:
            if span is None:
                yield None
                return
            token = _chat_trace_active.set(True)
            try:
                yield span
            finally:
                _chat_trace_active.reset(token)
    except BaseException:
        if attributes_manager is not None:
            try:
                attributes_manager.__exit__(*sys.exc_info())
            except Exception:
                _logger.warning("Langfuse trace 속성 전파 오류 종료 실패", exc_info=True)
        raise
    else:
        if attributes_manager is not None:
            try:
                attributes_manager.__exit__(None, None, None)
            except Exception:
                _logger.warning("Langfuse trace 속성 전파 종료 실패", exc_info=True)


@contextmanager
def llm_generation(
    *, name: str, model: str, system: str, user: str, max_tokens: int,
    temperature: float, stream: bool,
) -> Iterator[Any | None]:
    """활성 챗봇 trace 아래에 OpenAI 호환 LLM 호출 generation을 기록한다."""

    if not _chat_trace_active.get():
        yield None
        return
    with _observation(
        as_type="generation",
        name=name,
        model=model,
        input={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        },
        model_parameters={
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        },
    ) as generation:
        yield generation


def update_observation(observation: Any | None, **kwargs: Any) -> None:
    """관측 업데이트 실패를 업무 경로에서 분리한다."""

    if observation is None:
        return
    try:
        observation.update(**kwargs)
    except Exception:
        _logger.warning("Langfuse observation 업데이트 실패", exc_info=True)
