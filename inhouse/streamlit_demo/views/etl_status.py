"""ETL 처리 현황 — 파이프라인 실행 이력과 파일별 단계 진행 상태.

`views/data_admin.py`(OKF/PageIndex/doc_chunk 문서 수량 퍼널·저장소 사용량, 정적
집계)와는 성격이 다르다 — 이 화면은 "지금 뭐가 어느 단계인지·최근 실행이 성공/
실패했는지"(동적/이력성 정보)를 보여준다.

데이터 계약은 ingest-agent가 정본(2026-08-27 세션 간 조율, komis_demo에 이미 적용
완료된 `ingest` 스키마):

    ingest.pipeline_run          잡 실행 1건 = 1행(run_id, job_name, stage, trigger,
                                  status, started_at, heartbeat_at, finished_at,
                                  args, metrics, error_message)
    ingest.pipeline_run_latest   job_name별 최신 1행 뷰
    ingest.source_file           원본 파일 1건 = 1행(file_id, file_name, source_group, ...)
    ingest.file_stage_status     (file_id, stage) 1건 = 1행, 재처리 시 upsert라 항상 최신

⚠ `get_settings().PG_SCHEMA`(mineral_risk 전용)를 쓰지 말 것 — 이 스키마명은
`ingest`로 쿼리 문자열에 직접 하드코딩한다(ingest-agent 지시, data_admin.py가
`mineral_risk.doc_chunk`를 하드코딩한 것과 같은 이유).

2026-08-27 시점: 스키마는 적용됐지만 파이프라인 배선 전이라 테이블은 0행 —
ingest-agent가 오늘 이어서 배선 중이므로 화면은 빈 상태를 정상 케이스로 다룬다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

from shared.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS  # noqa: E402,F401  (미사용, 접근범위 참고용으로 남김)

st.title("ETL 처리 현황")
st.caption("수집 → OKF 정제 → PageIndex 색인 → 벡터화 파이프라인의 실행 이력과 파일별 단계 진행 상태입니다.")

_STAGE_LABELS = {
    "extract": "추출",
    "okf": "OKF 정제",
    "pageindex": "PageIndex 색인",
    "vectorize": "벡터화",
}


@st.cache_data(ttl=30, show_spinner="파이프라인 실행 현황을 조회하는 중…")
def _pipeline_run_latest() -> pd.DataFrame | None:
    from shared.db import read_sql_pg

    return read_sql_pg(
        "SELECT job_name, stage, trigger, status, started_at, finished_at, metrics, error_message "
        "FROM ingest.pipeline_run_latest ORDER BY stage, job_name"
    )


@st.cache_data(ttl=15, show_spinner="실행 중인 잡을 확인하는 중…")
def _running_jobs() -> pd.DataFrame | None:
    from shared.db import read_sql_pg

    return read_sql_pg(
        "SELECT job_name, stage, trigger, started_at, heartbeat_at, "
        "now() - heartbeat_at AS heartbeat_age "
        "FROM ingest.pipeline_run WHERE status = 'running' ORDER BY started_at"
    )


@st.cache_data(ttl=30, show_spinner="최근 실행 이력을 조회하는 중…")
def _recent_runs(limit: int = 50) -> pd.DataFrame | None:
    from shared.db import read_sql_pg

    return read_sql_pg(
        "SELECT run_id, job_name, stage, trigger, status, started_at, finished_at, "
        "EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_sec, metrics, error_message "
        f"FROM ingest.pipeline_run ORDER BY started_at DESC LIMIT {int(limit)}"
    )


@st.cache_data(ttl=30, show_spinner="파일별 단계 진행 상태를 조회하는 중…")
def _file_stage_matrix() -> pd.DataFrame | None:
    from shared.db import read_sql_pg

    return read_sql_pg(
        "SELECT sf.file_id, sf.file_name, sf.source_group, sf.commodity_hint, "
        "MAX(CASE WHEN fss.stage='extract' THEN fss.status END) AS extract_status, "
        "MAX(CASE WHEN fss.stage='okf' THEN fss.status END) AS okf_status, "
        "MAX(CASE WHEN fss.stage='pageindex' THEN fss.status END) AS pageindex_status, "
        "MAX(CASE WHEN fss.stage='vectorize' THEN fss.status END) AS vectorize_status, "
        "MAX(CASE WHEN fss.stage='vectorize' THEN fss.chunk_count END) AS chunk_count "
        "FROM ingest.source_file sf LEFT JOIN ingest.file_stage_status fss USING (file_id) "
        "GROUP BY sf.file_id, sf.file_name, sf.source_group, sf.commodity_hint "
        "ORDER BY sf.source_group, sf.file_name"
    )


def _query(fn):
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 — Postgres 미접속 환경에서도 화면은 떠야 한다
        return None, str(exc)


latest, latest_err = _query(_pipeline_run_latest)
running, running_err = _query(_running_jobs)
recent, recent_err = _query(_recent_runs)
matrix, matrix_err = _query(_file_stage_matrix)

_db_error = latest_err or running_err or recent_err or matrix_err
if _db_error:
    st.warning(f"ingest 스키마 조회 실패 — Postgres(komis_demo) 접속을 확인하세요. ({_db_error[:200]})")

# ── 실행 중 + hung 의심 ──────────────────────────────────────────────────
if running is not None and not running.empty:
    st.subheader("지금 실행 중인 잡")
    display = running.copy()
    display["heartbeat_age_sec"] = display["heartbeat_age"].apply(
        lambda td: round(td.total_seconds()) if pd.notna(td) else None
    )
    hung = display[display["heartbeat_age_sec"].fillna(0) > 600]
    if not hung.empty:
        st.error(f"응답없음 의심 {len(hung)}건 — heartbeat_at 이 10분 이상 갱신되지 않았습니다.", icon=":material/warning:")
    st.dataframe(
        display[["job_name", "stage", "trigger", "started_at", "heartbeat_age_sec"]],
        use_container_width=True,
        hide_index=True,
    )

# ── 잡별 현재 상태 ────────────────────────────────────────────────────────
st.subheader("잡별 현재 상태")
if latest is None:
    pass
elif latest.empty:
    st.info("아직 실행 이력이 없습니다 — 파이프라인 배선 전(2026-08-27 기준 ingest-agent 작업 중)이라 정상입니다.", icon=":material/info:")
else:
    display = latest.copy()
    display["stage"] = display["stage"].map(_STAGE_LABELS).fillna(display["stage"])
    st.dataframe(
        display[["job_name", "stage", "trigger", "status", "started_at", "finished_at", "error_message"]],
        use_container_width=True,
        hide_index=True,
    )
    failed = display[display["status"] == "failed"]
    if not failed.empty:
        st.error(f"실패 상태인 잡 {len(failed)}건이 있습니다.", icon=":material/error:")

# ── 파일별 단계 매트릭스 ─────────────────────────────────────────────────
st.subheader("파일별 단계 진행 상태")
if matrix is None:
    pass
elif matrix.empty:
    st.info("아직 등록된 원본 파일이 없습니다.", icon=":material/info:")
else:
    source_groups = ["(전체)"] + sorted(matrix["source_group"].dropna().unique().tolist())
    picked = st.selectbox("문서군 필터", source_groups)
    filtered = matrix if picked == "(전체)" else matrix[matrix["source_group"] == picked]
    st.dataframe(
        filtered.rename(
            columns={
                "file_name": "파일명",
                "source_group": "문서군",
                "commodity_hint": "광종",
                "extract_status": "추출",
                "okf_status": "OKF 정제",
                "pageindex_status": "PageIndex 색인",
                "vectorize_status": "벡터화",
                "chunk_count": "청크 수",
            }
        ).drop(columns=["file_id"]),
        use_container_width=True,
        hide_index=True,
    )

# ── 최근 실행 이력 ────────────────────────────────────────────────────────
st.subheader("최근 실행 이력")
if recent is None:
    pass
elif recent.empty:
    st.info("최근 실행 이력이 없습니다.", icon=":material/info:")
else:
    display = recent.copy()
    display["stage"] = display["stage"].map(_STAGE_LABELS).fillna(display["stage"])
    st.dataframe(
        display[["run_id", "job_name", "stage", "trigger", "status", "started_at", "duration_sec", "error_message"]],
        use_container_width=True,
        hide_index=True,
    )
