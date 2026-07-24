# -*- coding: utf-8 -*-
"""거래소 재고 수집기 — 공개 API 총동원 결과물 (2026-07-24, 사용자 지시
"CO 재고 LME 수집기 개발+검증, 공개 데이터 다 동원, 내용 문서화·트래킹").

## 소스 정찰 결과(전 시도 기록 — outputs/model_opt/co_inventory_recon.md 상세)
- **CO(코발트): 무료 자동수집 경로 없음 확정.** 코발트 선물·창고재고는 전 세계에서
  LME에만 존재하는데 ① lme.com은 WAF 봇차단(브라우저 UA·WebFetch 모두 403),
  ② 무료 공개분은 당해연도뿐(과거 히스토리 유료, 연 $1,200), ③ Wayback에 데이터파일
  미아카이브(페이지 스냅샷 연 3~4회뿐+JS렌더), ④ 무료 미러(westmetall·eastmoney·
  99qh 등)는 유동성 있는 6대 비철만 취급(코발트 없음), ⑤ 중국 거래소엔 코발트 선물
  자체가 미상장, ⑥ 사내 보고서 코퍼스·KOMIS 원본 파일에도 코발트 재고 없음.
  → 확보하려면 LME 데이터라이선스 구매 또는 발주처(KOMIS는 LME 데이터 보유) 경유
  제공 요청이 필요 — 발주처 안건으로 이관.
- **NI(니켈): SHFE 주간 재고 확보** — 99期货(fx168 centerapi, akshare 경유) 주간
  스냅샷 2015-04~현재. LME 재고(KOMIS 파일)와 별개의 중국 내 실물 재고 축.
- **LI(리튬): GFEX 탄산리튬 창고재고(창단) 확보** — 광저우선물거래소 공식 공개
  API(akshare 경유), 상장일 2023-07-21~현재. LI 최초의 재고 시계열.

## 적재 규약
fact_inventory_exch(commodity_code, obs_date, val, unit, src — PK에 src 포함)에 적재(멱등).
※ fact_inventory는 PK가 (commodity_code, obs_date)라 광종당 1소스만 담을 수 있어
  (NI: LME행과 SHFE행이 같은 날짜에서 PK 충돌 — 1차 실행에서 실측), 다소스 공존용
  전용 테이블을 신설했다:
  - src='SHFE_99QH_W'   : NI, 주간(금요일 스냅샷), 톤
  - src='GFEX_OFFICIAL_W': LI, 주간(금요일, 휴장 시 직전 영업일로 최대 2일 소급), 톤
기존 src='KOMIS_WEEKLY_LME'(CU·NI LME재고)와 공존 — NI는 두 소스가 서로 다른 재고
(LME 글로벌 창고 vs 중국 SHFE 창고)이므로 병기가 맞다.

의존성: akshare(requirements.txt에 추가). 외부 API라 실패 시 해당 소스만 건너뜀.
실행: MSR_DB=<warehouse> python -m scripts.collect_exchange_inventory [--backfill]
  --backfill: GFEX 전체 백필(금요일 ~155회 호출, 0.4초 간격 — 기본은 최근 8주만 증분)
"""
from __future__ import annotations
import argparse, os, sys, time
import datetime as dt

import duckdb
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

GFEX_LIST_DATE = dt.date(2023, 7, 21)   # 탄산리튬 상장일
GFEX_SLEEP_SEC = 1.2                     # 공개 서버 예의상 호출 간격(레이트리밋 회피, 1차 0.4초에서 상향)


TABLE = "fact_inventory_exch"
DDL = (
    "CREATE TABLE IF NOT EXISTS fact_inventory_exch ("
    "commodity_code VARCHAR NOT NULL, obs_date DATE NOT NULL, val DECIMAL(20,3), "
    "unit VARCHAR, src VARCHAR NOT NULL, PRIMARY KEY (commodity_code, obs_date, src))")


def _upsert(con, df: pd.DataFrame, src: str, replace_all: bool = True):
    con.execute(DDL)
    if replace_all:
        con.execute(f"DELETE FROM {TABLE} WHERE src = ?", [src])
    con.register("_inv_df", df)
    con.execute(f"INSERT OR REPLACE INTO {TABLE} SELECT * FROM _inv_df")
    con.unregister("_inv_df")


def collect_shfe_ni() -> pd.DataFrame:
    """SHFE 니켈 주간 재고(99期货 집계) — 전체 히스토리 1회 호출."""
    import akshare as ak
    raw = ak.futures_inventory_99(symbol="镍")
    df = pd.DataFrame({
        "commodity_code": "NI",
        "obs_date": pd.to_datetime(raw["日期"]).dt.date,
        "val": pd.to_numeric(raw["库存"], errors="coerce"),
        "unit": "ton",
        "src": "SHFE_99QH_W",
    }).dropna(subset=["val"]).drop_duplicates(subset=["obs_date"], keep="last")
    return df


def _fridays(start: dt.date, end: dt.date):
    d = start + dt.timedelta(days=(4 - start.weekday()) % 7)   # 첫 금요일
    while d <= end:
        yield d
        d += dt.timedelta(days=7)


def collect_gfex_li(backfill: bool, skip_dates: set | None = None) -> pd.DataFrame:
    """GFEX 탄산리튬 창고재고(금요일 스냅샷, 휴장 시 최대 2일 소급). 증분 기본 8주.
    skip_dates: 이미 적재된 금요일(재호출 생략) — 레이트리밋 재실행 시 누락분만 채움."""
    import akshare as ak
    end = dt.date.today()
    start = GFEX_LIST_DATE if backfill else end - dt.timedelta(weeks=8)
    rows = []
    for fri in _fridays(start, end):
        if skip_dates and fri in skip_dates:
            continue
        val = None
        for back in range(3):   # 금→목→수 순으로 시도(휴장 대비)
            day = fri - dt.timedelta(days=back)
            try:
                d = ak.futures_gfex_warehouse_receipt(date=day.strftime("%Y%m%d"))
                if isinstance(d, dict) and "LC" in d and len(d["LC"]):
                    val = float(pd.to_numeric(d["LC"]["今日仓单量"], errors="coerce").sum())
                    break
            except Exception:
                pass
            time.sleep(GFEX_SLEEP_SEC)
        if val is not None:
            rows.append((fri, val))
        time.sleep(GFEX_SLEEP_SEC)
    df = pd.DataFrame(rows, columns=["obs_date", "val"])
    df["commodity_code"] = "LI"
    df["unit"] = "ton"
    df["src"] = "GFEX_OFFICIAL_W"
    return df[["commodity_code", "obs_date", "val", "unit", "src"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="GFEX 전체 백필(상장일부터)")
    a = ap.parse_args()
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)

    try:
        ni = collect_shfe_ni()
        _upsert(con, ni, "SHFE_99QH_W")
        print(f"NI(SHFE): {len(ni)}행 ({ni['obs_date'].min()}~{ni['obs_date'].max()})")
    except Exception as e:
        print(f"NI(SHFE) 수집 실패(건너뜀): {type(e).__name__}: {e}")

    try:
        con.execute(DDL)
        have = {r[0] for r in con.execute(
            "SELECT obs_date FROM fact_inventory_exch WHERE src='GFEX_OFFICIAL_W'").fetchall()}
        li = collect_gfex_li(a.backfill, skip_dates=have)
        if len(li):
            _upsert(con, li, "GFEX_OFFICIAL_W", replace_all=False)
        print(f"LI(GFEX): 신규 {len(li)}행 (기존 {len(have)}주 생략, backfill={a.backfill})")
    except Exception as e:
        print(f"LI(GFEX) 수집 실패(건너뜀): {type(e).__name__}: {e}")

    chk = con.execute("""SELECT src, commodity_code, COUNT(*), MIN(obs_date), MAX(obs_date)
        FROM fact_inventory_exch GROUP BY 1,2 ORDER BY 1,2""").df()
    print(chk.to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
