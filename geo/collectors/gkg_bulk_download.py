# -*- coding: utf-8 -*-
"""GDELT GKG 2.0 벌크 원본(2016-01~) 다운로드 — 지정학 지수 1차 구축용 원자재.

DOC API(gdelt.py)와 달리 15분 단위 원시 GKG 파일(zip)을 통째로 받아 보관한다.
- 근거: DOC API는 실측상 2016년 특화쿼리가 0건이었으나, GKG 원본에는 2016-01-04에도
  니켈/코발트/리튬 언급이 실제로 존재함을 확인(WB_2934_COPPER·WB_2935_NICKEL 테마코드 +
  코발트/리튬/희토류는 코드가 없어 키워드 매칭 필요).
- 원본을 그대로 보관(필터링하지 않음) — 추후 다른 테마코드·V2Tone·GCAM 등을 다시 뽑아 쓸 수
  있도록. NAS 여유공간(42TB) 기준으로 결정(로컬 디스크 129GB로는 2.56TB 전체 보관 불가).

사용법(5개 워커 병렬, 워커당 1프로세스):
    for i in 0 1 2 3 4; do
        python3 -m geo.collectors.gkg_bulk_download --worker $i --workers 5 &
    done

저장 위치: --dest (기본 /mnt/nas2_team_ai/jhkang/광해공단/bulk/gdelt) 아래 연도별 디렉토리.
재개 가능: 이미 받은 파일이 크기까지 일치하면 건너뜀(중단 후 재실행 시 이어받기).
"""
from __future__ import annotations
import argparse, os, time
from datetime import date

import requests

MASTER_URL = "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
DEFAULT_DEST = "/mnt/nas2_team_ai/jhkang/광해공단/bulk/gdelt"
DEFAULT_MASTER_CACHE = os.path.join(os.path.dirname(__file__), "_gkg_masterfilelist_cache.txt")


def fetch_master(cache_path: str, max_age_hours: float = 6.0) -> str:
    """마스터 파일목록 캐시(수억 줄 아님, ~1.2M줄·120MB — 워커마다 재다운 방지)."""
    if os.path.exists(cache_path):
        age_h = (time.time() - os.path.getmtime(cache_path)) / 3600
        if age_h < max_age_hours:
            return cache_path
    r = requests.get(MASTER_URL, timeout=120)
    r.raise_for_status()
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(r.text)
    return cache_path


def load_targets(master_path: str, year_from: int = 2016) -> list[tuple[int, str, str, str]]:
    """(size, url, year, filename) 리스트. GKG zip만, year_from 이후만, 파일명(=시각) 정렬."""
    out = []
    with open(master_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 3:
                continue
            size_s, _hash, url = parts
            fn = url.rsplit("/", 1)[-1]
            if not fn.endswith(".gkg.csv.zip"):
                continue
            yr = fn[:4]
            if not (yr.isdigit() and int(yr) >= year_from):
                continue
            out.append((int(size_s), url, yr, fn))
    out.sort(key=lambda t: t[3])
    return out


def download_one(url: str, dest: str, size: int, retries: int = 3, timeout: int = 30) -> bool:
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return True  # 이미 완료(재개)
    tmp = dest + ".part"
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
            if os.path.getsize(tmp) == size:
                os.replace(tmp, dest)
                return True
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


def run(worker_idx: int, n_workers: int, dest_root: str, year_from: int = 2016):
    os.makedirs(dest_root, exist_ok=True)
    log_dir = os.path.join(dest_root, "_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"worker{worker_idx}.log")

    master = fetch_master(DEFAULT_MASTER_CACHE)
    targets = load_targets(master, year_from)
    # 연도 단위 라운드로빈 분배 — 워커마다 서로 다른 연도를 온전히 맡아 처음부터
    # 여러 연도 디렉토리가 동시에 채워지도록 함(파일단위 인터리빙은 전 워커가
    # 같은 시기를 동시에 훑게 되어 특정 시점엔 연도 하나만 진행되는 것처럼 보임).
    years = sorted({yr for _, _, yr, _ in targets})
    my_years = set(years[worker_idx::n_workers])
    chunk = [t for t in targets if t[2] in my_years]

    done = skip = fail = 0
    t0 = time.time()
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"[start] worker={worker_idx}/{n_workers} 담당연도={sorted(my_years)} "
                  f"{len(chunk)}건 ({date.today().isoformat()})\n")
        log.flush()
        for i, (size, url, yr, fn) in enumerate(chunk, 1):
            dest_dir = os.path.join(dest_root, yr)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, fn)
            already = os.path.exists(dest) and os.path.getsize(dest) == size
            ok = download_one(url, dest, size)
            if ok and already:
                skip += 1
            elif ok:
                done += 1
            else:
                fail += 1
                log.write(f"  FAIL {url}\n")
            if i % 500 == 0 or i == len(chunk):
                elapsed = time.time() - t0
                log.write(f"  진행 {i}/{len(chunk)} (done={done} skip={skip} fail={fail}, "
                          f"{elapsed/3600:.2f}h 경과)\n")
                log.flush()
        log.write(f"[complete] worker={worker_idx} done={done} skip={skip} fail={fail} "
                  f"total={len(chunk)} 소요={(time.time()-t0)/3600:.2f}h\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", type=int, required=True, help="워커 인덱스 0..N-1")
    ap.add_argument("--workers", type=int, default=5, help="총 워커 수")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--year-from", type=int, default=2016)
    a = ap.parse_args()
    run(a.worker, a.workers, a.dest, a.year_from)
