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

2026-08-27 시각화 보완(main-agent 사용자 피드백 경유): 표만 나열돼 있어
한눈에 안 들어온다는 지적에 상단 KPI 카드(st.metric)·단계별 진행바
(st.progress)·상태 아이콘화(이모지 매핑)·hung 임계치 근접 시 색상 강조
(pandas Styler)를 추가했다. requirements.txt에 plotly/altair 등 시각화
라이브러리가 없고 다른 화면도 안 쓰길래 신규 의존성 없이 스트림릿 내장
위젯만으로 구현했다(pandas는 이미 의존성)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Streamlit이 view 파일을 __main__으로 실행해(exec) __name__ 기반 로거명이
# 전부 "__main__"으로 뭉개진다(실측 확인, data_admin.py와 동일) — 경로를 그대로 쓴다.
_log = logging.getLogger("streamlit_demo.views.etl_status")

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

st.title("ETL 처리 현황")
st.caption("수집 → OKF 정제 → PageIndex 색인 → 벡터화 파이프라인의 실행 이력과 파일별 단계 진행 상태입니다.")

_STAGE_LABELS = {
    "extract": "추출",
    "okf": "OKF 정제",
    "pageindex": "PageIndex 색인",
    "vectorize": "벡터화",
}
_STAGE_STATUS_COLUMNS = ["extract_status", "okf_status", "pageindex_status", "vectorize_status"]

_STATUS_BADGES = {
    "success": "✅ 성공",
    "failed": "❌ 실패",
    "running": "🔄 실행중",
}


def _status_badge(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "⏳ 대기"
    return _STATUS_BADGES.get(str(value), str(value))


def _heartbeat_style(seconds) -> str:
    if seconds is None or (isinstance(seconds, float) and pd.isna(seconds)):
        return ""
    if seconds >= 600:  # hung 판정 임계치(10분)와 동일
        return "background-color: #ffcdd2; color: #b71c1c; font-weight: 600"
    if seconds >= 300:  # 절반 근접 — 주의
        return "background-color: #ffe0b2; color: #e65100; font-weight: 600"
    return "background-color: #c8e6c9; color: #1b5e20"


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
        _log.exception("ingest 스키마 조회 실패(%s)", getattr(fn, "__name__", fn))
        return None, str(exc)


latest, latest_err = _query(_pipeline_run_latest)
running, running_err = _query(_running_jobs)
recent, recent_err = _query(_recent_runs)
matrix, matrix_err = _query(_file_stage_matrix)

_db_error = latest_err or running_err or recent_err or matrix_err
if _db_error:
    st.warning(f"ingest 스키마 조회 실패 — Postgres(komis_demo) 접속을 확인하세요. ({_db_error[:200]})")

# ── 상단 KPI 카드 ─────────────────────────────────────────────────────────
running_count = 0 if running is None else len(running)
failed_count = 0 if latest is None or latest.empty else int((latest["status"] == "failed").sum())
total_files = 0 if matrix is None else len(matrix)
if matrix is not None and not matrix.empty:
    vectorized_count = int((matrix["vectorize_status"] == "success").sum())
    vectorized_pct = round(100 * vectorized_count / len(matrix), 1)
else:
    vectorized_count = 0
    vectorized_pct = None

kpi_cols = st.columns(4)
kpi_cols[0].metric("실행 중인 잡", f"{running_count}건")
kpi_cols[1].metric("실패한 잡", f"{failed_count}건")
kpi_cols[2].metric("전체 파일 수", f"{total_files:,}건")
kpi_cols[3].metric(
    "벡터화 완료율",
    f"{vectorized_pct}%" if vectorized_pct is not None else "—",
    help=f"{vectorized_count}/{total_files}건" if matrix is not None else None,
)

# ── 단계별 진행 바 ────────────────────────────────────────────────────────
if matrix is not None and not matrix.empty:
    st.caption("파이프라인 단계별 진행률 — 전체 파일 대비 그 단계까지 성공 처리된 비율")
    stage_cols = st.columns(len(_STAGE_STATUS_COLUMNS))
    total = len(matrix)
    for col, status_col, label in zip(stage_cols, _STAGE_STATUS_COLUMNS, _STAGE_LABELS.values(), strict=True):
        done = int((matrix[status_col] == "success").sum())
        col.progress(done / total if total else 0.0, text=f"{label}: {done}/{total}")

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
    table = display[["job_name", "stage", "trigger", "started_at", "heartbeat_age_sec"]]
    styled = table.style.map(_heartbeat_style, subset=["heartbeat_age_sec"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

# ── 잡별 현재 상태 ────────────────────────────────────────────────────────
st.subheader("잡별 현재 상태")
if latest is None:
    pass
elif latest.empty:
    st.info("아직 실행 이력이 없습니다 — 파이프라인 배선 전(2026-08-27 기준 ingest-agent 작업 중)이라 정상입니다.", icon=":material/info:")
else:
    display = latest.copy()
    failed = display[display["status"] == "failed"]
    display["stage"] = display["stage"].map(_STAGE_LABELS).fillna(display["stage"])
    display["status"] = display["status"].apply(_status_badge)
    st.dataframe(
        display[["job_name", "stage", "trigger", "status", "started_at", "finished_at", "error_message"]],
        use_container_width=True,
        hide_index=True,
    )
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
    filtered = filtered.copy()
    for status_col in _STAGE_STATUS_COLUMNS:
        filtered[status_col] = filtered[status_col].apply(_status_badge)
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
    display["status"] = display["status"].apply(_status_badge)
    st.dataframe(
        display[["run_id", "job_name", "stage", "trigger", "status", "started_at", "duration_sec", "error_message"]],
        use_container_width=True,
        hide_index=True,
    )
