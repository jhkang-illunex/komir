import glob, os, duckdb
from pathlib import Path

# 1) 파이프라인이 쓰는 DB 절대경로
import sys; sys.path.insert(0, ".")
try:
    from msr.config import DB_PATH
    print("config.DB_PATH =", os.path.abspath(DB_PATH))
except Exception as e:
    print("config 로드 실패:", e); DB_PATH=None

# 2) 홈·프로젝트 아래 모든 .duckdb 에서 raw_customs_monthly 탐색
roots = [os.getcwd(), str(Path.home())]
seen=set()
for root in roots:
    for f in glob.glob(os.path.join(root, "**", "*.duckdb"), recursive=True):
        if f in seen: continue
        seen.add(f)
        try:
            c=duckdb.connect(f, read_only=True)
            tabs=[r[0] for r in c.execute("select table_name from information_schema.tables").fetchall()]
            has = "raw_customs_monthly" in tabs
            n = c.execute("select count(*) from raw_customs_monthly").fetchone()[0] if has else 0
            print(f"{'✅' if has else '  '} {f}  | customs행={n:,} | tables={tabs}")
            c.close()
        except Exception as e:
            print("  (열기실패)", f, e)

