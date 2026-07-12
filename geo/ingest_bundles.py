# -*- coding: utf-8 -*-
"""[0.5] 수집기 일자별 번들(collect_YYYYMMDD.tar.gz) 발견 → inbox 전개 → (기본) ingest 연쇄.

수집 서버(collector/)가 공유 볼륨에 놓는 번들을 분석 서버가 주기적으로 스캔해 처리한다.
  python -m geo ingest-bundles [--dir <번들 디렉토리>] [--no-ingest]
  기본 디렉토리: $GEO_BUNDLE_DIR > $GEO_DATA/bundles_in

안전장치:
  - 처리 상태: $GEO_DATA/_logs/bundles_done.txt (번들 파일명 단위 재개 — 재실행 무해)
  - tar 경로 탈출 방어: 멤버 경로 정규화 후 inbox 밖을 가리키면 거부
  - .txt 멤버만 전개(예상 밖 페이로드 무시)
  - 이중 방어: 전개 후 ingest의 파일해시 dedup이 재처리·중복을 한 번 더 걸러줌
번들 원본은 삭제하지 않는다(보존 정책) — 보관기간 정리는 운영 결정.
"""
from __future__ import annotations
import argparse, os, tarfile
from pathlib import Path

from . import config as C


def _state_path() -> Path:
    p = C.GEO_DATA / "_logs" / "bundles_done.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_done() -> set:
    p = _state_path()
    if p.exists():
        return set(l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
    return set()


def _safe_extract(bundle: Path, inbox: Path) -> int:
    """tar 멤버를 inbox로 전개(경로 탈출 방어 + .txt만). 반환: 전개 파일 수."""
    n = 0
    inbox_resolved = inbox.resolve()
    with tarfile.open(bundle, "r:gz") as tf:
        for m in tf.getmembers():
            if not (m.isfile() and m.name.endswith(".txt")):
                continue
            dest = (inbox / m.name).resolve()
            if not str(dest).startswith(str(inbox_resolved) + os.sep):
                print(f"  [skip] 경로 탈출 의심 멤버: {m.name}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            dest.write_bytes(src.read())
            n += 1
    return n


def run(bundle_dir: str | None = None, do_ingest: bool = True) -> dict:
    C.ensure_dirs()
    bdir = Path(bundle_dir or os.environ.get("GEO_BUNDLE_DIR") or (C.GEO_DATA / "bundles_in"))
    if not bdir.exists():
        print(f"[ingest-bundles] 번들 디렉토리 없음: {bdir}")
        return {"bundles": 0, "files": 0}
    done = _load_done()
    bundles = sorted(p for p in bdir.glob("collect_*.tar.gz") if p.name not in done)
    print(f"[ingest-bundles] 신규 번들 {len(bundles)}건 (디렉토리 {bdir}, 기처리 {len(done)})")
    n_files = 0
    for b in bundles:
        try:
            n = _safe_extract(b, C.INBOX)
        except Exception as e:
            print(f"  [warn] {b.name} 전개 실패: {e} — 상태 미기록(다음 실행 재시도)")
            continue
        n_files += n
        with open(_state_path(), "a", encoding="utf-8") as f:
            f.write(b.name + "\n")
        print(f"  {b.name}: {n}파일 → inbox")
    if n_files and do_ingest:
        from . import ingest
        ingest.run()
    return {"bundles": len(bundles), "files": n_files}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None)
    ap.add_argument("--no-ingest", action="store_true")
    a = ap.parse_args()
    run(a.dir, not a.no_ingest)
