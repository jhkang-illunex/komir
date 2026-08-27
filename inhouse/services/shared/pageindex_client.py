# -*- coding: utf-8 -*-
"""PageIndex(vendored) 진입점 — 이 모듈을 통해서만 pageindex_vendor/pageindex_lib를
써야 한다(pageindex_vendor/README.md "사용 규칙" 참고).

airgap 하드닝: pageindex_lib를 import하기 **전에** 반드시 아래 두 환경변수를
komir 설정값으로 강제 세팅한다(실측 검증: pageindex_vendor/README.md).
    OPENAI_BASE_URL=<komir LLM_BASE_URL>   — litellm/openai SDK가 이 값을 읽어
                                              로컬 vLLM으로 라우팅(외부 OpenAI 아님)
    LITELLM_LOCAL_MODEL_COST_MAP=True      — litellm의 원격 모델가격표 fetch 차단

문서-OKF(원문 전체 보존 마크다운)를 입력으로 트리를 만드는 용도로만 쓴다
(md_to_tree) — PDF 직접 입력(page_index, flash 모드)은 이번 범위 밖."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from services.shared.config import get_settings  # noqa: E402
from services.shared.logging_config import configure_logging  # noqa: E402

# 이 모듈이 komir 전체에서 PageIndex LLM 호출의 유일한 진입점이다(모듈 docstring
# "이 모듈을 통해서만" 참고) — 호출자(ingest/pageindex/build_pageindex_trees.py,
# pageindex_agent.py 등)가 configure_logging()을 안 불렀어도 여기서 한 번은
# 걸리게 한다(멱등이라 중복 호출 무해). vendored pageindex_lib/utils.py는 이미
# `logging.error(...)`로 연결오류·재시도 실패를 찍고 있었는데(실측: USGS 트리
# 생성 중 "ERROR:root:Error: Connection error" 다수 관측, 2026-08-11) 루트
# 로거에 핸들러가 없어 포맷 없는 lastResort로만 찍혔다 — configure_logging()
# 하나로 그 기존 로그도 같이 정상 포맷을 받는다.
configure_logging()
logger = logging.getLogger(__name__)


def _harden_env() -> None:
    """pageindex_lib를 import하기 전에 반드시 호출 — airgap 강제."""

    settings = get_settings()
    os.environ["OPENAI_BASE_URL"] = settings.LLM_BASE_URL
    os.environ.setdefault("OPENAI_API_KEY", settings.LLM_API_KEY or "local-vllm-no-key-required")
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


_harden_env()

_VENDOR_ROOT = Path(__file__).resolve().parent / "pageindex_vendor"
if str(_VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_VENDOR_ROOT))

from pageindex_lib.page_index_md import md_to_tree  # noqa: E402


def build_tree_from_markdown(
    md_path: str,
    *,
    model: str | None = None,
    with_summary: bool = True,
) -> dict:
    """문서-OKF 마크다운 1건 → PageIndex 트리(dict: doc_name/line_count/structure).

    model 생략 시 komir 설정의 LLM_MODEL(로컬 vLLM)을 쓴다. with_summary=True면
    노드별 LLM 요약을 생성(실제 LLM 호출 발생, 문서당 노드 수에 비례한 시간 소요)."""

    _harden_env()  # 프로세스 수명 중 설정이 바뀌었을 가능성 대비 매 호출 재확인
    resolved_model = model or get_settings().LLM_MODEL
    logger.info(
        "PageIndex 트리 생성 시작: %s (model=%s, summary=%s)", md_path, resolved_model, with_summary,
    )
    started = time.monotonic()
    try:
        tree = asyncio.run(
            md_to_tree(
                md_path,
                if_add_node_summary="yes" if with_summary else "no",
                # md_to_tree()의 summary_token_threshold 기본값(None)을 그대로 두면
                # get_node_summary() 내부에서 `num_tokens < None` 비교로 TypeError가
                # 난다(실측 확인, 2026-08-11) — run_pageindex.py CLI가 쓰는 기본값
                # (200)을 명시적으로 넘겨 원본 CLI와 동일하게 동작하게 한다.
                summary_token_threshold=200,
                model=resolved_model,
            )
        )
    except Exception:
        logger.error(
            "PageIndex 트리 생성 실패: %s (%.1f초 경과)", md_path, time.monotonic() - started,
            exc_info=True,
        )
        raise
    logger.info(
        "PageIndex 트리 생성 완료: %s (%.1f초, %d줄)",
        md_path, time.monotonic() - started, tree.get("line_count", 0),
    )
    return tree
