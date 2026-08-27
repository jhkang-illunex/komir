"""데이터 관리 — RAG 코퍼스의 입력→정제→색인 단계별 문서 수량과 저장소 사용량.

집계 로직은 `documents/산출물/2026-W35_0824-0830/RAG문서코퍼스_데이터유형_수량_
public_private할당_260826.md`·`OKF_PageIndex_색인구조_저장소사용량_설명_260826.md`의
실측 방식을 그대로 화면화했다(OKF 프론트매터 스캔, PageIndex 트리 파일 수, Postgres
`doc_chunk` GROUP BY, 디스크/DB 저장소 크기) — 새 집계 규칙을 만들지 않았다.
public/private 판정은 `services/shared/retrieval/access.py::PRIVATE_ONLY_SOURCE_GROUPS`
단일 진리원을 그대로 재사용한다(하드코딩 금지).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
_SEMI = _INHOUSE_ROOT / "data_lake" / "semi_structure"
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

from shared.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS  # noqa: E402

# Streamlit이 view 파일을 __main__으로 실행해(exec) __name__ 기반 로거명이
# 전부 "__main__"으로 뭉개진다(실측 확인) — 이 파일에서만은 경로를 그대로 쓴다.
_log = logging.getLogger("streamlit_demo.views.data_admin")

st.title("데이터 관리")
st.caption("RAG 코퍼스의 입력 → 정제(OKF) → 색인(PageIndex·벡터) 단계별 문서 수량과 저장소 사용량입니다.")


@st.cache_data(ttl=300, show_spinner="OKF 문서 프론트매터를 스캔하는 중…")
def _scan_okf() -> pd.DataFrame:
    rows = []
    for path in _SEMI.glob("okf_documents/**/*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            front = yaml.safe_load(text.split("---", 2)[1])
        except (OSError, UnicodeDecodeError, yaml.YAMLError, IndexError):
            continue
        rows.append(
            {
                "source_group": front.get("source_group", "(미상)"),
                "fmt": (front.get("fmt") or "(미상)").lower(),
                "n_chars": front.get("n_chars") or 0,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner="PageIndex 트리 파일을 세는 중…")
def _scan_pageindex() -> pd.DataFrame:
    counts = Counter(
        path.relative_to(_SEMI / "pageindex_trees").parts[0]
        for path in _SEMI.glob("pageindex_trees/**/*.tree.json")
    )
    return pd.DataFrame(counts.items(), columns=["source_group", "trees"])


@st.cache_data(ttl=300, show_spinner="doc_chunk 테이블을 조회하는 중…")
def _doc_chunk_counts() -> pd.DataFrame | None:
    try:
        from shared.db import read_sql_pg

        return read_sql_pg(
            "SELECT src AS source_group, COUNT(*) AS chunks FROM mineral_risk.doc_chunk "
            "GROUP BY src ORDER BY chunks DESC"
        )
    except Exception as exc:  # noqa: BLE001 — Postgres 미접속 환경에서도 화면은 떠야 한다
        _log.exception("mineral_risk.doc_chunk 조회 실패")
        st.session_state["_doc_chunk_error"] = str(exc)
        return None


@st.cache_data(ttl=300, show_spinner="디스크 사용량을 확인하는 중…")
def _dir_size_bytes(relative: str) -> int | None:
    target = _SEMI / relative
    if not target.exists():
        return None
    try:
        out = subprocess.run(["du", "-sb", str(target)], capture_output=True, text=True, timeout=30, check=True)
        return int(out.stdout.split()[0])
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "확인 불가"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} PB"


okf = _scan_okf()
trees = _scan_pageindex()
chunks = _doc_chunk_counts()

# ── 단계별 퍼널 ──────────────────────────────────────────────────────────
st.subheader("단계별 문서 수량 퍼널")
st.caption("입력(원본 파일) → 정제(OKF 마크다운) → 색인(PageIndex 트리 · doc_chunk 청크)")

okf_total = len(okf)
tree_total = int(trees["trees"].sum()) if not trees.empty else 0
chunk_total = int(chunks["chunks"].sum()) if chunks is not None and not chunks.empty else None

cols = st.columns(3)
cols[0].metric("OKF 정제 문서", f"{okf_total:,}건")
cols[1].metric("PageIndex 트리", f"{tree_total:,}건", help="OKF 문서 1건당 트리 1개가 정상 — 어긋나면 결측")
cols[2].metric("doc_chunk 청크", f"{chunk_total:,}건" if chunk_total is not None else "DB 미접속")

if okf_total and tree_total and tree_total != okf_total:
    st.warning(f"OKF 문서 수({okf_total:,})와 PageIndex 트리 수({tree_total:,})가 다릅니다 — 결측 문서가 있을 수 있습니다.")

# ── 문서군 × 파일유형, public/private ───────────────────────────────────
st.subheader("문서군 × 파일유형 · public/private 할당")

if okf.empty:
    st.info("OKF 문서를 찾지 못했습니다.")
else:
    pivot = okf.pivot_table(index="source_group", columns="fmt", values="n_chars", aggfunc="count", fill_value=0)
    pivot["합계"] = pivot.sum(axis=1)
    pivot["접근범위"] = [
        "private 전용" if sg in PRIVATE_ONLY_SOURCE_GROUPS else "public + private"
        for sg in pivot.index
    ]
    pivot = pivot.sort_values("합계", ascending=False)
    st.dataframe(pivot, use_container_width=True)

    private_only_docs = int(okf[okf["source_group"].isin(PRIVATE_ONLY_SOURCE_GROUPS)].shape[0])
    alloc_cols = st.columns(2)
    alloc_cols[0].metric("private 전용 문서(public 검색 제외)", f"{private_only_docs:,}건")
    alloc_cols[1].metric("public + private 공통 문서", f"{okf_total - private_only_docs:,}건")

# ── doc_chunk 원천별 청크 수 ─────────────────────────────────────────────
if chunks is not None and not chunks.empty:
    st.subheader("doc_chunk 원천별 청크 수 (Postgres)")
    st.dataframe(chunks, use_container_width=True, hide_index=True)
elif st.session_state.get("_doc_chunk_error"):
    st.warning(f"doc_chunk 조회 실패 — Postgres 접속을 확인하세요. ({st.session_state['_doc_chunk_error'][:200]})")

# ── 저장소 사용량 ────────────────────────────────────────────────────────
st.subheader("저장소 사용량")
usage_cols = st.columns(2)
usage_cols[0].metric("OKF 문서 디스크 사용량", _fmt_bytes(_dir_size_bytes("okf_documents")))
usage_cols[1].metric("PageIndex 트리 디스크 사용량", _fmt_bytes(_dir_size_bytes("pageindex_trees")))
st.caption(f"측정 시각: {time.strftime('%Y-%m-%d %H:%M:%S')} · doc_chunk(pgvector) 테이블 용량은 Postgres 접속 시에만 표시됩니다.")
