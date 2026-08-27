# -*- coding: utf-8 -*-
"""서비스 공통 로깅 설정 — report_gen·rag_chat·commodity_api 3종이 공유(2026-08-28).

**배경**: 지금까지 어느 서비스의 `main.py`도 `logging.basicConfig()`를 부르지
않았다 — 각 모듈이 `logging.getLogger(__name__)`으로 로거만 만들고 루트 로거
설정(레벨·포맷·핸들러)은 아무도 안 했다. 파이썬 로깅은 루트에 핸들러가 없으면
`lastResort` 핸들러(WARNING 이상만, 포맷 없음)로 떨어지므로, 코드 곳곳의
`logger.info(...)` 호출(예: report_gen `main.py`의 프롬프트 로드 로그)이
실제로는 컨테이너 로그에 전혀 안 찍히고 있었을 가능성이 크다 — 로깅 인프라
자체가 조용히 절반만 동작하던 상태(사용자 지적: "LLM 경과 같은 부분은 로깅으로
기록"이 이 gap을 드러냄).

**사용**: 각 서비스 `main.py`가 앱 생성 이전(모듈 최상단, 다른 로깅 호출보다
먼저)에 한 번만 부른다:

    from shared.logging_config import configure_logging
    configure_logging()

uvicorn 자체 로거(`uvicorn`·`uvicorn.access`·`uvicorn.error`)는 uvicorn이 따로
설정하므로 이 함수는 건드리지 않는다 — 애플리케이션 로거(`app.*`·`rag.*` 등,
`__name__` 기반)만 대상이다. `logging.basicConfig()`는 루트 로거에 핸들러를
붙이는 방식이라 uvicorn 로거에도 포맷은 영향을 주지만(전파 구조상 자연스러움),
레벨을 강제로 바꾸진 않는다.

**레벨**: `LOG_LEVEL` 환경변수(기본 INFO) — 운영 중 DEBUG로 낮춰 재기동 없이
로그를 늘리고 싶을 때를 대비해 상수 하드코딩 대신 env로 뺐다."""
from __future__ import annotations

import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_configured = False


def configure_logging() -> None:
    """프로세스당 1회만 실제로 적용(멱등) — 서비스 재사용 모듈이 실수로 여러
    번 불러도 핸들러가 중복으로 쌓이지 않는다."""

    global _configured
    if _configured:
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=_DEFAULT_FORMAT)
    _configured = True
