# -*- coding: utf-8 -*-
"""주/월 정기 실행 체인(2026-07-12 완결) — 아키텍처 계약:
  수집기(외부 서버) → zip 번들 → [여기서부터]
  전처리기: geo ingest-bundles→extract(LLM) → publish --what events (geo_event→DB)
  지정학 추정기: geo index·prob (GEO_EVENT_SOURCE=db, DB에서 읽음) → publish --what index
  진단기(주): weekly_mart→nowcast→alert → DB
  수입 추정기(월): 관세청 증분(백필 보존)→ECOS→normalize→features→forecast_unit → DB
  발행: publish_results(외부 운영 DB, MSR_PUBLISH_DB 설정 시)

cron 예)
  0 6 * * 1   cd <komir>/mineral_supply_risk && python -m scripts.schedule weekly   >> /var/log/msr_weekly.log 2>&1
  0 7 1 * *   cd <komir>/mineral_supply_risk && python -m scripts.schedule monthly  >> /var/log/msr_monthly.log 2>&1
  0 8 1 1,4,7,10 * cd <komir>/mineral_supply_risk && python -m scripts.schedule quarterly >> /var/log/msr_quarterly.log 2>&1
  (LLM_PROVIDER 등 LLM_* env는 cron 환경에 주입할 것 — extract 단계에 필요.)

quarterly(D-5, 피드백기반_수정플랜 P3): 오버라이드 재검증 주기 — `scripts/override_backtest.py`
를 분기별 재실행해 트리거별(변동성·수입편중·지정학) 유지/임계조정/폐지 권고를 갱신한다.
현재 지정학 트리거는 2026-07-16 백테스트로 **폐지**(`ALERT_OVERRIDE_GEO=off`)됐지만, 데이터가
누적되면 재유효화될 수 있어 이 주기적 재검증이 유일한 안전망이다. 재유효화 판단 기준
(override_backtest.py의 `verdict()`에 이미 구현된 임계값, 이 함수는 그 결과만 파싱):
  - **유지**: 정당화비율(just_rate) ≥ 0.45 그리고 결과선행 lift ≥ 1.5
  - **임계 조정**: just_rate ≥ 0.3 또는 lift ≥ 1.3 (부분신호 — 임계 상향 검토)
  - **폐지 유지**: 위 조건 모두 미충족 또는 발화/격상 자체가 없음
자동으로 override_backtest.py의 판정을 재계산할 뿐, `alert.py`의 `ALERT_OVERRIDE_GEO` 스위치는
**절대 자동 변경하지 않는다** — 사람 검토 후 수동 반영이 원칙(운영 정책 변경은 자동화 대상 아님).
"""
import os, subprocess, sys
from datetime import date

_MSR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # mineral_supply_risk/
KOMIR = os.path.dirname(_MSR)                                         # komir 루트(geo 패키지 위치)
sys.path.insert(0, _MSR)
from msr import pipeline                                              # noqa: E402
from msr.config import DB_PATH                                        # noqa: E402


def _geo(*args, db_events: bool = False):
    """geo 서브커맨드를 komir 루트에서 서브프로세스로 실행(단계 격리).
    db_events=True면 추정기 모드 — 이벤트를 파일이 아닌 publish된 DB에서 읽는다."""
    env = dict(os.environ)
    env.setdefault("GEO_DATA", os.path.join(KOMIR, "geo_data"))
    env.setdefault("GEO_PUBLISH_DB", DB_PATH)     # 전처리기 적재처 = 추정기 읽기처 = warehouse
    # 양방향 명시: 조상 셸에 GEO_EVENT_SOURCE=db가 남아 있어도 전처리 단계가 DB를 읽지 않게.
    env["GEO_EVENT_SOURCE"] = "db" if db_events else "file"
    print(f"[schedule] geo {' '.join(args)}" + (" (이벤트 원천=DB)" if db_events else ""), flush=True)
    # timeout: LLM/DB 행이 걸리면 체인이 영원히 매달리는 것 방지(다음 주기 cron과 중첩 축적 방지)
    subprocess.run([sys.executable, "-m", "geo", *args], cwd=KOMIR, env=env, check=True,
                   timeout=int(os.environ.get("SCHEDULE_STAGE_TIMEOUT", 6 * 3600)))


def _publish_results():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import publish_results                        # MSR_PUBLISH_DB 미설정이면 스스로 생략
    publish_results.run()


def weekly():
    """주간: 번들 반입→전처리(DB 적재)→지정학 추정(DB 읽기)→수급위기 진단→경보→발행."""
    print(f"[schedule] === weekly 시작 === (warehouse: {DB_PATH}"
          f"{' — MSR_DB 미설정, 기본 경로 사용 중' if not os.environ.get('MSR_DB') else ''})", flush=True)
    # 전처리기 — 산출물을 DB에 넣는 데까지가 책임
    _geo("ingest-bundles")                        # 수집기 번들 전개(+ingest·gkg-parse 연쇄)
    _geo("extract")                               # LLM 이벤트 추출 → 파일 정본
    _geo("publish", "--what", "events")           # geo_event → DB
    # 지정학 이슈 추정기 — DB에서 읽어 주/월/년 지수·확률 산출
    _geo("index", db_events=True)
    _geo("prob", db_events=True)
    _geo("publish", "--what", "index")            # geo_index·geo_prob → DB
    # 수급위기 진단기 — DB에서 읽어 주 단위 진단·경보 → DB
    from msr.features import weekly_mart
    from msr.models import nowcast, alert
    weekly_mart.run()
    nowcast.run()
    alert.run()
    _publish_results()
    print("[schedule] === weekly 완료 ===", flush=True)


def monthly():
    """월간: 관세청 증분(백필 보존)·ECOS → 정규화·피처 → 12개월 수입량·금액 추정 → 발행."""
    print(f"[schedule] === monthly 시작 === (warehouse: {DB_PATH}"
          f"{' — MSR_DB 미설정, 기본 경로 사용 중' if not os.environ.get('MSR_DB') else ''})", flush=True)
    today = date.today()
    # 최근 24개월 재수집(관세청 소급 정정 반영) — collect_customs(전삭제형)를 쓰면
    # 2013~22 월간 백필이 유실되므로 반드시 보존형 증분을 쓴다.
    y, m0 = divmod(today.year * 12 + (today.month - 1) - 23, 12)
    pipeline.collect_customs_incremental(f"{y}{m0+1:02d}", f"{today.year}{today.month:02d}", freq="M")
    pipeline.collect_ecos()
    pipeline.normalize()
    pipeline.build_features()
    from msr.models import forecast_unit
    forecast_unit.run()                           # 12개월 톤·단가×톤(실지출액) → DB
    _publish_results()
    print("[schedule] === monthly 완료 ===", flush=True)


def quarterly():
    """분기: 오버라이드 백테스트 재실행 → 지정학 트리거 재유효화 여부 사람이 확인할 수 있게
    로그로 표시(D-5). `alert.py` 설정은 자동 변경하지 않음 — 검토용 신호만 남긴다."""
    print(f"[schedule] === quarterly 시작 === (warehouse: {DB_PATH}"
          f"{' — MSR_DB 미설정, 기본 경로 사용 중' if not os.environ.get('MSR_DB') else ''})", flush=True)
    subprocess.run([sys.executable, "-m", "scripts.override_backtest"], cwd=_MSR,
                   env=dict(os.environ), check=True,
                   timeout=int(os.environ.get("SCHEDULE_STAGE_TIMEOUT", 3600)))
    # 리포트에는 "③ 지정학 고신뢰"로 시작하는 표 행이 2곳(트리거별 개별 기여 표·판정·권고 표)
    # 있다 — 판정 표만 "| ③ 지정학 고신뢰 | **판정어** |" 형태로 두 번째 칸이 굵게(**) 표시되니
    # 그 패턴으로만 매칭해야 오탐(트리거 기여 표의 숫자 행 오매칭)을 피할 수 있다.
    report_path = os.path.join(_MSR, "outputs", "model_opt", "override_backtest.md")
    verdict_line = None
    try:
        with open(report_path) as f:
            for line in f:
                if line.startswith("| ③ 지정학") and "| **" in line:
                    verdict_line = line.strip()
                    break
    except FileNotFoundError:
        pass
    if verdict_line is None:
        print("[schedule] quarterly: 지정학 트리거 판정 라인을 찾지 못함 — 리포트 형식 변경 여부 확인 필요", flush=True)
    elif "**폐지**" in verdict_line:
        print(f"[schedule] quarterly: 지정학 오버라이드 여전히 폐지 권고(변경 없음) — {verdict_line}", flush=True)
    else:
        print(f"[schedule] quarterly: ⚠ 지정학 오버라이드 판정이 폐지 아님으로 변경됨 — "
              f"사람 검토 필요! {verdict_line}", flush=True)
    print("[schedule] === quarterly 완료 ===", flush=True)


if __name__ == "__main__":
    {"weekly": weekly, "monthly": monthly, "quarterly": quarterly}.get(
        sys.argv[1] if len(sys.argv) > 1 else "monthly", monthly)()
