# -*- coding: utf-8 -*-
"""[1] 입력·정리·구조화 엔트리: inbox 스캔 → 처리 → manifest → 이동."""
from pathlib import Path
from . import config as C, store


def run():
    C.ensure_dirs()
    from .archive import process_file
    known = store.known_hashes()
    files = [p for p in C.INBOX.rglob("*") if p.is_file()]
    print(f"[ingest] inbox {len(files)}건 처리 시작 (기존 {len(known)}건)")
    n, cnt = 0, {"archived": 0, "failed": 0, "unclassified": 0, "duplicate": 0}
    for p in files:
        try:
            rec = process_file(p, known)
        except Exception as e:
            print(f"  [error] {p.name}: {e}"); continue
        known.add(rec["file_hash"])
        # 파일은 이미 archive로 이동됨 → manifest도 즉시 영속화(파일당 upsert).
        # 도중 크래시 시 '이동됐지만 기록 없는' 영구 유실 방지.
        store.upsert_manifest([rec])
        n += 1
        cnt[rec.get("status", "archived")] = cnt.get(rec.get("status", "archived"), 0) + 1
        if n % 50 == 0: print(f"  ... {n}건")
    print(f"[ingest] 완료: {cnt}")
    return cnt


if __name__ == "__main__":
    run()
