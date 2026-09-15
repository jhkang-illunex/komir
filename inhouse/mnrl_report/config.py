"""설정·주차 계산·임계값.

DB 접속·LLM 설정은 `common.config.get_settings()`(inhouse/.env)를 그대로 쓴다.
이 모듈 고유 설정은 `MNRL_REPORT_*` 환경변수(없으면 기본값).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from common.config import get_settings

#: 등급 코드(ai_mnrl_diag.grade 체계) → 고시 별표6 4단계 표시명.
GRADE_NAMES = {"WATCH": "관심", "CAUTION": "주의", "WARNING": "경계", "CRITICAL": "심각"}
#: 표시명 순서(낮음→높음). 연속 주·이상징후 판정에 쓴다.
GRADE_ORDER = ["WATCH", "CAUTION", "WARNING", "CRITICAL"]
#: "수급 이상징후"로 보는 최소 등급(A5 ①: 관심은 모니터링, 주의 이상은 판단 검토).
ABNORMAL_MIN_GRADE = "CAUTION"

#: 개발 더미 표식 — ai_mnrl_diag/ai_dash_diag/ai_macro_indc/ai_news의 model_ver·src_nm.
DUMMY_MARK = "DEV_DUMMY"

#: 수급위기 진단 대상 5광종(고정, 사용자 확정 2026-09-15): 동·니켈·코발트·리튬·희토류.
#: 희토류는 대표원소 네오디뮴(MNRL1001)이다(사용자 확정 2026-09-15, 프로젝트 REE=Nd 결정과
#: 동일). 마스터의 '희토류'(MNRL0006) 행은 쓰지 않는다. 광종별 보고서(ai_rpt_mnrl)는 이 5행만.
TARGET_MINERALS = ("MNRL0008", "MNRL0002", "MNRL0003", "MNRL0001", "MNRL1001")


@dataclass(frozen=True)
class ReportConfig:
    """실행 시점 환경변수로 만든다(`get_config()`) — 클래스 기본값에 os.getenv를
    쓰면 import 시점 값이 고정돼 CLI(--minerals)가 나중에 넣은 env가 무시된다."""

    #: 수입국 HHI가 이 값 이상이면 "편중도가 높은 수준"(B9 import_struct_txt).
    #: 통상 기준(HHI 2,500 = 고집중). ai_threshold에 해당 키가 없어 여기서 관리한다.
    hhi_high: float
    #: 전체 평균 위기지수가 이 값 이상이면 "전반적으로 높은 위기 수준"(A2).
    overall_high: float
    #: 관세청 중량 컬럼(incm_weig) 단위가 kg인지(True면 톤=÷1000).
    customs_weight_kg: bool
    #: LLM 단계 활성 여부(기본 비활성 — 2026-09-13 "규칙 기반 기본값" 결정과 동일 취지).
    llm_enabled: bool
    #: 주간 스케줄(cron 5필드). 관세청·KOMIS 주간 파일이 월요일 오전에 갱신되는 것을
    #: 전제로 화요일 07:00 KST 기본.
    schedule_cron: str
    #: facts 스냅샷 저장 위치(감사·LLM 검증용). data_lake는 git 미추적.
    facts_dir: str
    #: 광종 선택 — 기본은 수급위기 진단 대상 5광종(TARGET_MINERALS, 사용자 확정 2026-09-15).
    #: MNRL_REPORT_MINERALS에 코드 목록을 주면 그 광종만, "all"이면 ai_mnrl_mst READY 전부.
    minerals_env: str

    @property
    def minerals(self) -> list[str] | None:
        env = self.minerals_env.strip()
        if env.lower() == "all":
            return None
        return [m.strip() for m in env.split(",") if m.strip()] or list(TARGET_MINERALS)


def get_config() -> ReportConfig:
    return ReportConfig(
        hhi_high=float(os.getenv("MNRL_REPORT_HHI_HIGH", "2500")),
        overall_high=float(os.getenv("MNRL_REPORT_OVERALL_HIGH", "60")),
        customs_weight_kg=os.getenv("MNRL_REPORT_CUSTOMS_WEIGHT_KG", "1") == "1",
        llm_enabled=os.getenv("MNRL_REPORT_LLM_ENABLED", "0") == "1",
        schedule_cron=os.getenv("MNRL_REPORT_SCHEDULE_CRON", "0 7 * * TUE"),
        facts_dir=os.getenv("MNRL_REPORT_FACTS_DIR",
                            os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_lake", "mnrl_report")),
        minerals_env=os.getenv("MNRL_REPORT_MINERALS", ""),
    )


def pg_dsn() -> str:
    s = get_settings()
    if not s.PG_DSN:
        raise RuntimeError("PG_DSN이 설정되지 않음 — inhouse/.env 확인")
    return s.PG_DSN.split("?")[0]


def latest_monday(today: date | None = None) -> date:
    """오늘 기준 가장 최근 월요일(오늘이 월요일이면 오늘). 보고 주차 키."""
    d = today or date.today()
    return d - timedelta(days=d.weekday())


def to_ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def from_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def week_meta(base: date) -> dict:
    """보고 주차 메타 — ISO 연도·주차, 기간(월~일)."""
    iso = base.isocalendar()
    return {
        "rpt_year": iso[0],
        "rpt_week_no": iso[1],
        "period_from_ymd": to_ymd(base),
        "period_to_ymd": to_ymd(base + timedelta(days=6)),
    }


def month_week_label(d: date) -> str:
    """양식의 "7월 1주차" 표기 — 그 달 몇 번째 월요일인지(1~5)."""
    n = (d.day - 1) // 7 + 1
    return f"{d.month}월 {n}주차"
