"""엔진 버전 등록·실행 로그 — public.ai_rpt_engine_ver / public.ai_rpt_gen_run.

- ai_rpt_engine_ver: (engine_cd, ver) 1행. 날짜·sha·구성 파일·모델명. 파이프라인이
  시작할 때 현재 엔진 버전을 idempotent upsert한다.
- ai_rpt_gen_run: 보고서 행 1건을 어느 엔진·버전으로 언제 만들었는지, 몇 컬럼을
  채우고 몇 컬럼을 폐기했는지(사유 JSON), 근거 스냅샷 파일 경로. 이 로그가 있어야
  "이 문장은 어느 규칙/프롬프트/모델에서 나왔나"를 나중에 역추적할 수 있다.
두 테이블은 이 모듈이 소유하며 `ensure_tables()`가 없으면 만든다(IF NOT EXISTS).
"""
from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa

from .. import db
from .base import Engine

DDL = """
CREATE TABLE IF NOT EXISTS public.ai_rpt_engine_ver (
    engine_cd     varchar(20)  NOT NULL,
    ver           varchar(30)  NOT NULL,
    engine_type   varchar(10)  NOT NULL,
    ver_date      varchar(6)   NOT NULL,
    ver_sha       varchar(8)   NOT NULL,
    model_nm      varchar(100),
    src_files     text,
    frst_reg_dt   timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT pk_ai_rpt_engine_ver PRIMARY KEY (engine_cd, ver)
);
COMMENT ON TABLE  public.ai_rpt_engine_ver IS '통합보고서 생성 엔진 버전 등록부. ver=YYMMDD-sha8(엔진 구성 파일 내용 해시). ai_rpt_*.rule_ver/llm_model_ver가 이 ver를 참조';
COMMENT ON COLUMN public.ai_rpt_engine_ver.engine_cd   IS 'rule(규칙 엔진) | gen(생성형 엔진)';
COMMENT ON COLUMN public.ai_rpt_engine_ver.ver         IS 'YYMMDD-sha8';
COMMENT ON COLUMN public.ai_rpt_engine_ver.engine_type IS 'RULE | GEN';
COMMENT ON COLUMN public.ai_rpt_engine_ver.ver_date    IS '구성 파일 최종 수정일 YYMMDD';
COMMENT ON COLUMN public.ai_rpt_engine_ver.ver_sha     IS '구성 파일 내용 sha256 앞 8자리(+모델명)';
COMMENT ON COLUMN public.ai_rpt_engine_ver.model_nm    IS 'GEN 엔진의 LLM 모델명(RULE은 NULL)';
COMMENT ON COLUMN public.ai_rpt_engine_ver.src_files   IS '해시에 들어간 파일 목록(JSON 배열)';

CREATE TABLE IF NOT EXISTS public.ai_rpt_gen_run (
    run_sn        bigserial    PRIMARY KEY,
    base_ymd      varchar(8)   NOT NULL,
    tbl_nm        varchar(40)  NOT NULL,
    row_key       varchar(40)  NOT NULL,
    engine_cd     varchar(20)  NOT NULL,
    engine_ver    varchar(30)  NOT NULL,
    write_stts    varchar(20)  NOT NULL,
    cols_filled   integer      NOT NULL DEFAULT 0,
    cols_dropped  integer      NOT NULL DEFAULT 0,
    dropped_json  text,
    facts_path    varchar(300),
    started_dt    timestamp    NOT NULL,
    finished_dt   timestamp    NOT NULL DEFAULT now(),
    err_msg       text
);
CREATE INDEX IF NOT EXISTS ix_ai_rpt_gen_run_key ON public.ai_rpt_gen_run (base_ymd, tbl_nm, row_key);
COMMENT ON TABLE  public.ai_rpt_gen_run IS '통합보고서 행 생성 실행 로그. 행(tbl_nm,row_key,base_ymd)마다 엔진·버전·채움/폐기 컬럼 수·근거 파일';
COMMENT ON COLUMN public.ai_rpt_gen_run.row_key      IS 'ai_rpt_mnrl은 mnrknd_unq_cd, ai_rpt_overall은 base_ymd';
COMMENT ON COLUMN public.ai_rpt_gen_run.write_stts   IS 'inserted | updated | skipped(not DRAFT) | dry-run | error';
COMMENT ON COLUMN public.ai_rpt_gen_run.dropped_json IS 'GEN 엔진이 검증 실패로 폐기한 컬럼과 사유 {col: reason}';
"""


def ensure_tables() -> None:
    with db.engine().begin() as c:
        for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
            c.execute(sa.text(stmt))


def register(engine: Engine) -> str:
    v = engine.version
    db.execute(
        """INSERT INTO public.ai_rpt_engine_ver (engine_cd, ver, engine_type, ver_date, ver_sha, model_nm, src_files)
           VALUES (:cd, :ver, :ty, :d, :sha, :model, :files)
           ON CONFLICT (engine_cd, ver) DO UPDATE SET src_files=EXCLUDED.src_files, model_nm=EXCLUDED.model_nm""",
        {"cd": v.engine_cd, "ver": v.ver, "ty": engine.engine_type, "d": v.ver_date, "sha": v.sha,
         "model": engine.model_nm, "files": json.dumps(list(v.files), ensure_ascii=False)})
    return v.ver


def log_run(*, base_ymd: str, table: str, row_key: str, engine: Engine, write_stts: str,
            cols_filled: int, dropped: dict | None, facts_path: str | None, started: datetime,
            err: str | None = None) -> None:
    db.execute(
        """INSERT INTO public.ai_rpt_gen_run (base_ymd, tbl_nm, row_key, engine_cd, engine_ver, write_stts,
               cols_filled, cols_dropped, dropped_json, facts_path, started_dt, err_msg)
           VALUES (:b, :t, :k, :cd, :ver, :st, :nf, :nd, :dj, :fp, :sd, :err)""",
        {"b": base_ymd, "t": table, "k": row_key, "cd": engine.engine_cd, "ver": engine.version.ver,
         "st": write_stts, "nf": cols_filled, "nd": len(dropped or {}),
         "dj": json.dumps(dropped, ensure_ascii=False) if dropped else None,
         "fp": facts_path, "sd": started, "err": err})
