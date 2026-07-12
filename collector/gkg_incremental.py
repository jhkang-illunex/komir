# -*- coding: utf-8 -*-
"""GDELT GKG 증분 다운로드 — 벌크(gkg_bulk_download.py, 역사 백필용)의 운영 후속.

GKG 파일은 15분 간격의 결정적 타임스탬프(YYYYMMDDHHMMSS.gkg.csv.zip)라서 마스터리스트
(수백 MB) 없이 "마지막 수신 시각 이후의 기대 파일명"을 생성해 직접 받는다. 결측 배치
(GDELT 쪽 누락)는 404 — 몇 번 재시도 후 건너뛴 것으로 기록해 다음 주기에 무한 재시도하지
않는다. 상태는 $COLLECT_OUT/_state/gkg_last.txt (마지막 처리 타임스탬프).

산출: $COLLECT_OUT/gkg/<YYYY>/<ts>.gkg.csv.zip — 분석 서버 `geo gkg-parse --bulk-root` 호환.
"""
from __future__ import annotations
import logging, time
from datetime import datetime, timedelta, timezone

import requests

from . import config as C

logger = logging.getLogger("collector.gkg")

BASE = "http://data.gdeltproject.org/gdeltv2"
_LAG_MIN = 30          # 최신 배치는 게시 지연이 있어 now-30분까지만 시도
_RATE_SECS = 1


def _state_file():
    C.ensure_dirs()
    return C.STATE / "gkg_last.txt"


def _skip_file():
    C.ensure_dirs()
    return C.STATE / "gkg_skipped.txt"


def _load_last() -> datetime:
    f = _state_file()
    if f.exists():
        try:
            return datetime.strptime(f.read_text().strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # 최초 실행: 최근 1일치부터(역사 백필은 벌크 다운로더 몫)
    return datetime.now(timezone.utc) - timedelta(days=1)


def _quarter_align(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def run(max_files: int = 0) -> int:
    C.ensure_dirs()
    last = _quarter_align(_load_last())
    end = _quarter_align(datetime.now(timezone.utc) - timedelta(minutes=_LAG_MIN))
    ts = last + timedelta(minutes=15)
    n_ok = n_miss = 0
    sess = requests.Session()
    while ts <= end:
        name = ts.strftime("%Y%m%d%H%M%S") + ".gkg.csv.zip"
        dest_dir = C.GKG_OUT / ts.strftime("%Y")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        if not dest.exists():
            time.sleep(_RATE_SECS)
            ok = False
            for attempt in range(3):
                try:
                    r = sess.get(f"{BASE}/{name}", timeout=C.HTTP_TIMEOUT,
                                 headers={"User-Agent": C.UA})
                    if r.status_code == 404:
                        break                       # GDELT 쪽 결측 배치 — 재시도 무의미
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    tmp.write_bytes(r.content)
                    tmp.rename(dest)
                    ok = True
                    break
                except Exception as e:
                    logger.warning("gkg %s 실패(%d/3): %s", name, attempt + 1, e)
                    time.sleep(2 * (attempt + 1))
            if ok:
                n_ok += 1
            else:
                n_miss += 1
                with open(_skip_file(), "a") as f:
                    f.write(name + "\n")
        _state_file().write_text(ts.strftime("%Y%m%d%H%M%S"))
        ts += timedelta(minutes=15)
        if max_files and (n_ok + n_miss) >= max_files:
            break
    logger.info("gkg 증분: 수신 %d, 결측 %d (last=%s)", n_ok, n_miss, _state_file().read_text())
    print(f"[gkg] 증분 수신 {n_ok}건, 결측 {n_miss}건")
    return n_ok


if __name__ == "__main__":
    run()
