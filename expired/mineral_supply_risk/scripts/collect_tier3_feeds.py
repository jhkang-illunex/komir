# -*- coding: utf-8 -*-
"""Tier3 자체수집 (2026-07-25, 자체수집_Tier3후보_260725.md Tier3-A 실행).

수집 대상(전부 사전 접근성 실측 완료):
  1. Comtrade 공급국/수요국 흐름 5종(월간, 2016~, fact_indicator src='UN_COMTRADE'):
     - LI: 칠레(152)→세계 수출, HS 283691+253090 → 'CL_LI_EXPORT_*' (남미 염호축)
     - LI: 아르헨티나(32)→세계 수출, HS 283691 → 'AR_LI_EXPORT_*'
     - NI: 필리핀(608)→세계 수출, HS 2604 → 'PH_NI_EXPORT_*' (인니 대체공급축)
     - REE: 말레이시아(458)→세계 수출, HS 2846 → 'MY_REE_EXPORT_*' (비중국 정제축)
     - NI: 일본(392)←세계 수입, HS 7502 → 'JP_NI_IMPORT_*' (아시아 경쟁수요)
  2. USGS 구리 MIS(mis-YYYYMM-coppe.xlsx, 12월호 체인+최신호 — 지연 ~1개월 실측):
     - T2 광산생산 Total → 'CU_US_MINE_PROD' (월간, fact_indicator src='USGS_MIS')
     - T10 재고: 전체 합 → 'CU_US_STOCK_T', COMEX 창고 열 → 'CU_COMEX_STOCK_T'
       ★COMEX 재고는 cmegroup 403으로 자동수집 불가 확정했던 축의 USGS 재게재 우회
       (코발트 LME 재고와 동일 패턴). 2024-06 8.1kt→2024-12 84.7kt 급증 등 포착.

교훈 반영: 코발트 수집기의 함정들 — 원천 빈 응답 시 DELETE 차단 가드, 다중행 헤더
컬럼 탐색, 누계 라벨(January–June) 제외, 잠정 표기 접미 허용.

실행: MSR_DB=<warehouse> python -m scripts.collect_tier3_feeds
멱등: indicator 접두어 단위 DELETE 후 INSERT.
"""
from __future__ import annotations
import datetime as dt
import io
import os
import re
import sys
import time

import duckdb
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402
from scripts.collect_priority_feeds import (  # noqa: E402
    _comtrade_fetch, _month_batches, _aggregate_rows, upsert_indicator,
)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 "
                    "Firefox/127.0"}
SLEEP = 1.6

SUPPLY_FLOWS = [
    # (commodity, reporter, flow, cmdCodes, partner, indicator_prefix)
    ("LI", 152, "X", "283691,253090", 0, "CL_LI_EXPORT"),
    ("LI", 32, "X", "283691", 0, "AR_LI_EXPORT"),
    ("NI", 608, "X", "2604", 0, "PH_NI_EXPORT"),
    ("REE", 458, "X", "2846", 0, "MY_REE_EXPORT"),
    ("NI", 392, "M", "7502", 0, "JP_NI_IMPORT"),
]

USGS_BASE = ("https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/"
             "production/s3fs-public/{path}/mis-{ym}-coppe.xlsx")
_MON = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"])}


def collect_supply_flows(con) -> None:
    for cc, rep, flow, cmd, partner, prefix in SUPPLY_FLOWS:
        agg = {}
        for period in _month_batches(2016):
            rows = _comtrade_fetch(dict(reporterCode=rep, period=period,
                                        cmdCode=cmd, flowCode=flow,
                                        partnerCode=partner))
            for p, wv in _aggregate_rows(rows).items():
                w0, v0 = agg.get(p, (0.0, 0.0))
                agg[p] = (w0 + wv[0], v0 + wv[1])
            time.sleep(SLEEP)
        if len(agg) < 24:      # 무결성 가드: 비정상 축소 응답이면 기존 보존
            print(f"  [warn] {prefix}: {len(agg)}개월 — 비정상, 기존 데이터 유지")
            continue
        n = upsert_indicator(con, cc, agg, prefix)
        months = sorted(agg.keys())
        print(f"  {prefix}({cc}): 월 {len(agg)}개({months[0]}~{months[-1]}) → {n}행")


def _fetch_issue(ym: str) -> pd.ExcelFile | None:
    for path in ("media/files", "atoms/files"):
        for attempt in range(3):
            try:
                r = requests.get(USGS_BASE.format(path=path, ym=ym), headers=UA,
                                 timeout=60)
                break
            except requests.exceptions.RequestException:
                time.sleep(5 * (attempt + 1))
        else:
            continue
        if r.status_code == 200:
            try:
                return pd.ExcelFile(io.BytesIO(r.content))
            except Exception:
                return None
    return None


def _num(x) -> float | None:
    """'92,900 r'·'40,000 e' 등 개정/추정 표기 제거 후 숫자화."""
    s_ = str(x).replace(",", "").strip()
    s_ = re.sub(r"\s*[re]\s*$", "", s_)
    try:
        v = float(s_)
        return v if np.isfinite(v) else None
    except ValueError:
        return None


def _parse_month_rows(t: pd.DataFrame, val_fn) -> list[tuple[dt.date, float]]:
    """연도 블록('2024'/'2024:'/'2021, December')×월 행 공통 파서.
    val_fn(row) → float|None. 누계('January–June')는 _MON 미매치로 자동 제외."""
    rows, year = [], None
    for _, row in t.iterrows():
        lab = str(row[0]).strip()
        m = re.match(r"^((?:19|20)\d{2})[:,]?\s*(\S*)", lab)
        if m:
            # 연도 행("2024"/"2024:"/"2021, December"/"2025 (P)") — 접미가 월이
            # 아니면 연도만 갱신(Cochilco '(P)' 버그 패턴 방지: 연도 갱신 누락 금지)
            year = int(m.group(1))
            mon = _MON.get(m.group(2).rstrip(","))
        elif lab in _MON and year is not None:
            mon = _MON[lab]
        else:
            continue
        if mon is None:
            continue
        v = val_fn(row)
        if v is not None and np.isfinite(v):
            rows.append((dt.date(year, mon, 1), float(v)))
    return rows


def _issue_series(x: pd.ExcelFile) -> dict[str, list]:
    out = {}
    # T2 광산생산: 'Total' 컬럼 위치를 헤더에서 탐색
    t2 = x.parse("T2", header=None)
    head = t2.head(8).astype(str)
    tot_col = next((j for j in range(t2.shape[1])
                    if any(head[j].str.strip().str.match(r"^Total\d*$"))), 3)
    out["CU_US_MINE_PROD"] = _parse_month_rows(t2, lambda r: _num(r[tot_col]))
    # T10 재고: 다중행 헤더 — COMEX 열 탐색, 전체=숫자열 합
    t10 = x.parse("T10", header=None)
    head = t10.head(6).astype(str)
    comex_col = next((j for j in range(t10.shape[1])
                      if any(head[j].str.contains("COMEX"))), None)
    ncols = t10.shape[1]

    def total_fn(row):
        vals = [_num(row[j]) for j in range(1, ncols)]
        ok = [v for v in vals if v is not None]
        return float(sum(ok)) if len(ok) >= 3 else None

    out["CU_US_STOCK_T"] = _parse_month_rows(t10, total_fn)
    if comex_col is not None:
        out["CU_COMEX_STOCK_T"] = _parse_month_rows(
            t10, lambda r: _num(r[comex_col]))
    return out


def collect_usgs_cu(con) -> None:
    yms = [f"{y}12" for y in range(2018, 2026)]  # 201812 atoms 존재 실측 — 2017-12부터 커버
    # 최신 발행 호 역순 탐색(발행 지연이 유동적 — 202512 403·202506 존재 실측):
    # 이번 달부터 24개월 역순으로 첫 응답 호 1개를 추가(연말호 체인과 병합)
    today = dt.date.today()
    for k in range(24):
        y, m = (today.year * 12 + today.month - 1 - k) // 12, \
               (today.year * 12 + today.month - 1 - k) % 12 + 1
        ym = f"{y}{m:02d}"
        if ym in yms:
            continue
        if _fetch_issue(ym) is not None:
            yms.append(ym)
            print(f"  최신호 탐지: {ym}")
            break
    series: dict[str, dict] = {}
    for ym in yms:
        x = _fetch_issue(ym)
        if x is None:
            continue
        try:
            got = _issue_series(x)
        except Exception as e:
            print(f"  [warn] USGS coppe {ym}: 파싱 실패({type(e).__name__}) — 건너뜀")
            continue
        n = sum(len(v) for v in got.values())
        if n == 0:
            print(f"  [warn] USGS coppe {ym}: 파싱 0행 — 건너뜀")
            continue
        for k, rows in got.items():
            d = series.setdefault(k, {})
            for date, v in rows:
                d[date] = v          # 나중 호가 과거 호를 덮어씀(개정 반영)
        print(f"  USGS coppe {ym}: {n}행")
    for ind, d in series.items():
        # COMEX 열은 2023-12부터만 존재(실측) — 가드 완화(15), 짧음은 하네스가
        # 커버리지 교란 플래그로 처리
        if len(d) < 15:
            print(f"  [warn] {ind}: {len(d)}개월 — 비정상 축소, 기존 데이터 유지")
            continue
        df = pd.DataFrame({
            "commodity_code": "CU", "indicator": ind, "freq": "M",
            "obs_date": sorted(d.keys()),
            "val": [d[k] for k in sorted(d.keys())], "src": "USGS_MIS"})
        con.execute("DELETE FROM fact_indicator WHERE indicator = ?", [ind])
        con.register("_u", df)
        con.execute("INSERT INTO fact_indicator SELECT * FROM _u")
        con.unregister("_u")
        print(f"  {ind}: {len(df)}행 ({df['obs_date'].min()}~{df['obs_date'].max()})")


def main() -> None:
    db = os.environ.get("MSR_DB", DB_PATH)
    print(f"[collect_tier3_feeds] DB={db}")
    con = duckdb.connect(db)
    print("1) Comtrade 흐름 5종(칠레·아르헨 LI, 필리핀 NI, 말레이 REE, 일본 NI수입)")
    collect_supply_flows(con)
    print("2) USGS 구리 MIS(광산생산·미국 재고·COMEX 재고)")
    collect_usgs_cu(con)
    con.close()
    print("완료")


if __name__ == "__main__":
    main()
