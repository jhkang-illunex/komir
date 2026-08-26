# -*- coding: utf-8 -*-
"""RAG 챗봇 API 엔트리 — POST /chat(user_id·session_id 필수) → retrieval/
unstructured.py+structured.py 병행 조회 → rag/ragkit/generate.py 인용강제 생성 →
streaming.py로 SSE 청크 전송 → session_store.py에 chat_message 적재.

2026-08-11(1차): structured.py(정형 템플릿 조회)를 매 턴 언제 부를지 동적으로 판단하는
로직(§5-4 "RAG 챗봇은 매 턴 LLM이 세 도구 중 무엇을 쓸지 동적으로 판단")은 아직
routers/chat.py에 안 붙어 있음 — 그 시점엔 비정형 문서검색 경로만 실제로 동작했다.

2026-08-11(2차): 페이지/필터 추천(komis-report-generator-main의 search/ LangGraph
그래프, 병합계획 결정①로 이 챗봇 기능 일부로 편입)을 app/page_recommend/로 이식하고
routers/chat.py에 배선했다 — 이제 두 경로(document|page)가 동작한다.

2026-08-13: structured.py가 chatbot_graph.py에 세 번째 도구로 배선 완료(위 문단의
"남은 것"은 그때 해소됨 — 이 문단만 갱신 안 돼 있던 stale 기록이었다).

2026-08-19: structured.py·chatbot_store.py 둘 다 데이터소스를 PostgreSQL(mineral_risk
스키마)로 전환 — 컨테이너에 로컬 DuckDB 파일을 마운트하지 않고도(§0 "DB는 외부서비스"
원칙) 정형조회·세션히스토리 전부 동작한다. `MSR_DB` 환경변수에 `PG_DSN`과 같은 값을
주면 된다(두 모듈 다 URL 타깃이면 자동으로 postgres 분기).

2026-08-26: startup에서 `rag.ragkit.mcp_client.start_all()`로 public/private MCP
서브프로세스 둘 다 미리 띄운다(요청마다 새로 띄우면 매 턴 수백ms~수초의 프로세스
기동 비용이 붙는다 — mcp_client.py 모듈독스트링의 "턴마다 재시작 안 함" 설계와
짝). shutdown에서 `stop_all()`로 정리. `chatbot_graph.py __main__`·smoke 테스트처럼
FastAPI 바깥에서 도는 경로는 `mcp_client`의 lazy-start(`ensure_started()`)로
이 lifespan 없이도 그대로 동작한다."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI


def _find_root(start: Path, marker: str) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / marker).is_file():
            return candidate
    raise ImportError(f"{marker}를 {start} 상위에서 찾지 못함")


_HERE = Path(__file__).resolve()
_RAG_ROOT = _find_root(_HERE, "rag/ragkit/mcp_client.py")
if str(_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(_RAG_ROOT))

from rag.ragkit import mcp_client  # noqa: E402

from .routers.chat import router as chat_router  # noqa: E402


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await asyncio.to_thread(mcp_client.start_all)
    try:
        yield
    finally:
        await asyncio.to_thread(mcp_client.stop_all)


app = FastAPI(title="komir rag_chat", lifespan=_lifespan)
app.include_router(chat_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
