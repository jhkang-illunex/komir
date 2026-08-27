# -*- coding: utf-8 -*-
"""ingest 파이프라인 실행상태·파일별 처리현황 기록(`ingest` 스키마 전용, komis_demo).

`services/shared/db.py`는 건드리지 않는다(이미 검증된 공유 코드, CLAUDE.md §4) — 여기서는
`pg_connect()`만 가져다 쓰고 나머지(스키마 적용·INSERT/UPDATE)는 이 모듈이 직접 한다.

⚠ 스키마명 "ingest"는 여기 하드코딩한다 — `get_settings().PG_SCHEMA`("mineral_risk")를
쓰지 않는다(그 값은 doc_chunk 등 검색 테이블 전용, 이 모듈의 대상이 아니다).

**관측 실패가 파이프라인을 막지 않는다**: `pipeline_run()` 진입 시 스키마 적용/INSERT가
실패하면(예: Postgres 일시 다운) 경고만 찍고 `run.run_id=None`인 채로 그대로 진행한다 —
상태기록은 부가 관측이지 파이프라인 정합성의 일부가 아니다(extract 단계는 원래 Postgres
없이도 잘 돌던 코드였다). `upsert_source_file`/`upsert_file_stage_status`도 같은 이유로
DB 오류를 삼키고 경고만 남긴다. 단 `vectorize.*`는 원래도 PG_DSN 필수라 이 문제가 없다.

사용:
    from ingest import status as ingest_status

    def main():
        args = parser.parse_args()
        with ingest_status.pipeline_run("okf.build_okf_documents", args=vars(args)) as run:
            ...본문...
            run.metrics["written"] = len(written)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from services.shared.db import apply_schema_pg, pg_connect  # noqa: E402

INGEST_SCHEMA = "ingest"
SCHEMA_SQL = Path(__file__).resolve().parent / "db" / "schema_ingest.sql"
STAGES = ("extract", "okf", "pageindex", "vectorize")

_HEARTBEAT_SEC = 60
_STALE_MINUTES = 10

_schema_applied = False
_schema_lock = threading.Lock()


def ensure_schema() -> None:
    """`schema_ingest.sql`을 프로세스당 1회 멱등 적용."""

    global _schema_applied
    if _schema_applied:
        return
    with _schema_lock:
        if _schema_applied:
            return
        apply_schema_pg(str(SCHEMA_SQL))
        _schema_applied = True


def normalize_file_id(doc_id: str) -> str:
    """코드 전반의 doc_id 컨벤션(`removeprefix("doc_")[:16]`)으로 정규화 — OKF
    프론트매터의 `doc_id`(예: "doc_ab12cd34...")를 `ingest.source_file.file_id`와
    맞추는 용도(`ingest/vectorize/build_pgvector_okf.py::_load_okf_record`와 동일 규칙)."""

    return str(doc_id or "").removeprefix("doc_")[:16]


def parse_yymmdd_date(value: str | None):
    """`DocRecord.doc_date`(YYMMDD, 없으면 "") 컨벤션을 `datetime.date`로 — 코드
    전반이 각기 다른 날짜 문자열 포맷을 쓰므로(`YYMMDD`·`YYYY-MM-DD`·`YYYY-MM`)
    `upsert_source_file`은 `date` 객체만 받고, 포맷 변환은 호출부가 자기 컨텍스트에
    맞는 헬퍼로 한다 — 이 함수는 `YYMMDD`(2000년대 가정, `build_pgvector_index.py
    ::_pub_date`와 동일 규칙) 전용. `YYYY-MM-DD`/`YYYY-MM`은 `datetime.date.
    fromisoformat()`(필요시 `+"-01"`)로 호출부에서 직접 변환할 것."""

    import datetime as _dt

    if not value or len(value) != 6 or not value.isdigit():
        return None
    try:
        return _dt.date(2000 + int(value[:2]), int(value[2:4]), int(value[4:6]))
    except ValueError:
        return None


def parse_iso_date(value: str | None):
    """`"YYYY-MM-DD"`/`"YYYY-MM"` 문자열(`ingest_reports.py::infer_date`·
    `pdf_extract_restricted.py::_year_month` 등이 이미 이 형태로 반환)을
    `datetime.date`로. 파싱 실패 시 None(추정해 넣지 않는다 — 프로젝트 전반 원칙)."""

    import datetime as _dt

    if not value:
        return None
    v = value if len(value) > 7 else f"{value}-01"  # "YYYY-MM" → "YYYY-MM-01"
    try:
        return _dt.date.fromisoformat(v)
    except ValueError:
        return None


def _json(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def pg_connect_safe():
    """관측용 커넥션을 열되 실패하면 None을 돌려준다(예외를 삼킨다) — 파일 단위
    루프에서 커넥션 하나로 여러 `upsert_*` 호출을 묶고 싶을 때 이걸로 열고
    `con=`으로 넘기면 된다. None이면 각 `upsert_*`가 알아서 개별 연결로 폴백한다
    (con=None 분기, "관측 실패가 파이프라인을 막지 않는다" 원칙과 동일)."""

    try:
        return pg_connect()
    except Exception as e:  # noqa: BLE001
        print(f"[ingest.status] 커넥션 열기 실패(무시): {e}", file=sys.stderr)
        return None


def commit_close_safe(con) -> None:
    """`pg_connect_safe()`로 연 커넥션을 안전하게 commit+close(None이면 no-op)."""

    if con is None:
        return
    try:
        con.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[ingest.status] commit 실패(무시): {e}", file=sys.stderr)
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


class RunHandle:
    """`pipeline_run()`이 넘겨주는 컨텍스트 — `run.metrics`에 자유롭게 채우면
    정상 종료 시 그대로 저장된다. `run.run_id`가 None이면 상태기록이 비활성(DB
    접속 실패) 상태라는 뜻 — 호출부가 직접 참조할 일은 거의 없다(upsert 함수들이
    자동으로 이 값을 씀)."""

    def __init__(self, run_id: int | None):
        self.run_id = run_id
        self.metrics: dict = {}


_current_run: "RunHandle | None" = None


@contextmanager
def pipeline_run(job_name: str, *, args: dict | None = None, heartbeat: bool = True):
    """`with pipeline_run("okf.build_okf_documents", args=vars(args)) as run: ...`

    - stage는 `job_name`의 첫 세그먼트(`.` 기준)에서 유도, `STAGES`에 없으면 ValueError.
    - trigger는 `INGEST_TRIGGERED_BY` env var(cron 래퍼가 export)로만 판정 — 모듈마다
      다르게 배선하지 않는다.
    - 진입 시 같은 job_name의 고아 'running' 행(heartbeat_at이 10분 넘게 안 갱신됨)을
      'failed'로 자가치유(프로세스가 비정상 종료돼 UPDATE를 못 한 경우 대비).
    - 정상 종료: status='success', finished_at, metrics(run.metrics 그대로 JSONB).
    - 예외(SystemExit 포함): status='failed', error_message. SystemExit(0)/SystemExit(None)은
      success 취급(partial-완료를 나타내는 관례적 종료 코드, 예: ingest_reports.py의
      `sys.exit(3 if timed_out else 0)` — 이 모듈은 그 sys.exit을 with 블록 **밖**에
      두는 걸 전제한다, 그러면 여기선 아예 안 보임).
    """

    global _current_run
    stage = job_name.split(".", 1)[0]
    if stage not in STAGES:
        raise ValueError(f"job_name '{job_name}'의 stage '{stage}'가 STAGES{STAGES}에 없음")
    trigger = "cron" if os.environ.get("INGEST_TRIGGERED_BY") == "cron" else "manual"

    run_id = None
    try:
        ensure_schema()
        con = pg_connect()
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingest.pipeline_run SET status='failed',
                        finished_at=now(),
                        error_message='stale heartbeat — 프로세스 비정상 종료 추정'
                    WHERE job_name=%s AND status='running'
                        AND heartbeat_at < now() - interval '%s minutes'
                    """,
                    (job_name, _STALE_MINUTES),
                )
                cur.execute(
                    """
                    INSERT INTO ingest.pipeline_run (job_name, stage, trigger, args)
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING run_id
                    """,
                    (job_name, stage, trigger, _json(args)),
                )
                run_id = cur.fetchone()[0]
            con.commit()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — 관측 실패는 파이프라인을 막지 않는다
        print(f"[ingest.status] 실행상태 기록 시작 실패(무시하고 계속): {e}", file=sys.stderr)

    run = RunHandle(run_id)
    prev_run, _current_run = _current_run, run

    stop_heartbeat = threading.Event()
    hb_thread = None
    if run_id is not None and heartbeat:
        def _beat():
            while not stop_heartbeat.wait(_HEARTBEAT_SEC):
                try:
                    c = pg_connect()
                    try:
                        with c.cursor() as cur:
                            cur.execute(
                                "UPDATE ingest.pipeline_run SET heartbeat_at=now() WHERE run_id=%s",
                                (run_id,),
                            )
                        c.commit()
                    finally:
                        c.close()
                except Exception:  # noqa: BLE001 — heartbeat 실패는 무시
                    pass

        hb_thread = threading.Thread(target=_beat, daemon=True)
        hb_thread.start()

    status_val = "success"
    error_message = None
    try:
        yield run
    except SystemExit as e:
        code = e.code
        if code not in (0, None):
            status_val = "failed"
            error_message = f"SystemExit: {code}"
        raise
    except BaseException as e:
        status_val = "failed"
        error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}"
        raise
    finally:
        stop_heartbeat.set()
        if hb_thread is not None:
            hb_thread.join(timeout=2)
        _current_run = prev_run
        if run_id is not None:
            try:
                con = pg_connect()
                try:
                    with con.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE ingest.pipeline_run
                            SET status=%s, finished_at=now(), metrics=%s::jsonb,
                                error_message=%s
                            WHERE run_id=%s
                            """,
                            (status_val, _json(run.metrics), error_message, run_id),
                        )
                    con.commit()
                finally:
                    con.close()
            except Exception as e:  # noqa: BLE001
                print(f"[ingest.status] 실행상태 기록 종료 실패(무시): {e}", file=sys.stderr)


def upsert_source_file(
    file_id: str,
    *,
    file_name: str,
    file_ext: str,
    source_path: str,
    source_group: str | None = None,
    commodity_hint: str | None = None,
    doc_date=None,
    con=None,
) -> None:
    """`ingest.source_file` upsert. `con`을 넘기면 그 커넥션을 그대로 쓰고
    commit/close는 호출부 책임(루프에서 여러 건을 한 트랜잭션으로 묶을 때 사용) —
    `con=None`이면 이 함수가 직접 열고 커밋하고 닫는다."""

    sql = """
        INSERT INTO ingest.source_file
            (file_id, file_name, file_ext, source_path, source_group,
             commodity_hint, doc_date, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (file_id) DO UPDATE SET
            file_name=EXCLUDED.file_name, file_ext=EXCLUDED.file_ext,
            source_path=EXCLUDED.source_path, source_group=EXCLUDED.source_group,
            commodity_hint=EXCLUDED.commodity_hint, doc_date=EXCLUDED.doc_date,
            updated_at=now()
    """
    params = (
        file_id[:32],
        (file_name or "")[:255],
        (file_ext or "").lstrip(".")[:10],
        source_path or "",
        (source_group or None) and str(source_group)[:80],
        (commodity_hint or None) and str(commodity_hint)[:4],
        doc_date or None,
    )
    _exec(sql, params, con)


def upsert_file_stage_status(
    file_id: str,
    stage: str,
    status: str,
    *,
    run_id: int | None = None,
    n_chars: int | None = None,
    chunk_count: int | None = None,
    error_message: str | None = None,
    con=None,
) -> None:
    """`ingest.file_stage_status` upsert. `run_id=None`이면 `pipeline_run()`이
    현재 열어 둔 실행(`_current_run`)의 run_id를 자동으로 채운다."""

    if run_id is None and _current_run is not None:
        run_id = _current_run.run_id
    sql = """
        INSERT INTO ingest.file_stage_status
            (file_id, stage, status, run_id, n_chars, chunk_count, error_message, processed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (file_id, stage) DO UPDATE SET
            status=EXCLUDED.status, run_id=EXCLUDED.run_id, n_chars=EXCLUDED.n_chars,
            chunk_count=EXCLUDED.chunk_count, error_message=EXCLUDED.error_message,
            processed_at=now()
    """
    params = (file_id[:32], stage, status, run_id, n_chars, chunk_count,
              (error_message or None) and str(error_message)[:4000])
    _exec(sql, params, con)


def bulk_file_stage_status(rows: list[tuple], *, stage: str, con=None) -> None:
    """`(file_id, status, n_chars, chunk_count, error_message)` 튜플 리스트를
    한 번에 upsert(vectorize처럼 수천 건일 때용). `run_id`는 `_current_run`에서
    일괄 채운다."""

    if not rows:
        return
    run_id = _current_run.run_id if _current_run is not None else None
    from psycopg2.extras import execute_values

    def _do(c):
        with c.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO ingest.file_stage_status
                    (file_id, stage, status, run_id, n_chars, chunk_count, error_message, processed_at)
                VALUES %s
                ON CONFLICT (file_id, stage) DO UPDATE SET
                    status=EXCLUDED.status, run_id=EXCLUDED.run_id, n_chars=EXCLUDED.n_chars,
                    chunk_count=EXCLUDED.chunk_count, error_message=EXCLUDED.error_message,
                    processed_at=now()
                """,
                [(fid[:32], stage, st, run_id, nch, cc, (em or None) and str(em)[:4000])
                 for fid, st, nch, cc, em in rows],
                template="(%s,%s,%s,%s,%s,%s,%s,now())",
                page_size=200,
            )

    try:
        if con is not None:
            _do(con)
        else:
            c = pg_connect()
            try:
                _do(c)
                c.commit()
            finally:
                c.close()
    except Exception as e:  # noqa: BLE001 — 관측 실패는 무시
        print(f"[ingest.status] bulk_file_stage_status 실패(무시): {e}", file=sys.stderr)


def _exec(sql: str, params: tuple, con) -> None:
    try:
        if con is not None:
            with con.cursor() as cur:
                cur.execute(sql, params)
            return
        c = pg_connect()
        try:
            with c.cursor() as cur:
                cur.execute(sql, params)
            c.commit()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001 — 관측 실패는 무시(진짜 작업은 이미 끝났음)
        print(f"[ingest.status] 상태기록 실패(무시): {e}", file=sys.stderr)
