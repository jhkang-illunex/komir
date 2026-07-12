# -*- coding: utf-8 -*-
"""일자별 번들 생성 — inbox의 루즈 텍스트를 collect_YYYYMMDD.tar.gz 하나로 묶어
분석 서버로의 인도 단위를 원자화한다(부분 전송·쓰는 중 읽기 문제 제거).

산출: $COLLECT_OUT/bundles/collect_YYYYMMDD.tar.gz   (tar 내부 경로: <subdir>/<파일>.txt)
원본: 삭제하지 않고 $COLLECT_OUT/_bundled/YYYYMMDD/ 로 이동(보존 정책 — 보관기간 정리는
      운영 결정 사항). 번들 파일은 .part로 쓴 뒤 rename(원자적) + 멤버수 재검증 후에만 이동.

GKG zip은 번들에 포함하지 않는다 — 15분 단위 파일이 이미 원자적이고 자체 상태(gkg_last)로
재개되므로 기존 경로($COLLECT_OUT/gkg/) 유지가 더 단순하다.
"""
from __future__ import annotations
import logging, tarfile
from datetime import date, datetime
from pathlib import Path

from . import config as C

logger = logging.getLogger("collector.bundler")

BUNDLES = C.COLLECT_OUT / "bundles"
BUNDLED = C.COLLECT_OUT / "_bundled"


def run(day: str | None = None) -> int:
    """현재 inbox의 루즈 파일 전부를 번들로 묶는다(파일명에 각자 날짜가 있으므로 번들
    이름은 '수집 실행일' 기준). 반환: 번들에 담긴 파일 수(0이면 번들 미생성)."""
    C.ensure_dirs()
    BUNDLES.mkdir(parents=True, exist_ok=True)
    day = day or date.today().strftime("%Y%m%d")

    files = sorted(p for p in C.INBOX.rglob("*.txt") if p.is_file())
    if not files:
        print("[bundle] inbox 비어있음 — 번들 생성 안 함")
        return 0

    dest = BUNDLES / f"collect_{day}.tar.gz"
    if dest.exists():        # 같은 날 재실행 → 증분 번들(suffix)
        n = 2
        while (BUNDLES / f"collect_{day}_{n}.tar.gz").exists():
            n += 1
        dest = BUNDLES / f"collect_{day}_{n}.tar.gz"

    part = dest.with_suffix(".part")
    with tarfile.open(part, "w:gz") as tf:
        for p in files:
            tf.add(p, arcname=str(p.relative_to(C.INBOX)))
    # 재검증: 멤버 수 일치 확인 후에만 원자적 rename + 원본 이동
    with tarfile.open(part, "r:gz") as tf:
        n_members = len([m for m in tf.getmembers() if m.isfile()])
    if n_members != len(files):
        part.unlink()
        raise RuntimeError(f"번들 검증 실패: 멤버 {n_members} != 원본 {len(files)}")
    part.rename(dest)

    moved_root = BUNDLED / day
    for p in files:
        rel = p.relative_to(C.INBOX)
        tgt = moved_root / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        p.rename(tgt)

    logger.info("bundle: %s (%d파일)", dest.name, len(files))
    print(f"[bundle] {dest.name} 생성({len(files)}파일) — 원본은 _bundled/{day}/로 이동")
    return len(files)


if __name__ == "__main__":
    run()
