# -*- coding: utf-8 -*-
"""FastAPI `/docs`·`/redoc`를 외부 CDN 없이 뜨게 한다(2026-09-03).

FastAPI 기본 `/docs`(Swagger UI)·`/redoc`은 HTML 안에 `cdn.jsdelivr.net`
(swagger-ui-dist·redoc)·`fonts.googleapis.com` 절대 URL을 박아 보낸다 —
서버(컨테이너)는 이 CDN에 닿아도, **브라우저가 사내망(airgap/inhouse)에서
그 CDN에 못 닿으면** `/docs` HTTP 응답 자체는 200이 오면서 화면만 텅 비거나
깨진다(실측: report_gen 컨테이너 자체는 jsdelivr 200으로 확인됐지만 사용자
브라우저에서 SSH 포트포워딩으로 열었을 때 재현). `swagger-ui-dist@5`·
`redoc@2` 정적 자산을 이 디렉터리(`static_docs/`)에 커밋해 두고, 그걸
로컬 `/static-docs/*`로 서빙 + `swagger_js_url`/`redoc_js_url` 등을 그
로컬 경로로 바꿔치기하면 브라우저는 이 서버 하나에만 접속하면 된다.

report_gen·rag_chat 둘 다 겪는 문제라(둘 다 FastAPI 기본 설정) 여기
`services/shared/`에 한 번만 구현하고 각 서비스는 등록만 한다."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

STATIC_DOCS_DIR = Path(__file__).resolve().parent / "static_docs"


def mount_offline_docs(app: FastAPI, *, title: str) -> None:
    """`app = FastAPI(..., docs_url=None, redoc_url=None)`로 기본 라우트를
    끈 뒤 호출한다 — 여기서 같은 경로(`/docs`·`/redoc`)를 로컬 자산으로
    다시 등록한다. `openapi_url`은 FastAPI 기본값(`/openapi.json`)을 그대로
    쓴다(이 두 서비스 다 커스텀 안 함)."""

    app.mount("/static-docs", StaticFiles(directory=STATIC_DOCS_DIR), name="static-docs")

    @app.get("/docs", include_in_schema=False)
    def swagger_ui_html() -> object:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{title} — Swagger UI",
            swagger_js_url="/static-docs/swagger-ui-bundle.js",
            swagger_css_url="/static-docs/swagger-ui.css",
            swagger_favicon_url="/static-docs/favicon.png",
        )

    @app.get("/redoc", include_in_schema=False)
    def redoc_html() -> object:
        return get_redoc_html(
            openapi_url=app.openapi_url,
            title=f"{title} — ReDoc",
            redoc_js_url="/static-docs/redoc.standalone.js",
            redoc_favicon_url="/static-docs/favicon.png",
        )
